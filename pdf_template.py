from io import BytesIO
from pathlib import Path
from typing import Dict, List

from fpdf import FPDF


def _find_font_path() -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return ""


def _safe_text(text: str, max_len: int = 1500) -> str:
    text = (text or "").replace("\x00", " ").strip()
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text


def _chunk_unbroken(text: str, chunk: int = 36) -> str:
    parts: List[str] = []
    for token in text.split():
        if len(token) <= chunk:
            parts.append(token)
            continue
        parts.extend(token[i : i + chunk] for i in range(0, len(token), chunk))
    return " ".join(parts) if parts else text


class LessonPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=12)
        self.font_name = "Helvetica"
        font_path = _find_font_path()
        if font_path:
            self.add_font("AppFont", "", font_path)
            self.font_name = "AppFont"


def render_week_pdf(template_fields: Dict) -> bytes:
    pdf = LessonPDF()
    pdf.add_page()
    fn = pdf.font_name

    def title(txt: str) -> None:
        pdf.set_font(fn, size=16)
        pdf.cell(0, 10, _safe_text(txt), new_x="LMARGIN", new_y="NEXT", align="C")

    def field_row(left: str, right: str, w_left: float = 35) -> None:
        pdf.set_font(fn, size=10)
        pdf.cell(w_left, 8, _safe_text(left), border=1)
        x = pdf.get_x()
        y = pdf.get_y()
        right_clean = _chunk_unbroken(_safe_text(right, max_len=400))
        pdf.multi_cell(0, 8, right_clean, border=1)
        pdf.set_xy(x, y + max(8, pdf.font_size * 1.8))

    title(template_fields.get("doc_title", "주간 수업안 및 보고서"))

    pdf.set_font(fn, size=10)
    width = (pdf.w - pdf.l_margin - pdf.r_margin) / 4
    headers = [
        ("교사", template_fields.get("teacher_name", "고영찬")),
        ("과목", template_fields.get("subject", "")),
        ("주차", template_fields.get("week_label", "")),
        ("반", template_fields.get("class_name", "")),
    ]
    for label, value in headers:
        pdf.cell(width * 0.35, 8, _safe_text(label), border=1)
        pdf.cell(width * 0.65, 8, _safe_text(value, 80), border=1)
    pdf.ln(8)

    field_row("일정", template_fields.get("schedule", ""))
    field_row("준비물", template_fields.get("materials", ""))
    field_row("주제/목표", template_fields.get("theme_objective", ""))

    pdf.ln(2)
    pdf.set_font(fn, size=11)
    pdf.cell(0, 8, "수업 계획", border=1, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(fn, size=10)
    col_w = [25, 22, 110, 33]
    for h, w in zip(["단계", "시간", "내용", "비고"], col_w):
        pdf.cell(w, 8, h, border=1, align="C")
    pdf.ln(8)

    rows = template_fields.get("lesson_rows") or [
        {"phase": "도입", "time": "10분", "content": "복습 및 동기 유발", "remarks": ""},
        {"phase": "전개", "time": "30분", "content": "핵심 개념 및 활동", "remarks": ""},
        {"phase": "정리", "time": "10분", "content": "형성평가 및 과제", "remarks": ""},
    ]

    for row in rows[:8]:
        p = _safe_text(str(row.get("phase", "")), 40)
        t = _safe_text(str(row.get("time", "")), 20)
        c = _chunk_unbroken(_safe_text(str(row.get("content", "")), 260), 30)
        r = _chunk_unbroken(_safe_text(str(row.get("remarks", "")), 100), 20)

        start_x, start_y = pdf.get_x(), pdf.get_y()
        pdf.multi_cell(col_w[0], 8, p, border=1)
        y_after_phase = pdf.get_y()

        pdf.set_xy(start_x + col_w[0], start_y)
        pdf.multi_cell(col_w[1], 8, t, border=1)
        y_after_time = pdf.get_y()

        pdf.set_xy(start_x + col_w[0] + col_w[1], start_y)
        pdf.multi_cell(col_w[2], 8, c, border=1)
        y_after_content = pdf.get_y()

        pdf.set_xy(start_x + col_w[0] + col_w[1] + col_w[2], start_y)
        pdf.multi_cell(col_w[3], 8, r, border=1)
        y_after_remark = pdf.get_y()

        pdf.set_xy(start_x, max(y_after_phase, y_after_time, y_after_content, y_after_remark))

    pdf.ln(2)
    pdf.set_font(fn, size=11)
    pdf.cell(0, 8, "수업 보고", border=1, new_x="LMARGIN", new_y="NEXT")
    field_row("평가", template_fields.get("evaluation", ""))
    field_row("학생 특이사항", template_fields.get("student_notes", ""))
    field_row("교사 메모", template_fields.get("teacher_notes", ""))

    draft = _chunk_unbroken(_safe_text(template_fields.get("edited_draft", ""), 3000), 35)
    pdf.set_font(fn, size=9)
    pdf.multi_cell(0, 6, f"첨부 초안\n{draft}", border=1)

    out = BytesIO()
    out.write(pdf.output())
    return out.getvalue()
