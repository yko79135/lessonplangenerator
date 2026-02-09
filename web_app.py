import json
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

from lessonplan_bot import (
    generate_lesson_table_rows_text,
    infer_lesson_datetime,
    parse_curriculum_sheet,
    parse_syllabus_pdf,
    suggest_topic_objective,
)
from google_drive_uploader import upload_report_as_google_doc
from pdf_template import has_cjk_font, render_week_pdf

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


def save_index(index: List[Dict]) -> None:
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def add_syllabus(uploaded_file, curriculum_file=None) -> None:
    file_id = str(uuid.uuid4())
    safe_name = uploaded_file.name.replace("/", "_").replace("\\", "_")
    save_path = SYLLABI_DIR / f"{file_id}_{safe_name}"
    save_path.write_bytes(uploaded_file.getbuffer())

    weeks = parse_syllabus_pdf(save_path)

    curriculum_rows = []
    curriculum_path = ""
    if curriculum_file is not None:
        cur_name = curriculum_file.name.replace("/", "_").replace("\\", "_")
        curriculum_path_obj = SYLLABI_DIR / f"{file_id}_curriculum_{cur_name}"
        curriculum_path_obj.write_bytes(curriculum_file.getbuffer())
        curriculum_rows = parse_curriculum_sheet(curriculum_path_obj)
        curriculum_path = str(curriculum_path_obj)
    index = load_index()
    index.append(
        {
            "id": file_id,
            "name": uploaded_file.name,
            "path": str(save_path),
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "weeks": weeks,
            "curriculum_rows": curriculum_rows,
            "curriculum_path": curriculum_path,
        }
    )
    save_index(index)


def delete_syllabus(item_id: str) -> None:
    index = load_index()
    kept = []
    for item in index:
        if item.get("id") == item_id:
            try:
                Path(item.get("path", "")).unlink(missing_ok=True)
                if item.get("curriculum_path"):
                    Path(item.get("curriculum_path", "")).unlink(missing_ok=True)
            except Exception:
                pass
        else:
            kept.append(item)
    save_index(kept)


def selected_item_by_label(index: List[Dict], label: str) -> Optional[Dict]:
    for item in index:
        if f"{item['name']} ({item['uploaded_at']})" == label:
            return item
    return None


def compose_final_report_text(
    *,
    doc_title: str,
    teacher_name: str,
    subject: str,
    lesson_datetime: str,
    target_group: str,
    materials: str,
    lesson_topic: str,
    theme_objective: str,
    lesson_rows_text: str,
    evaluation: str,
    student_notes: str,
    teacher_notes: str,
) -> str:
    return (
        f"{doc_title}\n\n"
        f"교사: {teacher_name}\n"
        f"수업: {subject}\n"
        f"수업날짜: {lesson_datetime}\n"
        f"대상: {target_group}\n"
        f"수업 필요 물품 / 준비물: {materials}\n\n"
        f"[수업 주제 및 수업 목적]\n"
        f"수업 주제: {lesson_topic}\n"
        f"수업 목적: {theme_objective}\n\n"
        f"[수업계획서]\n"
        f"(단계|시간|내용|비고)\n"
        f"{lesson_rows_text}\n\n"
        f"[수업보고서]\n"
        f"수업 평가: {evaluation}\n"
        f"학생 특이 사항: {student_notes}\n"
        f"교사 메모: {teacher_notes}\n"
    )


def main() -> None:
    st.set_page_config(page_title="Syllabus to Weekly Lesson Plan", layout="wide")
    st.title("Syllabus Library 기반 주간 수업안/보고서 생성기")

    if not has_cjk_font():
        st.warning("한글 폰트를 찾지 못해 PDF에서 한글이 깨질 수 있습니다. Streamlit Cloud에서는 packages.txt의 fonts-nanum 설치를 확인하세요.")

    ensure_storage()
    index = load_index()

    if "draft_text" not in st.session_state:
        st.session_state["draft_text"] = ""
    if "theme_objective" not in st.session_state:
        st.session_state["theme_objective"] = ""
    if "evaluation" not in st.session_state:
        st.session_state["evaluation"] = "특이사항 없음"
    if "student_notes" not in st.session_state:
        st.session_state["student_notes"] = "특이사항 없음"
    if "teacher_notes" not in st.session_state:
        st.session_state["teacher_notes"] = "특이사항 없음"
    if "lesson_rows_input" not in st.session_state:
        st.session_state["lesson_rows_input"] = (
            "도입|10분|출석 확인, 지난 시간 복습|집중 유도\n"
            "전개|30분|핵심 내용 설명 및 활동|질의응답\n"
            "정리|10분|형성평가, 과제 안내|다음 시간 예고"
        )
    if "last_auto_week_key" not in st.session_state:
        st.session_state["last_auto_week_key"] = ""
    if "auto_lesson_topic" not in st.session_state:
        st.session_state["auto_lesson_topic"] = ""
    if "auto_lesson_datetime" not in st.session_state:
        st.session_state["auto_lesson_datetime"] = ""
    if "auto_target_group" not in st.session_state:
        st.session_state["auto_target_group"] = ""

    st.subheader("1) Syllabus Library")
    up = st.file_uploader("강의계획서 PDF 업로드", type=["pdf"])
    curriculum_up = st.file_uploader(
        "세부 진도표 업로드 (선택: .xlsx/.xls/.csv)",
        type=["xlsx", "xls", "csv"],
        help="주차/반/주제/목적 정보를 올리면 자동 기본값이 더 정확해집니다.",
    )
    if up is not None:
        try:
            add_syllabus(up, curriculum_up)
            st.success("업로드 및 파싱 완료. 아래 목록에서 선택하세요.")
            st.rerun()
        except Exception as exc:
            st.error(f"업로드 실패: {exc}")
            st.code(traceback.format_exc())

    if not index:
        st.info("저장된 강의계획서가 없습니다. 먼저 PDF를 업로드하세요.")
        return

    labels = [f"{item['name']} ({item['uploaded_at']})" for item in index]
    selected_label = st.selectbox("저장된 강의계획서 선택", labels)
    selected = selected_item_by_label(index, selected_label)
    if not selected:
        st.warning("선택한 강의계획서를 찾을 수 없습니다.")
        return

    c1, c2 = st.columns([4, 1])
    with c2:
        if st.button("선택 항목 삭제", type="secondary"):
            delete_syllabus(selected["id"])
            st.success("삭제되었습니다.")
            st.rerun()

    st.subheader("2) 주차 선택 및 초안 생성")
    weeks = selected.get("weeks", [])
    week_options = [f"Week {w['week_no']} ({w['date_range']})" for w in weeks] or ["Week 1 (N/A)"]
    chosen_week = st.selectbox("Week", week_options)
    week_info = weeks[week_options.index(chosen_week)] if weeks else {"week_no": 1, "date_range": "N/A", "events": [], "details": ""}

    subject_default = selected.get("name", "").split(".")[0] if selected.get("name") else "영어"
    subject = st.text_input("Subject", value=subject_default or "영어")
    class_plan_note = st.text_area("Brief class plan note", value="학생 참여형 활동을 강화")

    curriculum_rows = selected.get("curriculum_rows", [])
    auto_class_default = (week_info.get("events") or ["G6"])[0]

    col_a, col_b = st.columns(2)
    with col_a:
        teacher_name = st.text_input("Teacher name", value="고영찬")
        class_name = st.text_input("Class name", value=auto_class_default)
        schedule = st.text_input("Schedule", value=f"{week_info.get('date_range', 'N/A')} / 40분")
    with col_b:
        include_prayer = st.checkbox("Include prayer", value=True)

    auto = suggest_topic_objective(
        week_info=week_info,
        class_name=class_name,
        subject=subject,
        curriculum_rows=curriculum_rows,
    )
    inferred_datetime = infer_lesson_datetime(week_info)
    inferred_target = class_name or auto_class_default

    current_week_key = f"{selected.get('id')}::{week_info.get('week_no')}::{class_name}::{subject}"
    if st.session_state.get("last_auto_week_key") != current_week_key:
        st.session_state["auto_lesson_topic"] = auto.get("lesson_topic", subject)
        st.session_state["auto_lesson_datetime"] = inferred_datetime
        st.session_state["auto_target_group"] = inferred_target
        st.session_state["theme_objective"] = auto.get("theme_objective", f"{subject} 핵심 개념 이해 및 적용")
        st.session_state["last_auto_week_key"] = current_week_key

    st.markdown("### 상단 헤더")
    doc_title = st.text_input("문서 제목", value="주간 수업 계획서 및 보고서")
    lesson_topic = st.text_input("Lesson topic", key="auto_lesson_topic")
    lesson_datetime = st.text_input("Lesson date/time", key="auto_lesson_datetime")
    target_group = st.text_input("Target group", key="auto_target_group")
    materials = st.text_input("수업 필요 물품 / 준비물", value="교재, 활동지, PPT")

    st.markdown("### 수업 주제 및 수업 목적")
    theme_objective = st.text_area("Theme/Objectives", key="theme_objective")

    if st.button("3) 초안 생성", type="primary"):
        try:
            st.session_state["lesson_rows_input"] = generate_lesson_table_rows_text(
                week_info=week_info,
                class_plan_note=class_plan_note,
                include_prayer=include_prayer,
            )
        except Exception as exc:
            st.error(f"초안 생성 실패: {exc}")
            st.code(traceback.format_exc())

    st.markdown("### 수업보고서")
    evaluation = st.text_area("Evaluation", key="evaluation")
    student_notes = st.text_area("Student notes", key="student_notes")
    teacher_notes = st.text_area("Teacher notes", key="teacher_notes")
    evaluation_final = evaluation.strip() or "특이사항 없음"
    student_notes_final = student_notes.strip() or "특이사항 없음"
    teacher_notes_final = teacher_notes.strip() or "특이사항 없음"

    st.markdown("#### 수업계획서 표 (자동 초안, 편집 가능)")
    draft_text = st.text_area(
        "수업계획서 표 원문 (TXT 다운로드용)",
        key="lesson_rows_input",
        height=220,
        help="초안 생성 시 수업계획서 표(도입/전개/마무리) 내용만 자동 작성됩니다.",
    )

    lesson_rows = []
    for line in draft_text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        while len(parts) < 4:
            parts.append("")
        lesson_rows.append({"phase": parts[0], "time": parts[1], "content": parts[2], "remarks": parts[3]})

    txt_name = f"lesson_week_{week_info.get('week_no', 1)}.txt"
    st.download_button("Download TXT", data=draft_text.encode("utf-8"), file_name=txt_name, mime="text/plain")

    try:
        pdf_bytes = render_week_pdf(
            {
                "doc_title": doc_title,
                "teacher_name": teacher_name,
                "subject": subject,
                "week_label": chosen_week,
                "class_name": class_name,
                "schedule": schedule,
                "materials": materials,
                "lesson_topic": lesson_topic,
                "lesson_datetime": lesson_datetime,
                "target_group": target_group,
                "theme_objective": theme_objective,
                "evaluation": evaluation_final,
                "student_notes": student_notes_final,
                "teacher_notes": teacher_notes_final,
                "lesson_rows": lesson_rows,
                "edited_draft": "",
            }
        )
        st.download_button(
            "Download PDF (template)",
            data=pdf_bytes,
            file_name=f"lesson_week_{week_info.get('week_no', 1)}.pdf",
            mime="application/pdf",
        )
    except Exception as exc:
        st.error(f"PDF 생성 실패: {exc}")
        st.code(traceback.format_exc())

    st.subheader("5) Google Docs 업로드 (Shared Drive/Folder)")
    st.caption(
        "공유 폴더 ID를 입력하고 업로드 버튼을 누르면 편집 가능한 Google Docs로 저장합니다. "
        "서비스 계정 이메일을 해당 공유 폴더에 편집자로 추가해야 합니다."
    )
    gdoc_folder_id = st.text_input("Google Drive folder ID", value="")
    gdoc_title = st.text_input(
        "Google Doc title",
        value=f"주간 수업 계획서 및 보고서 - {chosen_week}",
    )
    if st.button("Upload as Google Doc"):
        try:
            if not draft_text.strip():
                st.warning("업로드할 초안 텍스트가 없습니다. 먼저 초안을 생성/편집하세요.")
            else:
                report_text = compose_final_report_text(
                    doc_title=doc_title,
                    teacher_name=teacher_name,
                    subject=subject,
                    lesson_datetime=lesson_datetime,
                    target_group=target_group,
                    materials=materials,
                    lesson_topic=lesson_topic,
                    theme_objective=theme_objective,
                    lesson_rows_text=draft_text,
                    evaluation=evaluation_final,
                    student_notes=student_notes_final,
                    teacher_notes=teacher_notes_final,
                )
                url = upload_report_as_google_doc(
                    title=gdoc_title,
                    body_text=report_text,
                    folder_id=gdoc_folder_id,
                )
                st.success("Google Doc 업로드 완료")
                st.markdown(f"[문서 열기]({url})")
        except Exception as exc:
            st.error(f"Google Doc 업로드 실패: {exc}")
            st.code(traceback.format_exc())

    st.caption("※ Google Docs 업로드는 서비스 계정 또는 환경설정이 필요합니다.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        st.error(f"치명적 오류: {exc}")
        st.code(traceback.format_exc())
