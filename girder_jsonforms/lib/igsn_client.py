"""Client for the centralized IGSN registry service.

Girder keeps a full local ``Deposition`` for every IGSN -- it needs one for
ACLs, search, sample tracking and project wiring -- but the *identifier* is
negotiated with the service, and publication to DataCite is delegated to it.
Without ``jsonforms.igsn_service_url`` set, none of this is used and the plugin
allocates from its own ``PrefixCounter`` exactly as before.

Two rules matter here:

* ``allocate``/``allocate_children`` are **not** idempotent -- a retried
  allocation consumes another block of sequence numbers. So retries are enabled
  only for GET/PUT, never for the allocating POSTs.
* There is deliberately **no local fallback**. If the service is unreachable,
  minting fails loudly. Falling back to a local counter would recreate the
  divergence between instances that this service exists to eliminate.
"""

import logging

import requests
from girder.models.setting import Setting
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..settings import PluginSettings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class IGSNServiceError(Exception):
    """The IGSN registry service could not satisfy a request.

    Deliberately fatal to whatever operation raised it: a Girder deposition must
    never exist without a matching record in the registry.
    """

    def __init__(self, message, status_code=None, detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class IGSNClient:
    def __init__(self, base_url, token, timeout=DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )
        # Idempotent verbs only. POST /identifiers must never be auto-retried.
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "PUT"]),
        )
        self._session.mount("http://", HTTPAdapter(max_retries=retry))
        self._session.mount("https://", HTTPAdapter(max_retries=retry))

    # -- plumbing ---------------------------------------------------------- #

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}/api/v1{path}"
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = self._session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            raise IGSNServiceError(
                f"IGSN service at {self.base_url} is unreachable: {exc}"
            ) from exc

        if response.status_code >= 400:
            detail = None
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:500]
            raise IGSNServiceError(
                f"IGSN service returned {response.status_code} for "
                f"{method} {path}: {detail}",
                status_code=response.status_code,
                detail=detail,
            )
        if not response.content:
            return None
        return response.json()

    # -- allocation -------------------------------------------------------- #

    def allocate(
        self, prefix, count=1, metadata=None, landing_page=None, external_ref=None
    ):
        """Allocate top-level IGSNs. Returns a list of record dicts.

        NOT idempotent. Do not retry on an ambiguous failure -- use
        ``list_records(prefix=...)`` to find out what was actually allocated.
        """
        body = {"prefix": prefix, "count": count}
        if metadata:
            body["metadata"] = metadata
        if landing_page:
            body["landing_page"] = landing_page
        if external_ref:
            body["external_ref"] = external_ref
        return self._request("POST", "/identifiers", json=body)["records"]

    def allocate_children(
        self, igsn, indices=None, count=None, metadata=None, local_identifiers=None
    ):
        """Register children of ``igsn``.

        Pass ``indices`` when the caller computed the labels (Girder's
        lab-specific batch strategies produce things like ``S1R2C3``), or
        ``count`` to let the service pick the next free numeric ones.

        Fails whole rather than partially, so a caller that aborts its own batch
        on error never ends up holding children the registry doesn't know about.
        """
        body = {}
        if indices is not None:
            body["indices"] = list(indices)
        if count is not None:
            body["count"] = count
        if metadata:
            body["metadata"] = metadata
        if local_identifiers:
            body["local_identifiers"] = local_identifiers
        return self._request("POST", f"/identifiers/{igsn}/children", json=body)[
            "records"
        ]

    # -- records ----------------------------------------------------------- #

    def get_record(self, igsn):
        """Fetch a record, or None if the registry doesn't have it."""
        try:
            return self._request("GET", f"/records/{igsn}")
        except IGSNServiceError as exc:
            if exc.status_code == 404:
                return None
            raise

    def list_records(self, prefix=None, status=None, parent=None, limit=100, offset=0):
        params = {"limit": limit, "offset": offset}
        if prefix:
            params["prefix"] = prefix
        if status:
            params["status"] = status
        if parent:
            params["parent"] = parent
        return self._request("GET", "/records", params=params)

    def put_record(self, igsn, metadata=None, landing_page=None, external_ref=None):
        body = {}
        if metadata is not None:
            body["metadata"] = metadata
        if landing_page is not None:
            body["landing_page"] = landing_page
        if external_ref is not None:
            body["external_ref"] = external_ref
        return self._request("PUT", f"/records/{igsn}", json=body)

    def publish(self, igsn, target="findable", recurse=False):
        """Queue publication to DataCite. Returns immediately; poll for status."""
        return self._request(
            "POST",
            f"/records/{igsn}/publish",
            json={"target": target, "recurse": recurse},
        )

    def revoke(self, igsn):
        """Tombstone a reserved identifier. Never frees the sequence number."""
        return self._request("POST", f"/records/{igsn}/revoke")

    # -- vocabularies ------------------------------------------------------ #

    def vocabularies(self):
        return self._request("GET", "/vocabularies")

    def whoami(self):
        return self._request("GET", "/whoami")


def service_settings():
    """Return ``(url, token)`` from settings, either possibly empty."""
    return (
        (Setting().get(PluginSettings.IGSN_SERVICE_URL) or "").strip(),
        (Setting().get(PluginSettings.IGSN_SERVICE_TOKEN) or "").strip(),
    )


def is_remote():
    """True when this instance delegates identifier allocation to the service."""
    url, _ = service_settings()
    return bool(url)


def get_client():
    """Build a client, or None when this instance is in local mode.

    A configured URL with no token is a misconfiguration, not a reason to
    silently fall back to local counters -- so it raises.
    """
    url, token = service_settings()
    if not url:
        return None
    if not token:
        raise IGSNServiceError(
            f"{PluginSettings.IGSN_SERVICE_URL} is set to {url!r} but "
            f"{PluginSettings.IGSN_SERVICE_TOKEN} is empty"
        )
    return IGSNClient(url, token)
