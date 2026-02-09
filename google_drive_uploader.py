import json
import os
from typing import Dict

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
]


def _read_service_account_info() -> Dict:
    """Read service account JSON from Streamlit secrets or env var."""
    # Keep import local so module can still be imported outside streamlit runtime.
    try:
        import streamlit as st

        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass

    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if raw:
        return json.loads(raw)

    raise RuntimeError(
        "Google service account 설정이 없습니다. "
        "st.secrets['gcp_service_account'] 또는 GOOGLE_SERVICE_ACCOUNT_JSON을 설정하세요."
    )


def upload_report_as_google_doc(
    *,
    title: str,
    body_text: str,
    folder_id: str,
) -> str:
    """Create a Google Doc with body_text and move it to selected shared folder.

    Returns the document URL.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = _read_service_account_info()
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)

    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    safe_text = (body_text or "").replace("\x00", " ")
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": safe_text,
                    }
                }
            ]
        },
    ).execute()

    if folder_id.strip():
        # Move file into shared folder
        file_meta = drive_service.files().get(fileId=doc_id, fields="parents").execute()
        prev_parents = ",".join(file_meta.get("parents", []))
        drive_service.files().update(
            fileId=doc_id,
            addParents=folder_id.strip(),
            removeParents=prev_parents,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()

    return f"https://docs.google.com/document/d/{doc_id}/edit"
