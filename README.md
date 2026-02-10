# 주간 수업 계획서 및 보고서 생성기 (Streamlit)

강의계획서 PDF를 라이브러리에 저장하고, 주차별 정보를 추출해 **고정 템플릿 PDF** 형태의 `주간 수업 계획서 및 보고서`를 생성/편집/내보내기/Google Docs 업로드하는 앱입니다.

## 필수 파일 구성
- `web_app.py`: Streamlit UI 및 전체 사용자 플로우
- `lessonplan_bot.py`: PDF 주차/아웃라인 파싱, 표 초안 생성
- `pdf_template.py`: fpdf2 기반 고정 템플릿 렌더러 (`render_week_pdf(fields) -> bytes`)
- `google_drive_uploader.py`: OAuth 기반 Google Docs/Drive 업로드 유틸 (lazy import)
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
앱은 OAuth 사용자 인증(`authorized_user`)만 사용하며, **OOB(`urn:ietf:wg:oauth:2.0:oob`)를 사용하지 않습니다**.

### Google Cloud OAuth Client ID 생성 (필수)
1. Google Cloud Console → **APIs & Services** → **Credentials** 이동
2. **Create Credentials** → **OAuth client ID** 선택
3. Application type은 반드시 **Web application** 선택
4. **Authorized redirect URIs**에 아래 URI 추가
   - `{app_base_url}/oauth/callback`
   - 예시: `https://YOUR_APP.streamlit.app/oauth/callback`
5. 개발 환경도 사용할 경우 추가
   - `http://localhost:8501/oauth/callback`
6. 생성 후 다운로드한 OAuth Client JSON(`web` 또는 `installed` 키 포함)을 앱에 입력

인증 정보 로딩 순서:
1. `GOOGLE_OAUTH_USER_JSON` 또는 Streamlit secrets `gcp_oauth_user`
2. 앱 UI의 `OAuth 사용자 인증 JSON 직접 입력(선택)`
3. 앱 UI OAuth 연결 완료 시 세션(`gcp_oauth_user_payload`)에 저장된 인증정보

OAuth 클라이언트(JSON) 로딩 순서:
1. `GOOGLE_OAUTH_CLIENT_JSON` 또는 Streamlit secrets `gcp_oauth_client`
2. 앱 UI의 `OAuth Client JSON`

### OAuth 인증 생성 절차(앱 내)
1. `app_base_url`을 설정 (권장: `st.secrets["app_base_url"]`)
2. `OAuth Client JSON` 입력
3. `Google 로그인 시작` 클릭
4. 표시된 `Google 로그인` 링크에서 계정 동의
5. 앱의 `/oauth/callback?code=...&state=...`로 돌아오면 자동 코드 교환 및 세션 인증 저장
6. `Upload as Google Doc` 클릭 시 저장된 인증정보로 업로드

### 업로드 오류 트러블슈팅
- `403 The caller does not have permission`
  - Google Cloud에서 **Google Docs API**와 **Google Drive API** 활성화 확인
  - OAuth 로그인한 계정이 대상 폴더 접근 권한을 가지고 있는지 확인
  - 조직(Workspace) 정책에서 Docs/Drive API 호출을 차단하지 않았는지 확인
- `401 Unauthorized`
  - OAuth 인증정보가 만료·폐기되었는지 확인하고 인증 JSON을 재생성

## 안정성 메모
- PDF 텍스트 추출은 `pypdf` 우선, 실패 시 `PyPDF2` fallback
- PDF 렌더링은 긴 문자열/특수문자에 대해 줄바꿈/분할 방어 로직 포함
- 앱 전역 예외는 `st.error` + traceback으로 표시하여 blank-screen 방지
