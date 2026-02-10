import json
import os
from typing import Dict, Optional

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
]


class GoogleAuthConfigError(RuntimeError):
    """Raised when Google auth configuration is missing or invalid."""


def _load_streamlit_secret(name: str):
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        return None


def _payload_from_json_string(raw_json: str) -> Dict:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise GoogleAuthConfigError(f"Google 인증 JSON 파싱 실패: {exc}") from exc

    if not isinstance(parsed, dict):
        raise GoogleAuthConfigError("Google 인증 JSON 형식이 올바르지 않습니다.")

    # Accept direct Google credential JSON
    if parsed.get("type") in {"authorized_user", "service_account"}:
        return {"type": parsed["type"], "data": parsed}

    # Accept wrapped payload: {"type": "authorized_user", "data": {...}}
    wrapped_type = parsed.get("type")
    wrapped_data = parsed.get("data")
    if wrapped_type in {"authorized_user", "service_account"} and isinstance(wrapped_data, dict):
        return {"type": wrapped_type, "data": wrapped_data}

    raise GoogleAuthConfigError(
        "Google 인증 JSON 형식이 올바르지 않습니다. authorized_user 또는 service_account JSON을 사용하세요."
    )


def describe_available_auth_source() -> str:
    if _load_streamlit_secret("gcp_oauth_user"):
        return "Streamlit secrets: gcp_oauth_user"
    if os.getenv("GOOGLE_OAUTH_USER_JSON", "").strip():
        return "환경변수: GOOGLE_OAUTH_USER_JSON"
    if _load_streamlit_secret("gcp_service_account"):
        return "Streamlit secrets: gcp_service_account"
    if os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        return "환경변수: GOOGLE_SERVICE_ACCOUNT_JSON"
    return ""


def _read_credentials_payload(credential_json_override: Optional[str] = None) -> Dict:
    """Prefer in-app override, then OAuth user JSON, then service-account JSON."""
    if (credential_json_override or "").strip():
        return _payload_from_json_string(credential_json_override.strip())

    oauth_info = _load_streamlit_secret("gcp_oauth_user")
    if oauth_info:
        return {"type": "authorized_user", "data": dict(oauth_info)}

    oauth_raw = os.getenv("GOOGLE_OAUTH_USER_JSON", "").strip()
    if oauth_raw:
        return _payload_from_json_string(oauth_raw)

    sa_info = _load_streamlit_secret("gcp_service_account")
    if sa_info:
        return {"type": "service_account", "data": dict(sa_info)}

    sa_raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_raw:
        return _payload_from_json_string(sa_raw)

    raise GoogleAuthConfigError(
        "Google 인증정보가 없습니다. 아래 중 하나를 설정하세요: "
        "(1) Streamlit secrets gcp_oauth_user (권장), "
        "(2) 환경변수 GOOGLE_OAUTH_USER_JSON, "
        "(3) Streamlit secrets gcp_service_account, "
        "(4) 환경변수 GOOGLE_SERVICE_ACCOUNT_JSON, "
        "(5) 앱 내 인증 JSON 직접 입력."
    )


def _build_google_services(credential_json_override: Optional[str] = None):
    from googleapiclient.discovery import build

    payload = _read_credentials_payload(credential_json_override)

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


def upload_report_as_google_doc(*, title: str, body_text: str, folder_id: str, credential_json_override: str = "") -> str:
    docs_service, drive_service = _build_google_services(credential_json_override or None)

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
