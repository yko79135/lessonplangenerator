import csv
import re
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional


def _extract_pdf_text(path: Path) -> str:
    """Extract text from PDF using pypdf first, then PyPDF2 fallback."""
    errors: List[str] = []

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if text.strip():
            return text
        errors.append("pypdf extracted empty text")
    except Exception as exc:  # pragma: no cover - defensive fallback
        errors.append(f"pypdf failed: {exc}")

    try:
        from PyPDF2 import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if text.strip():
            return text
        errors.append("PyPDF2 extracted empty text")
    except Exception as exc:  # pragma: no cover - defensive fallback
        errors.append(f"PyPDF2 failed: {exc}")

    raise RuntimeError("Could not parse PDF text. " + " | ".join(errors))


@dataclass
class WeekInfo:
    week_no: int
    date_range: str
    events: List[str]
    details: str
    raw_text: str
    year: Optional[int] = None

    def to_dict(self) -> Dict:
        return asdict(self)


WEEK_LINE_RE = re.compile(
    r"(?m)^\s*(?P<week>\d{1,2})\s*주\s+(?P<date>\d{1,2}\.\d{1,2}\s*[-~]\s*\d{1,2}\.\d{1,2})\s*(?P<rest>.*)$"
)


CLASS_TOKEN_RE = re.compile(r"\b(?:\d{1,2}[A-Za-z]|[A-Za-z]{1,3}\d{1,2})\b")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
MMDD_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?!\d)")
WEEKDAY_RE = re.compile(r"[월화수목금토일]")
DATE_WD_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?:\([^)]*\))?\s*([월화수목금토일])")
HOLIDAY_RE = re.compile(r"휴강|공휴일|대체휴일|시험|행사")


def parse_weeks_from_text(text: str) -> List[WeekInfo]:
    """Parse weekly rows such as '1주 2.23-2.27 ... 11A, 11B'."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    weeks: List[WeekInfo] = []

    # Join wrapped lines with a sentinel and then recover blocks per week
    joined = "\n".join(lines)
    matches = list(WEEK_LINE_RE.finditer(joined))

    year_match = YEAR_RE.search(text)
    parsed_year = int(year_match.group(1)) if year_match else date.today().year

    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(joined)
        block_tail = joined[start:end].strip()

        week_no = int(match.group("week"))
        date_range = re.sub(r"\s+", "", match.group("date"))
        first_rest = match.group("rest").strip()

        block = "\n".join([x for x in [first_rest, block_tail] if x])
        events = CLASS_TOKEN_RE.findall(block)
        details_lines = [ln for ln in block.splitlines() if ln.strip()]
        details = details_lines[-1] if details_lines else first_rest
        weeks.append(
            WeekInfo(
                week_no=week_no,
                date_range=date_range,
                events=sorted(set(events)) if events else [],
                details=details[:500],
                raw_text=block[:2000],
                year=parsed_year,
            )
        )

    if not weeks:
        # fallback: create a single pseudo-week from whole text
        short = " ".join(lines)[:300]
        weeks.append(WeekInfo(week_no=1, date_range="N/A", events=[], details=short, raw_text=short, year=parsed_year))

    return weeks


def parse_syllabus_pdf(pdf_path: Path) -> List[Dict]:
    text = _extract_pdf_text(pdf_path)
    return [wk.to_dict() for wk in parse_weeks_from_text(text)]


def parse_curriculum_sheet(path: Path) -> List[Dict]:
    """Parse optional CSV/XLSX curriculum table.

    Expected flexible columns such as:
    - week / week_no / 주차
    - class / target / 반 / 분반
    - topic / 주제
    - objective / 목적
    - details / 내용
    """
    suffix = path.suffix.lower()
    rows: List[Dict] = []

    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
    elif suffix in {".xlsx", ".xls"}:
        import pandas as pd  # type: ignore

        df = pd.read_excel(path)
        rows = df.fillna("").to_dict(orient="records")
    else:
        return []

    normalized: List[Dict] = []
    for r in rows:
        lowered = {str(k).strip().lower(): v for k, v in r.items()}

        def pick(*names: str) -> str:
            for n in names:
                if n in lowered and str(lowered[n]).strip():
                    return str(lowered[n]).strip()
            return ""

        week_raw = pick("week", "week_no", "주차")
        week_no = int(re.search(r"\d+", week_raw).group(0)) if re.search(r"\d+", week_raw) else None
        entry = {
            "week_no": week_no,
            "class_name": pick("class", "target", "반", "분반", "class_name", "target group"),
            "topic": pick("topic", "수업 주제", "주제"),
            "objective": pick("objective", "수업 목적", "목적"),
            "details": pick("details", "내용", "비고", "description"),
        }
        if any(entry.values()):
            normalized.append(entry)
    return normalized


def infer_lesson_datetime(week_info: Dict) -> str:
    """Infer lesson date/time text from week block data, weekdays and holiday hints."""
    year = int(week_info.get("year") or date.today().year)
    raw = " ".join([week_info.get("raw_text", ""), week_info.get("details", "")])
    date_with_weekday = [(int(m.group(1)), int(m.group(2)), m.group(3)) for m in DATE_WD_RE.finditer(raw)]

    date_parts: List[str] = []
    for month, day, wd in date_with_weekday[:4]:
        label = f"{year:04d}.{month:02d}.{day:02d} {wd}".strip()
        if HOLIDAY_RE.search(raw):
            label += " (휴강/행사 확인)"
        date_parts.append(label)

    if date_parts:
        return ", ".join(dict.fromkeys(date_parts))

    mmdd = [(int(m.group(1)), int(m.group(2))) for m in MMDD_RE.finditer(raw)]

    # fallback using date range
    dr = str(week_info.get("date_range", ""))
    mmdd_range = MMDD_RE.findall(dr)
    if mmdd_range:
        built = [f"{year:04d}.{int(m):02d}.{int(d):02d}" for m, d in mmdd_range[:2]]
        return " ~ ".join(built)
    return dr or "일정 미확인"


def suggest_topic_objective(
    *,
    week_info: Dict,
    class_name: str,
    subject: str,
    curriculum_rows: Optional[List[Dict]] = None,
) -> Dict[str, str]:
    """Auto-fill topic/objective from curriculum sheet first, then syllabus details."""
    curriculum_rows = curriculum_rows or []
    week_no = int(week_info.get("week_no") or 0)

    for row in curriculum_rows:
        r_week = int(row.get("week_no") or 0)
        r_class = str(row.get("class_name") or "").strip().lower()
        if r_week == week_no and (not r_class or r_class == class_name.strip().lower()):
            topic = row.get("topic") or row.get("details") or f"{subject} - {class_name} 주간 수업"
            objective = row.get("objective") or f"{topic} 내용을 이해하고 활동에 적용한다."
            return {"lesson_topic": str(topic), "theme_objective": str(objective)}

    details = str(week_info.get("details", "")).strip()
    short_detail = details[:90] if details else f"{class_name} 대상 핵심 단원"
    return {
        "lesson_topic": f"{subject} - {short_detail}",
        "theme_objective": f"{short_detail}를 중심으로 핵심 개념을 이해하고, 학생 참여 활동을 통해 적용 능력을 기른다.",
    }


def generate_weekly_draft(
    *,
    subject: str,
    week_info: Dict,
    class_plan_note: str,
    teacher_name: str,
    class_name: str,
    schedule: str,
    materials: str,
    include_prayer: bool,
) -> str:
    prayer_line = "- 기도: 수업 시작 전 짧은 기도 진행\n" if include_prayer else ""
    events = ", ".join(week_info.get("events", [])) or "해당 없음"
    details = week_info.get("details", "")

    return (
        f"[주간 수업안/보고서 초안]\n"
        f"과목: {subject}\n"
        f"주차: Week {week_info.get('week_no')} ({week_info.get('date_range')})\n"
        f"담당교사: {teacher_name}\n"
        f"반: {class_name}\n"
        f"시간표: {schedule}\n"
        f"준비물: {materials}\n\n"
        f"1) 주차 요약\n"
        f"- 강의계획서 분석: {details}\n"
        f"- 관련 반/그룹: {events}\n"
        f"- 메모: {class_plan_note or '없음'}\n"
        f"{prayer_line}"
        f"2) 수업 목표\n"
        f"- 핵심 개념 이해와 적용\n"
        f"- 학생 참여형 활동을 통한 확인\n\n"
        f"3) 진행 계획\n"
        f"- 도입(10분): 지난 시간 복습 및 동기 유발\n"
        f"- 전개(30분): 핵심 개념 설명, 활동, 질의응답\n"
        f"- 정리(10분): 형성평가 및 과제 안내\n\n"
        f"4) 수업 후 보고\n"
        f"- 학생 반응 및 이해도: (작성)\n"
        f"- 보완할 점: (작성)\n"
    )


def generate_lesson_table_rows_text(
    *,
    week_info: Dict,
    class_plan_note: str,
    include_prayer: bool,
) -> str:
    """Generate editable content for the 수업계획서 table rows only."""
    details = (week_info.get("details") or "핵심 단원 학습").strip()
    events = ", ".join(week_info.get("events", [])) or "해당 반 활동"
    intro = "기도와 출석 확인, 지난 시간 복습" if include_prayer else "출석 확인, 지난 시간 복습"
    develop = f"{details} 중심 설명 및 활동 / 대상: {events} / 활동: {class_plan_note or '개념 확인 활동'}"
    close = "형성평가, 과제 안내, 다음 시간 예고"

    return (
        f"도입|10분|{intro}|집중 유도\n"
        f"전개|25분|{develop}|질의응답\n"
        f"마무리|5분|{close}|정리"
    )
