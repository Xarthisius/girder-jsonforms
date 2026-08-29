"""Resolving which ORCID flavor this instance talks to.

``girder-wholetale`` registers production ORCID and the ORCID sandbox as two
separate OAuth providers (``orcid`` and ``orcid_sandbox``), each with its own
client credentials and its own callback URL, and both can be enabled at once.
So "the ORCID provider" is no longer a single well-known entry in
``providers.idMap`` -- this plugin has to say which one it means, via the
``jsonforms.orcid_provider`` setting.

The ``girder_wholetale`` import is deferred into the functions: importing it
pulls in ``girder_wholetale.lib``, which touches the database at import time.
"""

import logging

import requests
from girder.models.setting import Setting
from girder_oauth import providers
from girder_oauth.providers import addProvider

from ..settings import PluginSettings

logger = logging.getLogger(__name__)

# Client-credentials tokens for the public API, keyed by provider name. The two
# flavors have distinct credentials and distinct token endpoints, so a single
# cache slot would hand sandbox tokens to production requests and vice versa.
_orcid_headers = {}


def orcid_providers():
    """The ORCID provider classes girder-wholetale offers."""
    from girder_wholetale.lib.orcid import ORCID, SandboxORCID

    return (ORCID, SandboxORCID)


def orcid_provider_names():
    return tuple(provider.getProviderName() for provider in orcid_providers())


def register_orcid_providers():
    """Make both ORCID flavors resolvable through ``providers.idMap``.

    ``WholeTalePlugin.load()`` already does this, but girder-worker processes
    never load Girder plugins, and the ORCID tasks run there.
    """
    for provider in orcid_providers():
        addProvider(provider)


def get_orcid_provider():
    """Return the configured ORCID provider class, or None if unavailable."""
    name = Setting().get(PluginSettings.ORCID_PROVIDER)
    provider = providers.idMap.get(name)
    if provider is None:
        logger.error(
            "ORCID provider %r is not registered; set %s to one of %s",
            name,
            PluginSettings.ORCID_PROVIDER,
            ", ".join(orcid_provider_names()),
        )
    return provider


def get_orcid_headers(provider):
    """Headers for public-API reads, using ``provider``'s own credentials."""
    name = provider.getProviderName()
    if name not in _orcid_headers:
        token_response = requests.post(
            provider._TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": Setting().get(provider._CLIENT_ID_SETTING),
                "client_secret": Setting().get(provider._CLIENT_SECRET_SETTING),
                "grant_type": "client_credentials",
                "scope": "/read-public",
            },
        )
        token_response.raise_for_status()
        _orcid_headers[name] = {
            "Accept": "application/vnd.orcid+json",
            "Authorization": "Bearer " + token_response.json()["access_token"],
        }
    return _orcid_headers[name]
