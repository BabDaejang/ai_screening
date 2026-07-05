# AI 사용 의심 선별·검증 도구(제작: 종촌고 임태형, historysorang@gmail.com)

학생 독후감(독서 수행평가) 제출물에서 AI 사용 의심 사례와 할루시네이션(거짓 사실 주장)을 선별·검증하는 도구입니다. 웹 UI(FastAPI)와 CLI 두 가지 방식으로 사용할 수 있습니다.

> ⚠️ **중요**: 점수는 증거가 아니며 최종 판단은 교사의 구술 면담으로 확인합니다. 이 도구의 출력은 면담 대상 선별 및 면담 자료 생성용입니다.

## 개요

- **학교 내부 교사 전용** 도구
- **토큰 최소화 파이프라인**: 로컬 연산으로 먼저 거르고, LLM은 사용자가 승인한 단계·대상에만 호출
  - **Phase 0 — 데이터 로드** (토큰 0): Excel/CSV/PDF/TXT/DOCX에서 학번·이름·도서명·본문 추출
  - **Phase 1 — 규칙 기반 검사** (토큰 0): 8종 로컬 휴리스틱으로 점수화, Safe/Warning/Danger 등급 배지 표시
  - **Phase 2 — LLM 문체 스크리닝** (토큰 소비): 사용자가 [다음 단계 진행]을 눌러야 시작
  - **Phase 3 — 팩트시트 기반 사실 검증** (토큰 소비): 듀얼 패널 모달에서 검증 대상을 확정해야 시작
- **다중 모델 지원**: Anthropic (Claude), Google (Gemini), OpenAI (GPT) — 단계별로 다른 프로바이더 조합 가능
- **프로필 관리**: API 키 암호화 저장, 여러 프로필 등록·선택
- **작업 상태 이식성**: `session_progress.json` 자동 저장/복원 — 다른 PC로 파일만 옮겨 작업을 이어갈 수 있음

## 디렉토리 구조

```
ai_screening/
├── app.py                     # 웹 UI 서버 (FastAPI) — 파이프라인 오케스트레이션, 게이팅, 세션 API
├── screen.py                  # CLI 버전 진입점
├── config.yaml                # 규칙 가중치·임계값·상투어·단가 등 교사 편집용 설정
├── stages/
│   ├── stage1_rules.py        # Phase 1: 규칙 기반 검사 (특수문자, 마크다운 잔재, 상투구,
│   │                          #   복붙 흔적, 구조 균질성, 문장 길이 분산, 어휘 다양성(MATTR), 메타데이터)
│   ├── stage2_screening.py    # Phase 2: LLM 문체 스크리닝 (학생별 독립 호출)
│   ├── stage3_verify.py       # Phase 3: 팩트시트 대조 사실 검증 + 면담 질문 생성
│   └── factsheet_prompt.py    # 팩트시트 생성 프롬프트 단일 소스 (메타 10% / 내용 90% 강제)
├── providers/                 # LLM 프로바이더 어댑터 (gemini / anthropic / openai)
├── utils/
│   ├── file_reader.py         # Phase 0: 파일 로드 (인코딩 폴백, 헤더 행 자동 탐지)
│   ├── session_store.py       # 세션 진행 상태 저장/복원 (session_progress.json)
│   ├── cost_tracker.py        # 토큰 사용량·비용 추적
│   ├── docx_metadata.py       # docx 편집 시간·작성자 메타데이터 추출
│   ├── report_generator.py    # CSV·마크다운 리포트 생성, 등급 산출
│   └── user_manager.py        # 프로필·API 키 관리
├── static/                    # 웹 UI (index.html / app.js / style.css)
├── factsheets/                # 도서별 팩트시트 .md 캐시
├── book_cache.json            # 글로벌 도서 캐시 (세션과 분리 — 모든 사용자·세션이 공유)
├── session_progress.json      # 현재 세션 스냅샷 (자동 생성 — 타 PC 이관용)
└── screening_results.jsonl    # 학생별 완료 체크포인트 (append-only, 재실행 시 자동 스킵)
```

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

자동으로 웹 브라우저(`http://localhost:8000`) 창이 열립니다.

**웹 UI 작업 흐름:**

1. **프로필 로그인** 후 [API 키 관리]에서 사용할 프로바이더의 키를 등록합니다.
2. [분석 실행]에서 **제출물 파일 선택**(Excel/CSV/PDF/TXT/DOCX, 복수 선택 가능) 후 단계별 모델을 고르고 **[선별 검사 시작]**을 누릅니다.
3. **Phase 1(규칙 검사)** 이 토큰 소모 없이 자동 실행되고, 결과 테이블에 점수와 Safe/Warning/Danger 등급 배지가 표시됩니다.
4. 파이프라인이 자동 정지하면 **[2단계(AI 스크리닝) 진행]** 버튼을 눌러야 토큰을 소비하는 Phase 2가 시작됩니다.
5. Phase 2 완료 후 **3단계 검증 대상 선택 모달**(듀얼 패널)이 자동으로 열립니다.
   - 좌측: 전체/대기 명단 (1단계 등급, 1·2단계 점수, 등급, AI 신호 요약 뱃지 포함)
   - 우측: 검증 대상 명단 — 위험군(등급 상/최우선)은 **미리 선택**되어 있음
   - 항목을 **클릭하면 좌↔우로 즉시 이동**하며, **[최종 검증 확정]**을 눌러야만 선택된 학생만 Batch로 LLM에 전송됩니다 (그 전까지 토큰 소모 0).
6. 완료 후 결과 테이블의 [상세보기]에서 LLM 판단 근거(Reasoning), 주장별 모순 판정, 면담 질문을 확인하고 CSV로 내보냅니다.

**작업 이어하기 (State Portability):**

- 진행 상황은 학생 1명 완료 시마다 `session_progress.json`에 자동 저장되며, 서버 재기동 시 자동 복원됩니다.
- 화면 상단의 **세션 파일 표시줄**에 현재 저장 파일명·경로·최종 저장 시각이 항상 표시됩니다.
- 다른 컴퓨터에서 이어가려면: [내보내기]로 파일을 받아 옮긴 뒤 [불러오기]로 업로드하면 됩니다. **파일 이름을 바꿔도** 내용 스키마만 맞으면 복원되고, 이미 완료된 학생은 재분석 시 자동 스킵됩니다(중복 토큰 소모 0). 기존 `screening_summary.csv` 업로드 복구도 그대로 지원합니다.

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

- 지원 형식: **Excel(.xlsx/.xls), CSV, PDF, TXT, DOCX** (웹 UI는 복수 파일 동시 선택 가능)
- **Excel/CSV**: 여러 학생이 행 단위로 들어있는 테이블로 처리 — 학번/이름/도서명/본문 컬럼을 헤더 키워드로 자동 매핑하며, 제목 행이 헤더 위에 있어도 헤더 행을 자동 탐지합니다
- **TXT/DOCX/PDF**: 파일 1개 = 학생 1명. 파일명(확장자 제외)이 학생 식별자이며, `학생이름_책제목` 형식이면 책제목을 자동 파싱합니다
- 도서명이 `도서명(저자명)` 형태이면 저자를 자동 분리해 캐시 키에 활용합니다
- `.txt`는 UTF-8 → CP949 순 인코딩 자동 감지, 빈 셀/결측치(`nan`, `-`, `없음` 등)는 자동 정리
- `.docx`는 편집 시간·작성자 등 메타데이터도 추출해 1단계 판정에 사용합니다

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

이와 별도로 1단계 결과 열에는 rule_score 기준의 **Safe(🟢) / Warning(🟡) / Danger(🔴)** 등급 배지가 표시됩니다 (기본 임계값 20점/45점, `config.yaml`의 `stage1_grade`에서 조정).

## 팩트시트 & 도서 캐시 (book_cache.json)

- 팩트시트는 "메타 정보(저자·출판사) 10% 이내 / **책 내용(줄거리·챕터·인물·개념·결론·인용구) 90% 이상**" 구조로 생성됩니다 (`stages/factsheet_prompt.py`에서 단일 관리).
- `book_cache.json`은 **글로벌 도서 캐시**로, 세션 파일과 분리되어 어떤 사용자의 세션에서도 공유됩니다. 도서명이 캐시에 존재하면 **LLM을 호출하지 않고** 로컬 데이터를 재사용합니다 (저자 미상이어도 도서명 정규화 일치로 캐시를 먼저 탐색).
- `factsheets/` 폴더에 책별 `.md` 파일도 함께 저장되며, 교사가 직접 작성한 팩트시트를 같은 폴더에 두면 우선 적용됩니다.
- 웹 UI의 [로컬 도서 인벤토리] 패널에서 팩트시트 열람·심층 보강이 가능하고, `--no-web` 옵션(CLI) 또는 체크박스(웹)로 자동 생성을 막을 수 있습니다.

## 설정 (config.yaml)

`config.yaml`에서 다음을 조정할 수 있습니다:
- 각 규칙의 가중치 (`weights` — 문장 길이 분산 `sentence_variance`, 어휘 다양성 `lexical_diversity` 포함)
- 1단계 위험도 등급 임계값 (`stage1_grade` — Warning/Danger 기준 점수)
- 각 규칙의 세부 파라미터 (`rules` — CV 임계값, MATTR 임계값·윈도우 등)
- 챗봇 상투구 목록 (`cliche_phrases`)
- 등급 임계값 (`tier`)
- 메타데이터 판정 기준
- API 단가 (비용 추정용)
- 사용 가능 모델 목록 (fallback)

## 비용

실행 종료 시 콘솔에 모델별 토큰 사용량과 예상 비용(USD)이 출력됩니다.

### 비용 절감 전략

- **1단계**: API 미사용 (비용 0) — 로컬 휴리스틱 8종으로 1차 선별
- **2단계**: 경량 모델 사용 (Haiku / Flash / GPT-4o-mini) + 단계 진입 전 사용자 승인 게이트
- **3단계**: 듀얼 패널에서 확정한 대상만 Batch 실행 + 팩트시트/도서 캐시 재사용
- **체크포인트**: 완료된 학생은 `screening_results.jsonl`에 기록되어 재실행 시 자동 스킵 (중복 호출 0)
- **Anthropic 사용 시**: 시스템 프롬프트 캐싱으로 추가 절감 (동일 도서 다수 학생 검증 시 입력 토큰 약 1/10 단가)
- **추가 대안**: SentenceTransformers 등 로컬 임베딩으로 주장-팩트시트 1차 유사도 필터링 시 3단계 입력 토큰 추가 절감 가능 (코드 주석 참고)

## 테스트

```bash
pytest tests/ -v
```

## 라이선스

학교 내부 사용 전용.

---

> 📌 **면책**: 이 도구는 AI 사용 가능성을 기계적으로 선별하는 보조 도구일 뿐입니다. **점수는 증거가 아니며, 최종 판단은 반드시 교사의 구술 면담을 통해 확인해야 합니다.** AI가 작성하지 않은 글도 높은 점수를 받을 수 있고, AI가 작성한 글도 낮은 점수를 받을 수 있습니다.
