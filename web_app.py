import json
import re
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import importlib
import streamlit as st

from google_drive_uploader import (
    GoogleAuthConfigError,
    build_oauth_authorization_url,
    describe_available_auth_source,
    describe_available_oauth_client_source,
    exchange_oauth_code_for_user_credentials,
    upload_report_as_google_doc,
)
from lessonplan_bot import (
    generate_lesson_table_rows_text,
    infer_class_dates_from_week,
    normalize_table_rows,
    parse_syllabus_pdf,
    parse_table_rows_text,
    suggest_topic_objective_from_syllabus,
)
import lessonplan_bot as lb
from pdf_template import has_cjk_font, render_week_pdf
from docx_template import render_week_docx



def _load_lessonplan_bot_module():
    try:
        return importlib.import_module("lessonplan_bot")
    except Exception as exc:
        st.error(f"lessonplan_bot 로딩 실패: {exc}")
        st.code(traceback.format_exc())
        return None

DATA_DIR = Path("data")
SYLLABI_DIR = DATA_DIR / "syllabi"
INDEX_PATH = DATA_DIR / "syllabi_index.json"


def ensure_storage() -> None:
    SYLLABI_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.exists():
        INDEX_PATH.write_text("[]", encoding="utf-8")


def load_index() -> List[Dict]:
    ensure_storage()
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_index(items: List[Dict]) -> None:
    INDEX_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add_syllabus(uploaded_pdf) -> None:
    item_id = str(uuid.uuid4())
    safe_pdf_name = uploaded_pdf.name.replace("/", "_").replace("\\", "_")
    pdf_path = SYLLABI_DIR / f"{item_id}_{safe_pdf_name}"
    pdf_path.write_bytes(uploaded_pdf.getbuffer())

    syllabus_parsed = parse_syllabus_pdf(pdf_path)

    index = load_index()
    index.append(
        {
            "id": item_id,
            "name": uploaded_pdf.name,
            "path": str(pdf_path),
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "weeks": syllabus_parsed.get("weeks", []),
            "outline_map": syllabus_parsed.get("outline_map", {}),
        }
    )
    save_index(index)


def delete_syllabus(item_id: str) -> None:
    updated = []
    for item in load_index():
        if item.get("id") == item_id:
            Path(item.get("path", "")).unlink(missing_ok=True)
            continue
        updated.append(item)
    save_index(updated)


def compose_report_text(fields: Dict, draft_text: str) -> str:
    student_notes = fields.get("student_notes") or "특이사항 없음"
    return (
        f"{fields.get('doc_title', '주간 수업 계획서 및 보고서')}\n\n"
        f"교사: {fields.get('teacher_name', '')}\n"
        f"수업: {fields.get('class_name', '')}\n"
        f"수업날짜: {fields.get('lesson_datetime', '')}\n"
        f"대상: {fields.get('target_group', '')}\n"
        f"수업 필요물품/준비물: {fields.get('materials', '')}\n\n"
        f"[수업 주제 및 수업 목적]\n"
        f"수업 주제: {fields.get('lesson_topic', '')}\n"
        f"수업 목적: {fields.get('theme_objective', '')}\n\n"
        f"[수업계획서]\n단계|시간|내용|비고\n{draft_text}\n\n"
        f"[수업보고서]\n"
        f"수업평가: {fields.get('evaluation', '특이사항 없음')}\n"
        f"학생특이사항: {student_notes}\n"
        f"교사메모: {fields.get('teacher_notes', '특이사항 없음')}\n"
    )

def _infer_subject_name(filename: str, week_info: Dict) -> str:
    stem = Path(filename or "").stem
    cleaned = re.sub(r"[_\-]+", " ", stem)
    cleaned = re.sub(r"\b(20\d{2}|\d{1,2}주|syllabus|plan|weekly|week)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    detail = str(week_info.get("details", ""))
    subject_hint = re.search(r"(Life\s*Science|Science|Math|English|Social\s*Studies|국어|수학|과학|영어)", f"{cleaned} {detail}", re.IGNORECASE)
    if subject_hint:
        token = subject_hint.group(1)
        return token if re.search(r"[A-Za-z]", token) else token.strip()
    return cleaned or "Life Science"


def _infer_target_grade(week_info: Dict) -> str:
    search_space = " ".join([str(week_info.get("raw_text", "")), str(week_info.get("details", "")), " ".join(week_info.get("events", []))])
    m = re.search(r"\bG\s*\d{1,2}\b", search_space, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", "", m.group(0).upper())

    ev = week_info.get("events", [])
    if ev:
        m2 = re.search(r"\d+", str(ev[0]))
        if m2:
            return f"G{m2.group(0)}"
    return "G6"


def _label(item: Dict) -> str:
    return f"{item.get('name')} ({item.get('uploaded_at')})"


def _get_selected(index: List[Dict], label: str) -> Optional[Dict]:
    for item in index:
        if _label(item) == label:
            return item
    return None


def main() -> None:
    lb = _load_lessonplan_bot_module()
    if lb is None:
        return

    st.set_page_config(page_title="주간 수업 계획서 및 보고서 생성기", layout="wide")
    st.title("주간 수업 계획서 및 보고서 생성기")

    if not has_cjk_font():
        st.warning("한글 폰트를 찾지 못했습니다. Streamlit Cloud에서는 packages.txt(fonts-nanum) 설치를 확인하세요.")

    ensure_storage()
    index = load_index()

    # session defaults
    defaults = {
        "teacher_name": "고영찬",
        "doc_title": "주간 수업 계획서 및 보고서",
        "materials": "교재, 활동지, 필기구",
        "theme_objective": "",
        "lesson_rows_input": "",
        "applied_draft_text": "",
        "evaluation": "특이사항 없음",
        "student_notes": "특이사항 없음",
        "teacher_notes": "특이사항 없음",
        "last_week_key": "",
        "oauth_state": "",
        "google_oauth_authorization_url": "",
        "gcp_oauth_user_payload": None,
        "app_base_url": "",
        "oauth_client_json_override": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    st.subheader("1) Syllabus Library")
    with st.form("upload_form", clear_on_submit=True):
        up_pdf = st.file_uploader("강의계획서 PDF 업로드", type=["pdf"])
        upload_btn = st.form_submit_button("Syllabus 저장")

    if upload_btn:
        if up_pdf is None:
            st.warning("PDF를 먼저 업로드하세요.")
        else:
            try:
                add_syllabus(up_pdf)
                st.success("저장 완료")
                st.rerun()
            except Exception as exc:
                st.error(f"저장 실패: {exc}")
                st.code(traceback.format_exc())

    index = load_index()
    if not index:
        st.info("저장된 강의계획서가 없습니다.")
        return

    selected_label = st.selectbox("저장된 강의계획서 선택", [_label(i) for i in index])
    selected = _get_selected(index, selected_label)
    if not selected:
        st.warning("선택 항목을 찾지 못했습니다.")
        return

    if not selected.get("outline_map"):
        try:
            reparsed = parse_syllabus_pdf(Path(selected.get("path", "")))
            selected["outline_map"] = reparsed.get("outline_map", {})
            selected["weeks"] = reparsed.get("weeks", selected.get("weeks", []))
            items = load_index()
            for item in items:
                if item.get("id") == selected.get("id"):
                    item["outline_map"] = selected.get("outline_map", {})
                    item["weeks"] = selected.get("weeks", [])
                    break
            save_index(items)
        except Exception:
            selected["outline_map"] = {}

    if st.button("선택한 강의계획서 삭제", type="secondary"):
        delete_syllabus(selected.get("id", ""))
        st.success("삭제 완료")
        st.rerun()

    st.subheader("2) 초안생성")
    weeks = selected.get("weeks", [])
    week_options = [f"{w['week_no']}주 ({w['date_range']})" for w in weeks] or ["1주 (N/A)"]
    week_pick = st.selectbox("주차 선택", week_options)
    week_info = weeks[week_options.index(week_pick)] if weeks else {"week_no": 1, "date_range": "N/A", "events": [], "details": ""}

    # infer defaults
    class_candidates = week_info.get("events") or ["G6"]
    class_for_mapping = class_candidates[0]
    auto_subject = _infer_subject_name(selected.get("name", ""), week_info)
    auto_datetime = infer_class_dates_from_week(week_info)
    auto_target = _infer_target_grade(week_info)
    inferred = suggest_topic_objective_from_syllabus(
        week_info=week_info,
        subject=auto_subject,
        outline_map=selected.get("outline_map", {}),
    )

    week_key = f"{selected.get('id')}::{week_info.get('week_no')}::{class_for_mapping}"
    if st.session_state["last_week_key"] != week_key:
        st.session_state["lesson_name"] = auto_subject
        st.session_state["lesson_datetime"] = auto_datetime
        st.session_state["target_group"] = auto_target
        st.session_state["lesson_topic"] = inferred.get("lesson_topic", "")
        st.session_state["theme_objective"] = inferred.get("theme_objective", "")
        st.session_state["lesson_rows_input"] = ""
        st.session_state["applied_draft_text"] = ""
        st.session_state["last_week_key"] = week_key

    # REQUIRED INPUT ORDER
    doc_title = st.text_input("(1) 문서제목", key="doc_title")
    teacher_name = st.text_input("(2) 교사", key="teacher_name")
    lesson_name = st.text_input("(3) 수업", key="lesson_name")
    lesson_datetime = st.text_input("(4) 수업날짜", key="lesson_datetime")
    target_group = st.text_input("(5) 대상", key="target_group")
    materials = st.text_input("(6) 수업 필요물품/준비물", key="materials")
    lesson_topic = st.text_input("(7) 수업주제", key="lesson_topic")
    theme_objective = st.text_area("(8) 수업목적", key="theme_objective", height=80)
    plan_note = st.text_area("(9) 수업계획서 메모(도입/전개/정리)", value="학생 참여형 활동 강화", height=90)

    if st.button("(10) 초안생성", type="primary"):
        try:
            st.session_state["lesson_rows_input"] = lb.generate_lesson_table_rows_text(
                week_info=week_info,
                class_plan_note=plan_note,
                include_prayer=True,
            )
            st.session_state["applied_draft_text"] = st.session_state["lesson_rows_input"]
        except Exception as exc:
            st.error(f"초안생성 실패: {exc}")
            st.code(traceback.format_exc())

    draft_text = st.text_area(
        "(11) 생성된 초안(수업계획서 표 행만, 편집 가능)\n형식: 단계|시간|내용|비고",
        key="lesson_rows_input",
        height=230,
    )


    col_apply, col_hint = st.columns([1, 3])
    with col_apply:
        if st.button("(11-1) 수정 내용 반영"):
            st.session_state["applied_draft_text"] = st.session_state.get("lesson_rows_input", "")
            st.success("편집 내용이 결과물에 반영되었습니다.")
    with col_hint:
        st.caption("초안을 수정한 뒤 '(11-1) 수정 내용 반영'을 누르면 TXT/PDF/Google Docs 출력에 동일하게 반영됩니다.")

    evaluation = st.text_area("(12) 수업평가", key="evaluation", height=70)
    student_notes = st.text_area("(13) 학생특이사항", key="student_notes", height=70)
    teacher_notes = st.text_area("(14) 교사메모", key="teacher_notes", height=70)

    export_draft_text = st.session_state.get("applied_draft_text") or draft_text

    fields = {
        "doc_title": doc_title,
        "teacher_name": teacher_name,
        "class_name": lesson_name,
        "lesson_datetime": lesson_datetime,
        "target_group": target_group,
        "materials": materials,
        "lesson_topic": lesson_topic,
        "theme_objective": theme_objective,
        "evaluation": evaluation.strip() or "특이사항 없음",
        "student_notes": (student_notes or "").strip() or "특이사항 없음",
        "teacher_notes": teacher_notes.strip() or "특이사항 없음",
        "lesson_rows": normalize_table_rows(parse_table_rows_text(draft_text)),
    }

    full_txt = compose_report_text(fields, draft_text)
    st.download_button(
        "Download TXT",
        data=full_txt.encode("utf-8"),
        file_name=f"week_{week_info.get('week_no', 1)}_report.txt",
        mime="text/plain",
    )

    try:
        pdf_bytes = render_week_pdf(fields)
        st.download_button(
            "Download PDF",
            data=pdf_bytes,
            file_name=f"week_{week_info.get('week_no', 1)}_report.pdf",
            mime="application/pdf",
        )
    except Exception as exc:
        st.error(f"PDF 생성 실패: {exc}")
        st.code(traceback.format_exc())

    try:
        docx_bytes = render_week_docx(fields)
        st.download_button(
            "Download Word (.docx)",
            data=docx_bytes,
            file_name=f"week_{week_info.get('week_no', 1)}_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    except Exception as exc:
        st.error(f"Word 문서 생성 실패: {exc}")
        st.code(traceback.format_exc())

    st.subheader("3) Google Docs 업로드 (OAuth)")
    auth_source = describe_available_auth_source()
    client_source = describe_available_oauth_client_source()
    if auth_source:
        st.caption(f"감지된 OAuth 사용자 인증 소스: {auth_source}")
    else:
        st.warning("OAuth 사용자 인증정보가 없습니다. 아래 OAuth 단계로 생성하거나 JSON을 입력하세요.")

    if client_source:
        st.caption(f"감지된 OAuth 클라이언트 소스: {client_source}")

    st.markdown("#### OAuth 연결")
    secret_base_url = ""
    try:
        secret_base_url = str(st.secrets.get("app_base_url", "")).strip()
    except Exception:
        secret_base_url = ""

    if secret_base_url:
        app_base_url = secret_base_url
        st.caption(f"app_base_url (secrets): {app_base_url}")
    else:
        app_base_url = st.text_input(
            "App Base URL",
            value=st.session_state.get("app_base_url", ""),
            help="예: https://YOUR_APP.streamlit.app",
        ).strip()
        st.session_state["app_base_url"] = app_base_url

    redirect_uri = f"{app_base_url.rstrip('/')}/oauth/callback" if app_base_url else ""
    st.caption(f"OAuth Redirect URI: {redirect_uri or '(App Base URL 필요)'}")

    oauth_client_override = st.text_area(
        "OAuth Client JSON",
        value=st.session_state.get("oauth_client_json_override", ""),
        height=160,
        help=(
            "Google Cloud Console > APIs & Services > Credentials에서 다운로드한 "
            "OAuth 클라이언트 JSON(web 또는 installed)을 붙여넣으세요."
        ),
    )
    st.session_state["oauth_client_json_override"] = oauth_client_override

    query_code = st.query_params.get("code")
    query_state = st.query_params.get("state")
    if query_code and query_state:
        try:
            saved_state = st.session_state.get("oauth_state", "")
            if not saved_state or query_state != saved_state:
                st.error("OAuth state 검증 실패: 요청 위조 가능성으로 코드 교환을 중단했습니다.")
            elif not redirect_uri:
                st.error("OAuth 코드 교환 실패: App Base URL을 먼저 설정하세요.")
            else:
                creds = exchange_oauth_code_for_user_credentials(
                    code=str(query_code),
                    redirect_uri=redirect_uri,
                    client_json_override=oauth_client_override,
                )
                st.session_state["gcp_oauth_user_payload"] = {"type": "authorized_user", "data": creds}
                st.success("OAuth 연결 성공: 업로드에 사용할 사용자 인증정보가 저장되었습니다.")

                try:
                    st.query_params.clear()
                except Exception:
                    st.experimental_set_query_params()
        except GoogleAuthConfigError as exc:
            st.error(f"OAuth 코드 교환 실패: {exc}")
        except Exception as exc:
            st.error(f"OAuth 처리 중 오류: {exc}")
            st.code(traceback.format_exc())

    if st.button("Google 로그인 시작"):
        try:
            if not redirect_uri:
                st.error("App Base URL을 먼저 입력하세요.")
            else:
                state = str(uuid.uuid4())
                auth_url = build_oauth_authorization_url(
                    redirect_uri=redirect_uri,
                    state=state,
                    client_json_override=oauth_client_override,
                )
                st.session_state["oauth_state"] = state
                st.session_state["google_oauth_authorization_url"] = auth_url
                st.success("Google 로그인 링크가 생성되었습니다.")
        except GoogleAuthConfigError as exc:
            st.error(f"OAuth 설정 오류: {exc}")
        except Exception as exc:
            st.error(f"OAuth URL 생성 실패: {exc}")
            st.code(traceback.format_exc())

    auth_url = st.session_state.get("google_oauth_authorization_url", "")
    if auth_url:
        st.link_button("Google 로그인", auth_url)

    if st.session_state.get("gcp_oauth_user_payload"):
        st.caption("OAuth 사용자 인증이 현재 세션에 저장되었습니다.")

    folder_id = st.text_input("공유 Google Drive folder ID")
    doc_name = st.text_input("Google Doc 제목", value=f"{doc_title} - {week_pick}")
    oauth_user_payload = st.session_state.get("gcp_oauth_user_payload")
    session_credential_override = ""
    if oauth_user_payload and isinstance(oauth_user_payload, dict) and isinstance(oauth_user_payload.get("data"), dict):
        session_credential_override = json.dumps(oauth_user_payload["data"], ensure_ascii=False)

    credential_override = st.text_area(
        "OAuth 사용자 인증 JSON 직접 입력(선택)",
        value=session_credential_override,
        height=160,
        help="authorized_user JSON 또는 {\"type\":\"authorized_user\",\"data\":{...}} 형식을 사용할 수 있습니다.",
    )

    if st.button("Upload as Google Doc"):
        try:
            full_text = compose_report_text(fields, export_draft_text)
            url = upload_report_as_google_doc(
                title=doc_name,
                body_text=full_text,
                folder_id=folder_id,
                credential_json_override=credential_override,
            )
            st.success("Google Doc 업로드 완료")
            st.markdown(f"[문서 열기]({url})")
        except GoogleAuthConfigError as exc:
            st.error(f"Google OAuth 설정 오류: {exc}")
        except Exception as exc:
            st.error(f"Google Docs 업로드 실패: {exc}")
            st.code(traceback.format_exc())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        st.error(f"치명적 오류: {exc}")
        st.code(traceback.format_exc())
