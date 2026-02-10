from io import BytesIO
from typing import Dict

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from lessonplan_bot import normalize_table_rows


def _safe_text(value: str, fallback: str = "") -> str:
    text = str(value or "").replace("\x00", " ").strip()
    return text or fallback


def _set_cell_text(cell, text: str, *, bold: bool = False, align_center: bool = False, size: int = 10) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(_safe_text(text))
    run.bold = bold
    run.font.size = Pt(size)
    if align_center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def render_week_docx(fields: Dict) -> bytes:
    document = Document()

    title = document.add_paragraph()
    title_run = title.add_run(_safe_text(fields.get("doc_title"), "주간 수업 계획서 및 보고서"))
    title_run.bold = True
    title_run.font.size = Pt(20)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Header blocks (2 columns) to mirror the PDF layout.
    info_table = document.add_table(rows=1, cols=2)
    info_table.style = "Table Grid"
    left = (
        f"교사: {_safe_text(fields.get('teacher_name'), '고영찬')}\n"
        f"수업: {_safe_text(fields.get('class_name') or fields.get('subject'))}"
    )
    right = (
        f"수업날짜: {_safe_text(fields.get('lesson_datetime') or fields.get('week_label'))}\n"
        f"대상: {_safe_text(fields.get('target_group') or fields.get('class_name'))}"
    )
    _set_cell_text(info_table.rows[0].cells[0], left)
    _set_cell_text(info_table.rows[0].cells[1], right)

    materials_table = document.add_table(rows=1, cols=2)
    materials_table.style = "Table Grid"
    _set_cell_text(materials_table.rows[0].cells[0], "수업 필요 물품 / 준비물:", bold=True)
    _set_cell_text(materials_table.rows[0].cells[1], fields.get("materials", ""))

    document.add_paragraph()

    section1 = document.add_paragraph()
    section1_run = section1.add_run("수업 주제 및 수업 목적")
    section1_run.bold = True
    section1.alignment = WD_ALIGN_PARAGRAPH.CENTER

    topic_table = document.add_table(rows=1, cols=1)
    topic_table.style = "Table Grid"
    topic_objective = (
        f"수업 주제: {_safe_text(fields.get('lesson_topic'))}\n"
        f"수업 목적: {_safe_text(fields.get('theme_objective'))}"
    )
    _set_cell_text(topic_table.rows[0].cells[0], topic_objective)

    document.add_paragraph()

    section2 = document.add_paragraph()
    section2_run = section2.add_run("수업계획서")
    section2_run.bold = True
    section2.alignment = WD_ALIGN_PARAGRAPH.CENTER

    plan_table = document.add_table(rows=1, cols=4)
    plan_table.style = "Table Grid"
    headers = ["단계", "시간", "내용", "비고"]
    for idx, header in enumerate(headers):
        _set_cell_text(plan_table.rows[0].cells[idx], header, bold=True, align_center=True, size=11)

    rows = normalize_table_rows(fields.get("lesson_rows")) or [
        {"phase": "도입", "time": "10분", "content": "복습 및 동기 유발", "remarks": ""},
        {"phase": "전개", "time": "30분", "content": "핵심 개념 및 활동", "remarks": ""},
        {"phase": "정리", "time": "10분", "content": "형성평가 및 과제", "remarks": ""},
    ]

    for row in rows:
        cells = plan_table.add_row().cells
        _set_cell_text(cells[0], row.get("phase", ""), bold=True, align_center=True)
        _set_cell_text(cells[1], row.get("time", ""), align_center=True)
        _set_cell_text(cells[2], row.get("content", ""))
        _set_cell_text(cells[3], row.get("remarks", ""))

    document.add_paragraph()

    section3 = document.add_paragraph()
    section3_run = section3.add_run("수업보고서")
    section3_run.bold = True
    section3.alignment = WD_ALIGN_PARAGRAPH.CENTER

    report_table = document.add_table(rows=3, cols=2)
    report_table.style = "Table Grid"

    teacher_note = _safe_text(fields.get("teacher_notes"), "특이사항 없음")
    edited_draft = _safe_text(fields.get("edited_draft"))
    if edited_draft:
        teacher_note = f"{teacher_note}\n\n[초안]\n{edited_draft}".strip()

    report_rows = [
        ("수업 평가:", _safe_text(fields.get("evaluation"), "특이사항 없음")),
        ("학생 특이 사항", _safe_text(fields.get("student_notes"), "특이사항 없음")),
        ("교사 메모", teacher_note),
    ]
    for idx, (label, value) in enumerate(report_rows):
        _set_cell_text(report_table.rows[idx].cells[0], label, bold=True)
        _set_cell_text(report_table.rows[idx].cells[1], value)

    output = BytesIO()
    document.save(output)
    return output.getvalue()
