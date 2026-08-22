"""Shared provider payloads for the adapter tests.

AZ_PROFILE and AZ_VALUES are a contract. Later tasks import both names.
"""

AZ_PROFILE = {
    "slug": "northwind",
    "tracker": {"kind": "azure", "org": "https://dev.azure.com/northwind",
                "project": "Contoso migration", "api_version": "7.1-preview",
                "auth_env": {"user": "AZDO_USER", "token": "AZDO_PAT"}},
    "host": {"kind": "azure-repos", "repo": "Contoso.migration",
             "repo_id": "repo-guid", "project_id": "proj-guid",
             "base_branch": "master", "local_path": "/repos/Contoso-migration",
             "identity": {"name": "Example.Dev", "email": "k@example.com"},
             "auth_env": {"user": "AZDO_USER", "token": "AZDO_PAT"}},
    "link_rules": {"link_types": ["Task"], "never_link_types": ["Bug"]},
}
AZ_VALUES = {"AZDO_USER": "me@example.com", "AZDO_PAT": "patpatpatpat1234"}

AZ_WORKITEM = {
    "id": 59644,
    "fields": {
        "System.WorkItemType": "Task",
        "System.State": "To Do",
        "System.Title": "Add the tracking fields",
        "System.AssignedTo": {"displayName": "Example Dev"},
        "System.Description": (
            "<table><tr><td>Brookfield</td><td>GTM-42</td></tr></table>"
            "<p>See https://www.figma.com/design/ABC/x?node-id=1-2</p>"),
        "System.Parent": 59614,
    },
    "relations": [
        {"rel": "System.LinkTypes.Hierarchy-Reverse",
         "url": "https://dev.azure.com/northwind/_apis/wit/workItems/59614"},
        {"rel": "System.LinkTypes.Hierarchy-Forward",
         "url": "https://dev.azure.com/northwind/_apis/wit/workItems/59645"},
        {"rel": "AttachedFile", "attributes": {"name": "shot.png"},
         "url": "https://dev.azure.com/northwind/_apis/wit/attachments/aaa"},
    ],
    "_links": {"html": {"href": "https://dev.azure.com/northwind/_workitems/edit/59644"}},
}
AZ_COMMENTS = {"comments": [
    {"id": 1, "createdBy": {"displayName": "Sam"},
     "createdDate": "2026-08-01T10:00:00Z",
     "text": "<p>for Brookfield the id is GTM-42</p>"},
]}
