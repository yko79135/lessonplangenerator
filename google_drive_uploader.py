import json
import os
from typing import Dict

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
]


def _load_streamlit_secret(name: str):
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        return None


def _read_credentials_payload() -> Dict:
    """Prefer OAuth user credential JSON, fallback to service account JSON."""
    oauth_info = _load_streamlit_secret("gcp_oauth_user")
    if oauth_info:
        return {"type": "authorized_user", "data": dict(oauth_info)}

    oauth_raw = os.getenv("GOOGLE_OAUTH_USER_JSON", "").strip()
    if oauth_raw:
        return {"type": "authorized_user", "data": json.loads(oauth_raw)}

    sa_info = _load_streamlit_secret("gcp_service_account")
    if sa_info:
        return {"type": "service_account", "data": dict(sa_info)}

    sa_raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_raw:
        return {"type": "service_account", "data": json.loads(sa_raw)}

    raise RuntimeError(
        "Google 인증정보가 없습니다. GOOGLE_OAUTH_USER_JSON(권장) 또는 GOOGLE_SERVICE_ACCOUNT_JSON을 설정하세요."
    )


def _build_google_services():
    from googleapiclient.discovery import build

    payload = _read_credentials_payload()
    creds = None

    if payload["type"] == "authorized_user":
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_info(payload["data"], scopes=SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
    else:
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(payload["data"], scopes=SCOPES)

    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return docs_service, drive_service


def upload_report_as_google_doc(*, title: str, body_text: str, folder_id: str) -> str:
    docs_service, drive_service = _build_google_services()

    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": (body_text or "").replace("\x00", " "),
                    }
                }
            ]
        },
    ).execute()

    folder_id = (folder_id or "").strip()
    if folder_id:
        parent_info = drive_service.files().get(fileId=doc_id, fields="parents", supportsAllDrives=True).execute()
        prev_parents = ",".join(parent_info.get("parents", []))
        drive_service.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents=prev_parents,
            supportsAllDrives=True,
            fields="id, parents",
        ).execute()

    return f"https://docs.google.com/document/d/{doc_id}/edit"
