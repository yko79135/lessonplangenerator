import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
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
SUBSECTION_CODE_RE = re.compile(r"\b(?P<code>\d{1,2}[A-Za-z])\b")
YEAR_RE = re.compile(r"\b(20\d{2})\b")
HOLIDAY_RE = re.compile(r"휴강|공휴일|대체휴일|행사|시험")
DATE_DAY_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})\s*\(?([월화수목금토일])\)?")
DAY_ONLY_RE = re.compile(r"[월화수목금토일](?:/[월화수목금토일])+")
WEEKDAY_TOKEN_RE = re.compile(r"[월화수목금토일](?:\s*/\s*[월화수목금토일])+")

WEEKDAY_MAP = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}


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


def _clean_outline_title(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip(" -|:\t")
    t = re.sub(r"\s+\d{1,3}$", "", t)
    return t.strip()


def _looks_like_outline_title(text: str) -> bool:
    if not text:
        return False
    if re.search(r"\b\d{1,2}[./-]\d{1,2}\b", text):
        return False
    if re.search(r"\b\d+주\b", text):
        return False
    if not re.search(r"[A-Za-z가-힣]", text):
        return False
    if len(text) < 2:
        return False
    return True


def extract_outline_code_title_map(text: str) -> Dict[str, str]:
    """Extract subsection code->title mapping from syllabus outline/table-of-contents text."""
    mapping: Dict[str, str] = {}
    lines = [ln.strip() for ln in (text or "").replace("\r", "\n").split("\n")]

    for idx, line in enumerate(lines):
        if not line:
            continue

        code_matches = list(SUBSECTION_CODE_RE.finditer(line))
        if not code_matches:
            continue

        for i, match in enumerate(code_matches):
            code = match.group("code").upper()
            start = match.end()
            end = code_matches[i + 1].start() if i + 1 < len(code_matches) else len(line)
            raw_title = _clean_outline_title(line[start:end])

            if not raw_title:
                next_line = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
                if next_line and not SUBSECTION_CODE_RE.search(next_line):
                    raw_title = _clean_outline_title(next_line)

            if _looks_like_outline_title(raw_title) and code not in mapping:
                mapping[code] = raw_title

    return mapping


def extract_week_subsection_codes(week_info: Dict) -> List[str]:
    search_space = " ".join(
        [
            str(week_info.get("raw_text", "")),
            str(week_info.get("details", "")),
            " ".join(week_info.get("events", [])),
        ]
    )
    codes: List[str] = []
    for m in SUBSECTION_CODE_RE.finditer(search_space):
        code = m.group("code").upper()
        if code not in codes:
            codes.append(code)
    return codes


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


def parse_syllabus_pdf(pdf_path: Path) -> Dict:
    text = _extract_pdf_text(pdf_path)
    return {
        "weeks": [w.to_dict() for w in parse_weeks_from_text(text)],
        "outline_map": extract_outline_code_title_map(text),
        "raw_text": text[:50000],
    }


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


def infer_class_dates_from_week(week_info: Dict) -> str:
    """Infer concrete class dates from date-range + weekday hints (화/목 etc.)."""
    year = int(week_info.get("year") or date.today().year)
    raw = " ".join([str(week_info.get("raw_text", "")), str(week_info.get("details", ""))])
    dr = str(week_info.get("date_range", ""))

    mmdd = re.findall(r"(\d{1,2})[./-](\d{1,2})", dr)
    if len(mmdd) < 2:
        return infer_lesson_datetime(week_info)

    start = datetime(year, int(mmdd[0][0]), int(mmdd[0][1]))
    end = datetime(year, int(mmdd[1][0]), int(mmdd[1][1]))
    if end < start:
        end = end.replace(year=end.year + 1)

    weekday_tokens = []
    for match in WEEKDAY_TOKEN_RE.findall(raw):
        weekday_tokens.extend(re.findall(r"[월화수목금토일]", match))
    weekday_tokens = list(dict.fromkeys(weekday_tokens))
    target_days = {WEEKDAY_MAP[t] for t in weekday_tokens if t in WEEKDAY_MAP}

    explicit = []
    for mm, dd, day in DATE_DAY_RE.findall(raw):
        explicit.append(f"{int(mm)}.{int(dd)}({day})")
    if explicit:
        result = ", ".join(dict.fromkeys(explicit))
        if HOLIDAY_RE.search(raw):
            result += " [휴강/행사 확인]"
        return result

    all_dates = []
    cur = start
    while cur <= end:
        if not target_days or cur.weekday() in target_days:
            all_dates.append(cur)
        cur += timedelta(days=1)

    if not all_dates:
        all_dates = [start, end] if start != end else [start]

    weekday_rev = {v: k for k, v in WEEKDAY_MAP.items()}
    label = ", ".join(f"{d.month}.{d.day}({weekday_rev[d.weekday()]})" for d in all_dates)
    if HOLIDAY_RE.search(raw):
        label += " [휴강/행사 확인]"
    return label


def suggest_topic_objective(*, week_info: Dict, class_name: str, subject: str, curriculum_rows: Optional[List[Dict]] = None) -> Dict[str, str]:
    curriculum_rows = curriculum_rows or []
    week_no = int(week_info.get("week_no") or 0)
    class_norm = class_name.strip().lower()

    mmdd = re.findall(r"(\d{1,2})[./-](\d{1,2})", dr)
    if len(mmdd) < 2:
        return infer_lesson_datetime(week_info)

    start = datetime(year, int(mmdd[0][0]), int(mmdd[0][1]))
    end = datetime(year, int(mmdd[1][0]), int(mmdd[1][1]))
    if end < start:
        end = end.replace(year=end.year + 1)

    weekday_tokens = []
    for match in WEEKDAY_TOKEN_RE.findall(raw):
        weekday_tokens.extend(re.findall(r"[월화수목금토일]", match))
    weekday_tokens = list(dict.fromkeys(weekday_tokens))
    target_days = {WEEKDAY_MAP[t] for t in weekday_tokens if t in WEEKDAY_MAP}

    explicit = []
    for mm, dd, day in DATE_DAY_RE.findall(raw):
        explicit.append(f"{int(mm)}.{int(dd)}({day})")
    if explicit:
        result = ", ".join(dict.fromkeys(explicit))
        if HOLIDAY_RE.search(raw):
            result += " [휴강/행사 확인]"
        return result

    all_dates = []
    cur = start
    while cur <= end:
        if not target_days or cur.weekday() in target_days:
            all_dates.append(cur)
        cur += timedelta(days=1)

    if not all_dates:
        all_dates = [start, end] if start != end else [start]

    weekday_rev = {v: k for k, v in WEEKDAY_MAP.items()}
    label = ", ".join(f"{d.month}.{d.day}({weekday_rev[d.weekday()]})" for d in all_dates)
    if HOLIDAY_RE.search(raw):
        label += " [휴강/행사 확인]"
    return label


def suggest_topic_objective_from_syllabus(*, week_info: Dict, subject: str, outline_map: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    outline_map = {str(k).upper(): str(v) for k, v in (outline_map or {}).items()}
    codes = extract_week_subsection_codes(week_info)

    if codes:
        topics = [outline_map.get(code, code) for code in codes]
        lesson_topic = ", ".join(topics)
        theme_objective = f"{lesson_topic} 관련 핵심 개념을 이해하고 활동으로 적용한다."
        return {"lesson_topic": lesson_topic, "theme_objective": theme_objective}

    raw = str(week_info.get("details") or "").strip()
    brief = raw[:60] if raw else "핵심 단원"
    return {
        "lesson_topic": f"{subject} - {brief}",
        "theme_objective": f"{brief}를 바탕으로 핵심 개념을 이해하고 활동으로 적용한다.",
    }


def generate_lesson_table_rows_text(*, week_info: Dict, class_plan_note: str, include_prayer: bool) -> str:
    intro = "기도 및 출석 확인, 지난 시간 복습" if include_prayer else "출석 확인, 지난 시간 복습"
    develop_seed = str(week_info.get("details") or "핵심 단원 학습")[:100]
    develop = f"{develop_seed} 설명 및 활동\n- 메모: {class_plan_note or '개념 확인 활동'}"
    return (
        f"도입|10분|{intro}|집중 유도\n"
        f"전개|25분|{develop}|질의응답\n"
        f"정리|5분|형성평가, 과제 안내, 다음 시간 예고|마무리"
    )



def normalize_table_rows(rows: Optional[List[Dict]]) -> List[Dict[str, str]]:
    repaired: List[Dict[str, str]] = []
    for row in rows or []:
        phase = str((row or {}).get("phase", "")).strip()
        time = str((row or {}).get("time", "")).strip()
        content = str((row or {}).get("content", "")).strip()
        remarks = str((row or {}).get("remarks", "")).strip()

        if not any([phase, time, content, remarks]):
            continue

        if not content and repaired:
            addon = " | ".join(v for v in [phase, time, remarks] if v)
            if addon:
                repaired[-1]["content"] = f"{repaired[-1]['content']}\n{addon}".strip()
            continue

        repaired.append({"phase": phase, "time": time, "content": content, "remarks": remarks})

    return repaired

def parse_table_rows_text(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" not in line:
            if rows:
                rows[-1]["content"] = (rows[-1]["content"] + "\n" + line).strip()
            else:
                rows.append({"phase": "", "time": "", "content": line, "remarks": ""})
            continue

        parts = [p.strip() for p in line.split("|", 3)]
        while len(parts) < 4:
            parts.append("")
        rows.append({"phase": parts[0], "time": parts[1], "content": parts[2], "remarks": parts[3]})
    return normalize_table_rows(rows)
