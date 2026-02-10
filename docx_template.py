from io import BytesIO
from typing import Dict, List

from docx import Document


def _add_field_line(document: Document, label: str, value: str) -> None:
    document.add_paragraph(f"{label}: {value}")


def render_week_docx(fields: Dict) -> bytes:
    document = Document()
    document.add_heading(fields.get("doc_title", "주간 수업 계획서 및 보고서"), level=1)

    _add_field_line(document, "교사", fields.get("teacher_name", ""))
    _add_field_line(document, "수업", fields.get("class_name", ""))
    _add_field_line(document, "수업날짜", fields.get("lesson_datetime", ""))
    _add_field_line(document, "대상", fields.get("target_group", ""))
    _add_field_line(document, "수업 필요물품/준비물", fields.get("materials", ""))

    document.add_heading("수업 주제 및 수업 목적", level=2)
    _add_field_line(document, "수업 주제", fields.get("lesson_topic", ""))
    _add_field_line(document, "수업 목적", fields.get("theme_objective", ""))

    document.add_heading("수업계획서", level=2)
    lesson_rows: List[Dict] = fields.get("lesson_rows", [])
    plan_table = document.add_table(rows=1, cols=4)
    plan_table.style = "Table Grid"
    headers = ["단계", "시간", "내용", "비고"]
    for i, header in enumerate(headers):
        plan_table.rows[0].cells[i].text = header

    for row in lesson_rows:
        cells = plan_table.add_row().cells
        cells[0].text = str(row.get("phase", ""))
        cells[1].text = str(row.get("minutes", ""))
        cells[2].text = str(row.get("content", ""))
        cells[3].text = str(row.get("note", ""))

    document.add_heading("수업보고서", level=2)
    _add_field_line(document, "수업평가", fields.get("evaluation", "특이사항 없음"))
    _add_field_line(document, "학생특이사항", fields.get("student_notes", "특이사항 없음"))
    _add_field_line(document, "교사메모", fields.get("teacher_notes", "특이사항 없음"))

    output = BytesIO()
    document.save(output)
    return output.getvalue()
