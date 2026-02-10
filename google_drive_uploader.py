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


def _friendly_http_error(exc: Exception, payload: Dict) -> GoogleAuthConfigError:
    from googleapiclient.errors import HttpError

    if not isinstance(exc, HttpError):
        return GoogleAuthConfigError(str(exc))

    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 403:
        if payload.get("type") == "service_account":
            sa_email = (payload.get("data") or {}).get("client_email", "(service account email 없음)")
            return GoogleAuthConfigError(
                "Google Docs API 권한이 없습니다(403). "
                "서비스 계정을 사용 중이면 아래를 확인하세요: "
                "(1) Google Cloud 프로젝트에서 Google Docs API/Drive API 활성화, "
                f"(2) 대상 Drive 폴더를 서비스 계정({sa_email})에 편집자(Editor)로 공유, "
                "(3) 조직 정책상 외부 앱/서비스 계정 차단 여부 확인."
            )

        return GoogleAuthConfigError(
            "Google Docs API 권한이 없습니다(403). "
            "OAuth 사용자 인증을 사용 중이면 계정이 Google Docs 사용 가능 상태인지, "
            "그리고 조직 정책에서 Docs/Drive API 호출이 차단되지 않았는지 확인하세요."
        )

    if status == 401:
        return GoogleAuthConfigError("Google 인증이 만료되었거나 유효하지 않습니다(401). 인증 JSON을 다시 설정하세요.")

    return GoogleAuthConfigError(f"Google API 요청 실패({status}): {exc}")


def upload_report_as_google_doc(*, title: str, body_text: str, folder_id: str, credential_json_override: str = "") -> str:
    payload = _read_credentials_payload(credential_json_override or None)
    docs_service, drive_service = _build_google_services(credential_json_override or None)

    try:
        doc = docs_service.documents().create(body={"title": title}).execute()
    except Exception as exc:
        raise _friendly_http_error(exc, payload) from exc

    doc_id = doc["documentId"]

    try:
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
    except Exception as exc:
        raise _friendly_http_error(exc, payload) from exc

    folder_id = (folder_id or "").strip()
    if folder_id:
        try:
            parent_info = drive_service.files().get(fileId=doc_id, fields="parents", supportsAllDrives=True).execute()
            prev_parents = ",".join(parent_info.get("parents", []))
            drive_service.files().update(
                fileId=doc_id,
                addParents=folder_id,
                removeParents=prev_parents,
                supportsAllDrives=True,
                fields="id, parents",
            ).execute()
        except Exception as exc:
            raise _friendly_http_error(exc, payload) from exc

    return f"https://docs.google.com/document/d/{doc_id}/edit"
