# 주간 수업 계획서 및 보고서 생성기 (Streamlit)

강의계획서 PDF를 라이브러리에 저장하고, 주차별 정보를 추출해 **고정 템플릿 PDF** 형태의 `주간 수업 계획서 및 보고서`를 생성/편집/내보내기/Google Docs 업로드하는 앱입니다.

## 필수 파일 구성
- `web_app.py`: Streamlit UI 및 전체 사용자 플로우
- `lessonplan_bot.py`: PDF 주차/아웃라인 파싱, 표 초안 생성
- `pdf_template.py`: fpdf2 기반 고정 템플릿 렌더러 (`render_week_pdf(fields) -> bytes`)
- `google_drive_uploader.py`: Google Docs/Drive 업로드 유틸 (lazy import)
- `requirements.txt`: 루트 의존성 파일
- `packages.txt`: Streamlit Cloud용 시스템 패키지(한글 폰트)

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run web_app.py
```

## Streamlit Cloud 배포
1. 저장소 루트에 `requirements.txt`, `packages.txt` 유지
2. 앱 엔트리포인트를 `web_app.py`로 지정
3. `packages.txt`에 `fonts-nanum` 포함 (PDF 한글 폰트)
4. Google 업로드를 쓰려면 아래 인증정보 설정

## 데이터 영속성
- 강의계획서 PDF 저장 경로: `data/syllabi/`
- 라이브러리 인덱스: `data/syllabi_index.json`

## 기능 요약
- 주차 파싱: `1주 2.23-2.27 ... 11A, 11B` 같은 한국형 패턴 파싱
- 주차 선택 후 자동 기본값 추론:
  - 수업 / 수업날짜 / 대상
  - 수업주제 / 수업목적(강의계획서 본문 + 아웃라인 코드 매핑 기반)
- `초안생성`은 **수업계획서 표 행(단계|시간|내용|비고)** 만 생성
- 초안 텍스트 편집 후 `(11-1) 수정 내용 반영`을 눌러 TXT/PDF/Google Docs에 동일 반영
- Google Doc으로 전체 보고서 업로드 및 폴더 이동

## Google Docs 업로드 설정
앱은 아래 순서로 인증 정보를 찾습니다.

1. `GOOGLE_OAUTH_USER_JSON` 또는 Streamlit secrets `gcp_oauth_user` (권장)
2. `GOOGLE_SERVICE_ACCOUNT_JSON` 또는 Streamlit secrets `gcp_service_account` (대안)

3. 앱 UI의 `Google 인증 JSON 직접 입력(선택)`에 JSON을 붙여넣기 (세션 한정)

### OAuth 사용자 인증(권장)
- 개인 사용자 권한으로 문서를 생성/이동합니다.
- 대상 공유 폴더에 사용자가 접근 권한이 있어야 합니다.
- 앱 내 JSON 입력을 쓸 경우 `authorized_user` 형식(JSON 전체)을 그대로 붙여넣으면 됩니다.

### 서비스 계정 인증
- 폴더 관리자가 서비스 계정 이메일을 해당 폴더에 **편집자(Editor)** 로 공유해야 합니다.
- 관리자 권한 자체는 필요하지 않지만, 폴더 공유는 필수입니다.

## 안정성 메모
- PDF 텍스트 추출은 `pypdf` 우선, 실패 시 `PyPDF2` fallback
- PDF 렌더링은 긴 문자열/특수문자에 대해 줄바꿈/분할 방어 로직 포함
- 앱 전역 예외는 `st.error` + traceback으로 표시하여 blank-screen 방지
