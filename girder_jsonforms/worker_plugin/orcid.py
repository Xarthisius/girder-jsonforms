import datetime
import requests
import urllib.parse as urlparse

import os

from girder.models.user import User
from girder_worker.app import app
from girder_oauth import providers
from girder.utility.model_importer import ModelImporter

_domain = os.environ.get("DOMAIN", "example.com")
_hosts = {
    "organization": [
        {
            "name": "Hopkins Extreme Materials Institute",
            "address": {"city": "Baltimore", "region": "Maryland", "country": "US"},
            "disambiguated-organization": {
                "disambiguated-organization-identifier": "https://ror.org/02ed2th17",
                "disambiguation-source": "ROR",
            },
        }
    ]
}

_resource_items = [
    {
        "resource-name": "MAXIMA",
        "resource-type": "equipment",
        "hosts": _hosts,
        "external-ids": {
            "external-id": [
                {
                    "external-id-type": "doi",
                    "external-id-value": "10.34863/ybhd-a260",
                    "external-id-url": "https://doi.org/10.34863/ybhd-a260",
                    "external-id-relationship": "self",
                }
            ]
        },
        "url": "https://hemi.jhu.edu/caimee/center-facilities/aimd-l/#1745356027264-0fcae1de-66a4",
    },
    {
        "resource-name": "HELIX",
        "resource-type": "equipment",
        "hosts": _hosts,
        "external-ids": {
            "external-id": [
                {
                    "external-id-type": "doi",
                    "external-id-value": "10.34863/kp4k-5g15",
                    "external-id-url": "https://doi.org/10.34863/kp4k-5g15",
                    "external-id-relationship": "self",
                }
            ]
        },
        "url": "https://hemi.jhu.edu/caimee/center-facilities/aimd-l/#1745356027264-0fcae1de-66a4",
    },
    {
        "resource-name": "SPHINX",
        "resource-type": "equipment",
        "hosts": _hosts,
        "external-ids": {
            "external-id": [
                {
                    "external-id-type": "doi",
                    "external-id-value": "10.34863/0njd-tk10",
                    "external-id-url": "https://doi.org/10.34863/0njd-tk10",
                    "external-id-relationship": "self",
                }
            ]
        },
        "url": "https://hemi.jhu.edu/caimee/center-facilities/aimd-l/#1745438879173-208b1f97-0fd2",
    },
]


@app.task(queue="local")
def register_project_with_orcid(user_id, project_id):
    provider = providers.idMap.get("orcid")
    ProjectModel = ModelImporter.model("project", plugin="jsonforms")
    if provider is None:
        raise ValueError("Provider 'orcid' not found")

    api_url = provider._API_USER_URL
    resource_server = urlparse.urlparse(provider._AUTH_URL).netloc

    user = User().load(user_id, force=True)
    for token in user.get("otherTokens", []):
        if token["resource_server"] == resource_server:
            break
    else:
        raise ValueError(f"No token found for resource server '{resource_server}'")

    project = ProjectModel.load(project_id, force=True)
    if project["status"] != "accepted":
        print("Project must be accepted before registering with ORCID")
        return

    api_url_netloc = urlparse.urlparse(api_url).netloc
    for orcid_resource in project.get("orcidResourceUrl", []):
        if (
            orcid_resource["orcid"] == token["orcid"]
            and urlparse.urlparse(orcid_resource["url"]).netloc == api_url_netloc
        ):
            print(f"Project already registered with ORCID at {orcid_resource['url']}")
            url = orcid_resource["url"]
            method = "PUT"
            break
    else:
        url = api_url.format(orcid=token["orcid"], path="/research-resource")
        method = "POST"

    now = datetime.datetime.now(datetime.UTC)
    end = now + datetime.timedelta(days=180)
    payload = {
        "proposal": {
            "title": {"title": {"value": project["name"]}},
            "hosts": _hosts,
            "external-ids": {
                "external-id": [
                    {
                        "external-id-type": "source-work-id",
                        "external-id-value": project["projectId"],
                        "external-id-url": f"https://projects.{_domain}/proposal/{project['_id']}",
                        "external-id-relationship": "self",
                    }
                ]
            },
            "start-date": {
                "year": {"value": now.year},
                "month": {"value": now.month},
                "day": {"value": now.day},
            },
            "end-date": {
                "year": {"value": end.year},
                "month": {"value": end.month},
                "day": {"value": end.day},
            },
            "url": {
                "value": f"https://projects.{_domain}/proposa/{project['projectId']}"
            },
        },
        "resource-item": _resource_items,
    }
    headers = {
        "Accept": "application/vnd.orcid+json",
        "Content-type": "application/json",
        "Authorization": f"Bearer {token['access_token']}",
    }
    if method == "PUT":
        payload["put-code"] = url.split("/")[-1]
        resp = requests.put(url, headers=headers, json=payload)
        if not resp.ok:
            raise ValueError(
                f"Failed to update project registration with ORCID: {resp.status_code} {resp.text}"
            )
    else:
        resp = requests.post(
            api_url.format(orcid=token["orcid"], path="/research-resource"),
            headers=headers,
            json=payload,
        )

        if not resp.ok:
            raise ValueError(
                f"Failed to register project with ORCID: {resp.status_code} {resp.text}"
            )

        location = resp.headers.get("Location")
        if not location:
            raise ValueError("No Location header in ORCID response")
        print(f"Project registered with ORCID at {location} for ORCID {token['orcid']}")
        ProjectModel.collection.update_one(
            {"_id": project["_id"]},
            {"$push": {"orcidResourceUrl": {"orcid": token["orcid"], "url": location}}},
        )
