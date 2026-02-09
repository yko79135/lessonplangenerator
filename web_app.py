import json
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

from lessonplan_bot import generate_weekly_draft, parse_syllabus_pdf
from pdf_template import render_week_pdf

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


def add_syllabus(uploaded_file) -> None:
    file_id = str(uuid.uuid4())
    safe_name = uploaded_file.name.replace("/", "_").replace("\\", "_")
    save_path = SYLLABI_DIR / f"{file_id}_{safe_name}"
    save_path.write_bytes(uploaded_file.getbuffer())

    weeks = parse_syllabus_pdf(save_path)
    index = load_index()
    index.append(
        {
            "id": file_id,
            "name": uploaded_file.name,
            "path": str(save_path),
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "weeks": weeks,
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


def main() -> None:
    st.set_page_config(page_title="Syllabus to Weekly Lesson Plan", layout="wide")
    st.title("Syllabus Library 기반 주간 수업안/보고서 생성기")

    ensure_storage()
    index = load_index()

    st.subheader("1) Syllabus Library")
    up = st.file_uploader("강의계획서 PDF 업로드", type=["pdf"])
    if up is not None:
        try:
            add_syllabus(up)
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

    st.subheader("2) 입력 정보")
    weeks = selected.get("weeks", [])
    week_options = [f"Week {w['week_no']} ({w['date_range']})" for w in weeks] or ["Week 1 (N/A)"]
    chosen_week = st.selectbox("Week", week_options)
    week_info = weeks[week_options.index(chosen_week)] if weeks else {"week_no": 1, "date_range": "N/A", "events": [], "details": ""}

    subject = st.text_input("Subject", value="영어")
    class_plan_note = st.text_area("Brief class plan note", value="학생 참여형 활동을 강화")

    col_a, col_b = st.columns(2)
    with col_a:
        teacher_name = st.text_input("Teacher name", value="고영찬")
        class_name = st.text_input("Class name", value="11A")
        schedule = st.text_input("Schedule", value=f"{week_info.get('date_range', 'N/A')} / 50분")
    with col_b:
        materials = st.text_input("Materials", value="교재, 활동지, PPT")
        include_prayer = st.checkbox("Include prayer", value=True)

    if st.button("3) 초안 생성", type="primary"):
        try:
            st.session_state["draft_text"] = generate_weekly_draft(
                subject=subject,
                week_info=week_info,
                class_plan_note=class_plan_note,
                teacher_name=teacher_name,
                class_name=class_name,
                schedule=schedule,
                materials=materials,
                include_prayer=include_prayer,
            )
        except Exception as exc:
            st.error(f"초안 생성 실패: {exc}")
            st.code(traceback.format_exc())

    draft_text = st.text_area(
        "4) Draft text (편집 가능)",
        value=st.session_state.get("draft_text", ""),
        height=320,
    )
    st.session_state["draft_text"] = draft_text

    st.subheader("PDF Template Fields")
    theme_objective = st.text_area("Theme/Objectives", value=f"{subject} 핵심 개념 이해 및 적용")
    evaluation = st.text_area("Evaluation", value="학습 목표 달성 여부와 참여도를 확인")
    student_notes = st.text_area("Student notes", value="특이사항 없음")
    teacher_notes = st.text_area("Teacher notes", value=class_plan_note)

    default_rows = """도입|10분|출석 확인, 지난 시간 복습|집중 유도
전개|30분|핵심 내용 설명 및 활동|질의응답
정리|10분|형성평가, 과제 안내|다음 시간 예고"""
    row_input = st.text_area("Lesson plan rows (단계|시간|내용|비고 per line)", value=default_rows, height=120)

    lesson_rows = []
    for line in row_input.splitlines():
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
                "doc_title": "주간 수업안 및 보고서",
                "teacher_name": teacher_name,
                "subject": subject,
                "week_label": chosen_week,
                "class_name": class_name,
                "schedule": schedule,
                "materials": materials,
                "theme_objective": theme_objective,
                "evaluation": evaluation,
                "student_notes": student_notes,
                "teacher_notes": teacher_notes,
                "lesson_rows": lesson_rows,
                "edited_draft": draft_text,
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

    st.caption("※ Future upload integrations (e.g., Drive) can be added later.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        st.error(f"치명적 오류: {exc}")
        st.code(traceback.format_exc())
