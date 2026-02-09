import re
from dataclasses import dataclass, asdict
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

    def to_dict(self) -> Dict:
        return asdict(self)


WEEK_LINE_RE = re.compile(
    r"(?m)^\s*(?P<week>\d{1,2})\s*주\s+(?P<date>\d{1,2}\.\d{1,2}\s*[-~]\s*\d{1,2}\.\d{1,2})\s*(?P<rest>.*)$"
)


CLASS_TOKEN_RE = re.compile(r"\b\d{1,2}[A-Za-z]\b")


def parse_weeks_from_text(text: str) -> List[WeekInfo]:
    """Parse weekly rows such as '1주 2.23-2.27 ... 11A, 11B'."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    weeks: List[WeekInfo] = []

    # Join wrapped lines with a sentinel and then recover blocks per week
    joined = "\n".join(lines)
    matches = list(WEEK_LINE_RE.finditer(joined))

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
            )
        )

    if not weeks:
        # fallback: create a single pseudo-week from whole text
        short = " ".join(lines)[:300]
        weeks.append(WeekInfo(week_no=1, date_range="N/A", events=[], details=short))

    return weeks


def parse_syllabus_pdf(pdf_path: Path) -> List[Dict]:
    text = _extract_pdf_text(pdf_path)
    return [wk.to_dict() for wk in parse_weeks_from_text(text)]


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
