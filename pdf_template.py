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


def _wrap_text(pdf: FPDF, text: str, max_width: float) -> List[str]:
    """Hard-wrap text to avoid FPDF horizontal-space crashes with long/unbroken strings."""
    clean = _safe_text(text, max_len=4000).replace("\r\n", "\n").replace("\r", "\n")
    lines: List[str] = []
    for raw in clean.split("\n"):
        segment = _chunk_unbroken(raw, 22)
        if not segment:
            lines.append("")
            continue

        current = ""
        for ch in segment:
            trial = f"{current}{ch}"
            if pdf.get_string_width(trial) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)

    return lines if lines else [""]


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

    page_w = pdf.w - pdf.l_margin - pdf.r_margin

    def draw_box(x: float, y: float, w: float, h: float) -> None:
        pdf.rect(x, y, w, h)

    def draw_wrapped_text(x: float, y: float, w: float, h: float, text: str, *, size: int = 10, pad: float = 1.8, bold: bool = False) -> None:
        pdf.set_font(fn, style="B" if bold else "", size=size)
        lines = _wrap_text(pdf, text, max_width=max(5.0, w - (pad * 2)))
        line_h = max(5.6, size * 0.45)
        max_lines = max(1, int((h - (pad * 2)) // line_h))
        lines = lines[:max_lines]
        ty = y + pad
        for ln in lines:
            pdf.set_xy(x + pad, ty)
            pdf.cell(w - (pad * 2), line_h, ln)
            ty += line_h

    def section_header(text: str) -> None:
        x = pdf.l_margin
        y = pdf.get_y()
        h = 8
        draw_box(x, y, page_w, h)
        pdf.set_font(fn, style="B", size=12)
        pdf.set_xy(x, y)
        pdf.cell(page_w, h, _safe_text(text, 120), align="C")
        pdf.set_y(y + h)

    def key_value_row(label: str, value: str, row_h: float = 9) -> None:
        x = pdf.l_margin
        y = pdf.get_y()
        lw = 44
        draw_box(x, y, lw, row_h)
        draw_box(x + lw, y, page_w - lw, row_h)
        draw_wrapped_text(x, y, lw, row_h, label, bold=True)
        draw_wrapped_text(x + lw, y, page_w - lw, row_h, value)
        pdf.set_y(y + row_h)

    pdf.set_font(fn, style="B", size=20)
    pdf.cell(0, 11, _safe_text(template_fields.get("doc_title", "주간 수업 계획서 및 보고서"), 120), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(1.5)

    # Header top area (matches sample's 2x2-like blocks)
    x = pdf.l_margin
    y = pdf.get_y()
    total_h = 24
    left_w = page_w * 0.5
    right_w = page_w - left_w
    draw_box(x, y, left_w, total_h)
    draw_box(x + left_w, y, right_w, total_h)
    draw_wrapped_text(x + 1, y + 1, left_w - 2, total_h - 2, f"교사: {template_fields.get('teacher_name', '고영찬')}\n수업: {template_fields.get('subject', '')}")
    right_text = (
        f"수업날짜: {template_fields.get('lesson_datetime', template_fields.get('week_label', ''))}\n"
        f"대상: {template_fields.get('target_group', template_fields.get('class_name', ''))}"
    )
    draw_wrapped_text(x + left_w + 1, y + 1, right_w - 2, total_h - 2, right_text)
    pdf.set_y(y + total_h)

    key_value_row("수업 필요 물품 / 준비물:", template_fields.get("materials", ""), row_h=9)
    pdf.ln(4)

    section_header("수업 주제 및 수업 목적")
    topic = template_fields.get("lesson_topic", "")
    objective = template_fields.get("theme_objective", "")
    topic_objective = f"수업 주제: {topic}\n수업 목적: {objective}"
    body_h = 26
    x = pdf.l_margin
    y = pdf.get_y()
    draw_box(x, y, page_w, body_h)
    draw_wrapped_text(x, y, page_w, body_h, topic_objective)
    pdf.set_y(y + body_h)
    pdf.ln(4)

    section_header("수업계획서")

    col_w = [16, 25, 118, 31]
    head_h = 8
    x = pdf.l_margin
    y = pdf.get_y()
    headers = ["주제", "시간", "내용", "참고사항"]
    for i, htxt in enumerate(headers):
        cx = x + sum(col_w[:i])
        draw_box(cx, y, col_w[i], head_h)
        pdf.set_font(fn, style="B", size=11)
        pdf.set_xy(cx, y)
        pdf.cell(col_w[i], head_h, htxt, align="C")
    pdf.set_y(y + head_h)

    rows = template_fields.get("lesson_rows") or [
        {"phase": "도입", "time": "10분", "content": "복습 및 동기 유발", "remarks": ""},
        {"phase": "전개", "time": "30분", "content": "핵심 개념 및 활동", "remarks": ""},
        {"phase": "정리", "time": "10분", "content": "형성평가 및 과제", "remarks": ""},
    ]

    line_h = 6.2
    for row in rows[:8]:
        values = [
            str(row.get("phase", "")),
            str(row.get("time", "")),
            str(row.get("content", "")),
            str(row.get("remarks", "")),
        ]
        wrapped = [_wrap_text(pdf, values[i], col_w[i] - 4) for i in range(4)]
        row_h = max(16, line_h * max(len(w) for w in wrapped) + 3)

        # Prevent row split mid-table; move to next page safely
        if pdf.get_y() + row_h > pdf.h - pdf.b_margin:
            pdf.add_page()
            section_header("수업계획서 (계속)")
            x = pdf.l_margin
            y = pdf.get_y()
            for i, htxt in enumerate(headers):
                cx = x + sum(col_w[:i])
                draw_box(cx, y, col_w[i], head_h)
                pdf.set_font(fn, style="B", size=11)
                pdf.set_xy(cx, y)
                pdf.cell(col_w[i], head_h, htxt, align="C")
            pdf.set_y(y + head_h)

        y = pdf.get_y()
        x = pdf.l_margin
        for i in range(4):
            cx = x + sum(col_w[:i])
            draw_box(cx, y, col_w[i], row_h)
            draw_wrapped_text(cx, y, col_w[i], row_h, values[i], bold=(i == 0 and bool(values[i])))
        pdf.set_y(y + row_h)

    pdf.ln(4)
    section_header("수업보고서")
    key_value_row("수업 평가:", template_fields.get("evaluation", ""), row_h=14)
    key_value_row("학생 특이 사항", template_fields.get("student_notes", ""), row_h=14)

    teacher_note = template_fields.get("teacher_notes", "")
    if template_fields.get("edited_draft", ""):
        teacher_note = f"{teacher_note}\n\n[초안]\n{template_fields.get('edited_draft', '')}".strip()
    key_value_row("교사 메모", teacher_note, row_h=26)

    out = BytesIO()
    out.write(pdf.output())
    return out.getvalue()
