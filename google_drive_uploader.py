import json
import os
from typing import Dict, Optional, Union

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
    if parsed.get("type") == "authorized_user":
        return {"type": "authorized_user", "data": parsed}

    # Accept wrapped payload: {"type": "authorized_user", "data": {...}}
    wrapped_type = parsed.get("type")
    wrapped_data = parsed.get("data")
    if wrapped_type == "authorized_user" and isinstance(wrapped_data, dict):
        return {"type": "authorized_user", "data": wrapped_data}

    raise GoogleAuthConfigError("Google 인증 JSON 형식이 올바르지 않습니다. authorized_user JSON을 사용하세요.")


def _client_payload_from_json_string(raw_json: str) -> Dict:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise GoogleAuthConfigError(f"OAuth 클라이언트 JSON 파싱 실패: {exc}") from exc

    if not isinstance(parsed, dict):
        raise GoogleAuthConfigError("OAuth 클라이언트 JSON 형식이 올바르지 않습니다.")

    if parsed.get("type") == "authorized_user":
        raise GoogleAuthConfigError(
            "OAuth Client JSON 자리에는 authorized_user JSON을 넣을 수 없습니다. "
            "Google Cloud Console > APIs & Services > Credentials에서 다운로드한 OAuth 클라이언트 JSON(web/installed)을 사용하세요."
        )

    if "installed" in parsed and isinstance(parsed["installed"], dict):
        return parsed["installed"]
    if "web" in parsed and isinstance(parsed["web"], dict):
        return parsed["web"]

    if all(k in parsed for k in ["client_id", "client_secret", "auth_uri", "token_uri"]):
        return parsed

    raise GoogleAuthConfigError(
        "OAuth 클라이언트 JSON 형식이 올바르지 않습니다. Google Cloud의 OAuth Client JSON을 사용하세요."
    )


def describe_available_auth_source() -> str:
    if _load_streamlit_secret("gcp_oauth_user"):
        return "Streamlit secrets: gcp_oauth_user"
    if os.getenv("GOOGLE_OAUTH_USER_JSON", "").strip():
        return "환경변수: GOOGLE_OAUTH_USER_JSON"
    return ""


def describe_available_oauth_client_source() -> str:
    if _load_streamlit_secret("gcp_oauth_client"):
        return "Streamlit secrets: gcp_oauth_client"
    if os.getenv("GOOGLE_OAUTH_CLIENT_JSON", "").strip():
        return "환경변수: GOOGLE_OAUTH_CLIENT_JSON"
    return ""


def _normalize_authorized_user_payload(payload: Dict) -> Dict:
    if payload.get("type") == "authorized_user" and isinstance(payload.get("data"), dict):
        return {"type": "authorized_user", "data": payload["data"]}
    if payload.get("type") == "authorized_user":
        return {"type": "authorized_user", "data": payload}
    return {"type": "authorized_user", "data": payload}


def _read_credentials_payload(credential_json_override: Optional[Union[str, Dict]] = None) -> Dict:
    """Prefer in-app override, then OAuth user JSON."""
    if isinstance(credential_json_override, dict):
        return _normalize_authorized_user_payload(credential_json_override)

    if (credential_json_override or "").strip():
        return _payload_from_json_string(credential_json_override.strip())

    oauth_info = _load_streamlit_secret("gcp_oauth_user")
    if oauth_info:
        return {"type": "authorized_user", "data": dict(oauth_info)}

    oauth_raw = os.getenv("GOOGLE_OAUTH_USER_JSON", "").strip()
    if oauth_raw:
        return _payload_from_json_string(oauth_raw)

    raise GoogleAuthConfigError(
        "OAuth 사용자 인증정보가 없습니다. 아래 중 하나를 설정하세요: "
        "(1) Streamlit secrets gcp_oauth_user, "
        "(2) 환경변수 GOOGLE_OAUTH_USER_JSON, "
        "(3) 앱 내 인증 JSON 직접 입력."
    )


def _read_oauth_client_payload(client_json_override: Optional[str] = None) -> Dict:
    if (client_json_override or "").strip():
        return _client_payload_from_json_string(client_json_override.strip())

    client_info = _load_streamlit_secret("gcp_oauth_client")
    if client_info:
        if "installed" in client_info or "web" in client_info:
            return _client_payload_from_json_string(json.dumps(client_info))
        return dict(client_info)

    raw = os.getenv("GOOGLE_OAUTH_CLIENT_JSON", "").strip()
    if raw:
        return _client_payload_from_json_string(raw)

    raise GoogleAuthConfigError(
        "OAuth 클라이언트 정보가 없습니다. 아래 중 하나를 설정하세요: "
        "(1) Streamlit secrets gcp_oauth_client, "
        "(2) 환경변수 GOOGLE_OAUTH_CLIENT_JSON, "
        "(3) 앱 내 OAuth Client JSON 직접 입력."
    )


def build_oauth_authorization_url(*, redirect_uri: str, state: str, client_json_override: str = "") -> str:
    from requests_oauthlib import OAuth2Session

    client = _read_oauth_client_payload(client_json_override or None)
    auth_uri = client.get("auth_uri")
    client_id = client.get("client_id")
    if not auth_uri or not client_id:
        raise GoogleAuthConfigError("OAuth 클라이언트 정보에 auth_uri/client_id가 필요합니다.")

    oauth = OAuth2Session(
        client_id=client_id,
        scope=SCOPES,
        redirect_uri=redirect_uri,
        state=state,
    )
    authorization_url, _ = oauth.authorization_url(
        auth_uri,
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return authorization_url


def exchange_oauth_code_for_user_credentials(
    *,
    code: str,
    redirect_uri: str,
    client_json_override: str = "",
) -> Dict:
    from requests_oauthlib import OAuth2Session

    client = _read_oauth_client_payload(client_json_override or None)
    token_uri = client.get("token_uri")
    client_id = client.get("client_id")
    client_secret = client.get("client_secret")
    if not token_uri or not client_id or not client_secret:
        raise GoogleAuthConfigError("OAuth 클라이언트 정보에 token_uri/client_id/client_secret이 필요합니다.")

    oauth = OAuth2Session(client_id=client_id, redirect_uri=redirect_uri, scope=SCOPES)

    try:
        token = oauth.fetch_token(
            token_url=token_uri,
            code=code.strip(),
            client_secret=client_secret,
            include_client_id=True,
        )
    except Exception as exc:
        raise GoogleAuthConfigError(f"OAuth 코드 교환 실패: {exc}") from exc

    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise GoogleAuthConfigError(
            "refresh_token을 받지 못했습니다. 권한 동의 화면에서 계정 재승인(prompt=consent) 후 다시 시도하세요."
        )

    user_creds = {
        "type": "authorized_user",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "token_uri": token_uri,
    }

    access_token = token.get("access_token")
    if access_token:
        user_creds["token"] = access_token
    expiry = token.get("expires_at")
    if expiry:
        from datetime import datetime, timezone

        user_creds["expiry"] = datetime.fromtimestamp(expiry, tz=timezone.utc).isoformat()

    return user_creds


def _build_google_services(credential_json_override: Optional[Union[str, Dict]] = None):
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    payload = _read_credentials_payload(credential_json_override)

    creds = Credentials.from_authorized_user_info(payload["data"], scopes=SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return docs_service, drive_service


def _friendly_http_error(exc: Exception) -> GoogleAuthConfigError:
    from googleapiclient.errors import HttpError

    if not isinstance(exc, HttpError):
        return GoogleAuthConfigError(str(exc))

    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 403:
        return GoogleAuthConfigError(
            "Google Docs API 권한이 없습니다(403). OAuth 사용자 인증 계정이 Docs/Drive 접근 가능한지 확인하세요."
        )

    if status == 401:
        return GoogleAuthConfigError("Google 인증이 만료되었거나 유효하지 않습니다(401). OAuth 인증정보를 다시 생성하세요.")

    return GoogleAuthConfigError(f"Google API 요청 실패({status}): {exc}")


def upload_report_as_google_doc(
    *,
    title: str,
    body_text: str,
    folder_id: str,
    credential_json_override: Optional[Union[str, Dict]] = "",
) -> str:
    docs_service, drive_service = _build_google_services(credential_json_override or None)

    try:
        doc = docs_service.documents().create(body={"title": title}).execute()
    except Exception as exc:
        raise _friendly_http_error(exc) from exc

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
        raise _friendly_http_error(exc) from exc

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
            raise _friendly_http_error(exc) from exc

    return f"https://docs.google.com/document/d/{doc_id}/edit"
