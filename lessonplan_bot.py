import csv
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class WeekInfo:
    week_no: int
    date_range: str
    events: List[str]
    details: str
    raw_text: str
    year: int

    def to_dict(self) -> Dict:
        return asdict(self)


WEEK_RE = re.compile(
    r"(?m)^\s*(?P<week_no>\d{1,2})\s*주\s*(?P<date_range>\d{1,2}[./]\d{1,2}\s*[-~]\s*\d{1,2}[./]\d{1,2})(?P<tail>.*)$"
)
CLASS_RE = re.compile(r"\b(?:\d{1,2}[A-Za-z]|[A-Za-z]{1,3}\d{1,2})\b")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
HOLIDAY_RE = re.compile(r"휴강|공휴일|대체휴일|행사|시험")
DATE_DAY_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})\s*\(?([월화수목금토일])\)?")
DAY_ONLY_RE = re.compile(r"[월화수목금토일](?:/[월화수목금토일])+")


def _extract_pdf_text(path: Path) -> str:
    errors: List[str] = []
    try:
        from pypdf import PdfReader  # type: ignore

        text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        if text.strip():
            return text
        errors.append("pypdf empty")
    except Exception as exc:
        errors.append(f"pypdf: {exc}")

    try:
        from PyPDF2 import PdfReader  # type: ignore

        text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        if text.strip():
            return text
        errors.append("PyPDF2 empty")
    except Exception as exc:
        errors.append(f"PyPDF2: {exc}")

    raise RuntimeError("PDF 텍스트 추출 실패: " + " | ".join(errors))


def parse_weeks_from_text(text: str) -> List[WeekInfo]:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    matches = list(WEEK_RE.finditer(cleaned))
    year = int(YEAR_RE.search(text).group(1)) if YEAR_RE.search(text) else date.today().year
    weeks: List[WeekInfo] = []

    for idx, m in enumerate(matches):
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned)
        block = cleaned[m.start() : block_end].strip()
        details = " ".join(block.split())
        events = sorted(set(CLASS_RE.findall(block)))
        weeks.append(
            WeekInfo(
                week_no=int(m.group("week_no")),
                date_range=re.sub(r"\s+", "", m.group("date_range")),
                events=events,
                details=details[:400],
                raw_text=block[:2500],
                year=year,
            )
        )

    if not weeks:
        fallback = " ".join(cleaned.split())[:500] or "주차 정보 없음"
        weeks.append(WeekInfo(week_no=1, date_range="N/A", events=[], details=fallback, raw_text=fallback, year=year))

    return weeks


def parse_syllabus_pdf(pdf_path: Path) -> List[Dict]:
    return [w.to_dict() for w in parse_weeks_from_text(_extract_pdf_text(pdf_path))]


def parse_curriculum_sheet(path: Path) -> List[Dict]:
    rows: List[Dict] = []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = [dict(r) for r in csv.DictReader(f)]
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        import pandas as pd  # type: ignore

        rows = pd.read_excel(path).fillna("").to_dict(orient="records")
    else:
        return []

    normalized: List[Dict] = []
    for row in rows:
        lower = {str(k).strip().lower(): str(v).strip() for k, v in row.items()}

        def pick(*keys: str) -> str:
            for k in keys:
                if lower.get(k):
                    return lower[k]
            return ""

        week_raw = pick("week", "week_no", "주차")
        week_match = re.search(r"\d+", week_raw)
        normalized.append(
            {
                "week_no": int(week_match.group(0)) if week_match else None,
                "class_name": pick("class", "반", "분반", "target", "target group", "class_name"),
                "topic": pick("topic", "수업 주제", "주제"),
                "objective": pick("objective", "수업 목적", "목적"),
                "details": pick("details", "내용", "비고", "description"),
            }
        )

    return [r for r in normalized if any(r.values())]


def infer_lesson_datetime(week_info: Dict) -> str:
    year = int(week_info.get("year") or date.today().year)
    raw = " ".join([str(week_info.get("raw_text", "")), str(week_info.get("details", ""))])
    parts = []
    for mm, dd, day in DATE_DAY_RE.findall(raw):
        parts.append(f"{year}.{int(mm):02d}.{int(dd):02d}({day})")
    if parts:
        result = ", ".join(dict.fromkeys(parts))
    else:
        day_hint = DAY_ONLY_RE.search(raw)
        range_hint = str(week_info.get("date_range", ""))
        result = f"{range_hint} ({day_hint.group(0)})" if day_hint else range_hint
    if HOLIDAY_RE.search(raw):
        result = f"{result} [휴강/행사 확인]"
    return result or "일정 미확인"


def suggest_topic_objective(*, week_info: Dict, class_name: str, subject: str, curriculum_rows: Optional[List[Dict]] = None) -> Dict[str, str]:
    curriculum_rows = curriculum_rows or []
    week_no = int(week_info.get("week_no") or 0)
    class_norm = class_name.strip().lower()

    for row in curriculum_rows:
        if int(row.get("week_no") or 0) != week_no:
            continue
        row_class = str(row.get("class_name") or "").strip().lower()
        if row_class and class_norm and row_class != class_norm:
            continue
        topic = row.get("topic") or row.get("details") or f"{class_name} {subject} 수업"
        objective = row.get("objective") or f"{topic} 내용을 이해하고 적용한다."
        return {"lesson_topic": str(topic), "theme_objective": str(objective)}

    raw = str(week_info.get("details") or "").strip()
    brief = raw[:60] if raw else f"{class_name} 핵심 단원"
    return {
        "lesson_topic": f"{subject} - {brief}",
        "theme_objective": f"{brief}를 바탕으로 핵심 개념을 이해하고 활동으로 적용한다.",
    }


def generate_lesson_table_rows_text(*, week_info: Dict, class_plan_note: str, include_prayer: bool) -> str:
    intro = "기도 및 출석 확인, 지난 시간 복습" if include_prayer else "출석 확인, 지난 시간 복습"
    develop_seed = str(week_info.get("details") or "핵심 단원 학습")[:100]
    # Keep each table row as a single line so it won't be parsed into accidental extra rows.
    develop = f"{develop_seed} 설명 및 활동 (메모: {class_plan_note or '개념 확인 활동'})"
    return (
        f"도입|10분|{intro}|집중 유도\n"
        f"전개|25분|{develop}|질의응답\n"
        f"정리|5분|형성평가, 과제 안내, 다음 시간 예고|마무리"
    )


def parse_table_rows_text(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Continuation rule: lines without a full 4-column row are appended to previous row content.
        if "|" not in line or line.count("|") < 3:
            if rows:
                rows[-1]["content"] = (rows[-1]["content"] + "\n" + line).strip()
            else:
                rows.append({"phase": "", "time": "", "content": line, "remarks": ""})
            continue

        parts = [p.strip() for p in line.split("|", 3)]
        while len(parts) < 4:
            parts.append("")
        rows.append({"phase": parts[0], "time": parts[1], "content": parts[2], "remarks": parts[3]})
    return rows
