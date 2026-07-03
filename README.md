# AI 사용 의심 선별·검증 도구

독서 수행평가 제출물에서 AI 사용 의심 사례를 선별·검증하는 Python CLI 도구입니다.

> ⚠️ **중요**: 점수는 증거가 아니며 최종 판단은 교사의 구술 면담으로 확인합니다. 이 도구의 출력은 면담 대상 선별 및 면담 자료 생성용입니다.

## 개요

- **학교 내부 교사 전용** 도구
- **3단계 파이프라인**으로 정밀 선별
  1. **규칙 기반 점수** (API 미사용, 비용 0)
  2. **LLM 스크리닝** (전수 검사)
  3. **팩트시트 기반 사실 검증** (상위 후보만)
- **다중 모델 지원**: Anthropic (Claude), Google (Gemini), OpenAI (GPT)
- **프로필 관리**: API 키 암호화 저장, 여러 프로필 등록·선택

## 설치

```bash
cd ai_screening
pip install -r requirements.txt
```

### 환경 변수 (API Key) 설정
다른 기기에서 처음 프로젝트를 클론받은 경우, API 키 설정을 해야 정상 구동됩니다.
1. 프로젝트 루트에 있는 `.env.example` 파일을 `.env` 파일로 복사합니다.
   ```bash
   cp .env.example .env
   ```
2. 생성된 `.env` 파일을 편집기로 열어 사용하려는 서비스의 API 키를 입력한 후 저장합니다.
   ```env
   GEMINI_API_KEY=your_gemini_api_key
   ANTHROPIC_API_KEY=your_anthropic_api_key
   OPENAI_API_KEY=your_openai_api_key
   ```

### 필요한 환경

- Python 3.9 이상
- 선택한 모델 프로바이더의 API 키

## 빠른 시작

### 1. 프로필 등록 (최초 1회)

```bash
python screen.py add-profile
```

대화형으로 프로바이더, 모델, API 키, 암호를 설정합니다.

### 2. 로그인

```bash
python screen.py login
```

등록된 프로필을 선택하고 암호를 입력합니다.

### 3. 실행 (Web UI 버전 - 권장)

터미널 대신 직관적인 화면을 사용하려면 아래 명령어로 웹 프로그램을 구동합니다.

```bash
python app.py
```

자동으로 웹 브라우저(`http://localhost:8000`) 창이 열리며, 마우스 클릭으로 프로필 로그인, 분석 시작, 대시보드 통계 조회 및 개별 학생 보고서를 예쁘게 확인하실 수 있습니다.

### 4. 실행 (CLI 버전)

```bash
python screen.py ./submissions/
```

`./submissions/` 폴더의 `.txt`, `.docx` 파일을 모두 분석합니다.

## CLI 명령어

### 메인 실행

```bash
# 기본 실행 (1·2단계 전수 + 상위 후보 3단계)
python screen.py ./submissions/

# 전원 3단계 실행
python screen.py ./submissions/ --verify-all

# 3단계 생략
python screen.py ./submissions/ --no-verify

# 팩트시트 자동 생성 금지
python screen.py ./submissions/ --no-web
```

### 프로필 관리

```bash
# 프로필 등록
python screen.py add-profile

# 프로필 목록
python screen.py list-profiles

# 로그인
python screen.py login

# 로그아웃
python screen.py logout

# 프로필 삭제
python screen.py delete-profile <프로필명>

# 모델 변경
python screen.py select-model
```

## 입력

- `./submissions/` 폴더에 `.txt` 또는 `.docx` 파일을 넣습니다
- 파일명(확장자 제외)이 학생 식별자입니다
- `학생이름_책제목` 형식이면 책제목을 자동 파싱합니다
- `.txt`는 UTF-8 → CP949 순 인코딩 자동 감지
- `.docx`는 편집 시간·작성자 등 메타데이터도 추출합니다

## 출력

### results.csv

| 열 | 내용 |
|---|---|
| student | 파일명 (학생 식별자) |
| book_title | 식별된 책 제목 |
| rule_score | 1단계 종합 점수 (0-100) |
| rule_evidence | 검출 근거 (원문 예시 포함) |
| edit_time_min | docx 편집 시간 (없으면 공란) |
| ai_score | 2단계 risk_score |
| ai_signals | 검출된 AI 문체 신호 |
| contradictions | 3단계 "모순" 건수 |
| hallucination_score | 3단계 환각 점수 |
| tier | 최우선 / 상 / 중 / 하 |
| report | 리포트 파일 경로 |

### reports/*.md

3단계를 거친 학생마다 상세 리포트가 생성됩니다:
- 제출물 전문
- 1단계 검출 근거 (원문 위치 인용)
- 2단계 AI 문체 신호
- 3단계 주장별 판정표
- 면담 확인 질문 제안 3개

## 등급 기준

| 등급 | 조건 |
|------|------|
| **최우선** | 3단계에서 "모순" 발견 |
| **상** | rule_score와 ai_score 모두 상위 30% |
| **중** | 둘 중 하나만 상위 30% |
| **하** | 나머지 |

임계값(30%)은 `config.yaml`에서 조정 가능합니다.

## 팩트시트

- `factsheets/` 폴더에 책별 팩트시트가 저장됩니다
- 한 번 생성된 팩트시트는 다음에 재사용되어 **토큰 비용이 들지 않습니다**
- 교사가 직접 작성한 팩트시트를 같은 폴더에 두면 우선 적용됩니다
- `--no-web` 옵션으로 자동 생성을 막을 수 있습니다

## 설정 (config.yaml)

`config.yaml`에서 다음을 조정할 수 있습니다:
- 각 규칙의 가중치
- 챗봇 상투구 목록
- 등급 임계값
- 메타데이터 판정 기준
- API 단가 (비용 추정용)
- 사용 가능 모델 목록

## 비용

실행 종료 시 콘솔에 모델별 토큰 사용량과 예상 비용(USD)이 출력됩니다.

### 비용 절감 전략

- **1단계**: API 미사용 (비용 0)
- **2단계**: 경량 모델 사용 (Haiku / Flash / GPT-4o-mini)
- **3단계**: 상위 후보만 실행 + 팩트시트 재사용
- **Anthropic 사용 시**: 시스템 프롬프트 캐싱으로 추가 절감

## 테스트

```bash
pytest tests/ -v
```

## 라이선스

학교 내부 사용 전용.

---

> 📌 **면책**: 이 도구는 AI 사용 가능성을 기계적으로 선별하는 보조 도구일 뿐입니다. **점수는 증거가 아니며, 최종 판단은 반드시 교사의 구술 면담을 통해 확인해야 합니다.** AI가 작성하지 않은 글도 높은 점수를 받을 수 있고, AI가 작성한 글도 낮은 점수를 받을 수 있습니다.
