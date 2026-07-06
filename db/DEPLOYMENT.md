# 클라우드 마이그레이션 배포 가이드 (Vercel + Supabase)

로컬 CLI/파일 기반 도구를 다중 사용자 웹 서비스로 전환한 뒤의 배포 절차입니다.

## 아키텍처 요약

| 구버전 (로컬 파일) | 신버전 (클라우드) |
|---|---|
| `~/.ai_screening/profiles.yaml` (프로필명만, 비밀번호 없음) | `users` 테이블 — username + **bcrypt 해시 비밀번호** |
| `.env`의 평문 LLM API 키 | `users.encrypted_api_keys` — **Fernet(AES) 암호화** 저장, 호출 직전 복호화 |
| `data/projects/{profile}/{id}/session.json` | `projects` 테이블 (세션 스냅샷 jsonb) |
| `{project}/screening_results.jsonl` (체크포인트) | `checkpoints` 테이블 (학생 단위 upsert) |
| `book_cache.json` + `factsheets/*.md` | `factsheets` 테이블 (글로벌 공유 캐시) |
| 서버 메모리 "현재 로그인 프로필" | **무상태 Bearer 토큰** (Fernet 암호화 + TTL 12h) |

- 리포트/CSV 등 파생 산출물만 임시 디렉토리(`tempfile.gettempdir()`)에 생성됩니다 (Vercel `/tmp` 호환).
- 분석 로직(stage1/2/3)은 변경되지 않았습니다.

## 1. Supabase 설정 (1회)

1. Supabase 프로젝트(`https://pqzcviurfjzsgkmaprqe.supabase.co`) 대시보드 → **SQL Editor**
2. [`db/schema.sql`](schema.sql) 전체를 붙여넣고 실행 (users/projects/checkpoints/factsheets 생성 + RLS 잠금)
3. **Settings → API**에서 `service_role` 키를 복사 (anon 키 아님 — 서버 전용, 절대 클라이언트 노출 금지)

## 2. 환경 변수

`.env.example`을 참고하여 설정합니다.

| 변수 | 설명 |
|---|---|
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_ROLE_KEY` | service_role 키 |
| `ENCRYPTION_KEY` | Fernet 마스터 키 — API 키 암호화 + 세션 토큰 서명에 사용 |
| `AUTH_TOKEN_TTL_SECONDS` | (선택) 로그인 토큰 유효기간, 기본 43200초 |
| `NAVER_CLIENT_ID/SECRET` | (선택) 저자 자동 확정용 서버 공용 키 |

`ENCRYPTION_KEY` 생성:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> ⚠️ `ENCRYPTION_KEY`를 교체하면 기존에 암호화 저장된 모든 API 키를 복호화할 수 없게 됩니다
> (사용자가 키를 재등록해야 함). 로그인 세션도 전부 무효화됩니다.

- **로컬**: 프로젝트 루트 `.env`
- **Vercel**: Project → Settings → Environment Variables (Production/Preview 모두)

## 3. Vercel 배포

`vercel.json`이 `app.py`(FastAPI ASGI)를 `@vercel/python` 런타임으로 빌드합니다.

```bash
vercel deploy --prod
```

## 4. 로컬 실행

```bash
pip install -r requirements.txt
python app.py                    # 웹 대시보드 (http://localhost:8000)

python screen.py register        # CLI 회원가입
python screen.py login           # CLI 로그인 (토큰: ~/.ai_screening/cli_token)
python screen.py ./submissions/  # 분석 실행
```

## 5. 알려진 서버리스 제약 (로컬 전용 기능)

Vercel 서버리스 환경에서는 아래 기능이 동작하지 않거나 제한됩니다:

- **`/api/pick-folder`, `/api/pick-file`, `/api/data/import`(경로 기반)**: 서버 로컬 파일시스템/tkinter에
  의존하므로 클라우드에서는 사용 불가. 클라우드에서는 CSV 업로드(`/api/import`)·세션 업로드·학생 수동
  추가를 사용하세요.
- **장시간 분석 파이프라인**: 백그라운드 스레드 + 단계 게이트(수 분~수십 분 대기) 구조는 서버리스
  함수의 실행 시간 제한(기본 10~60초, Pro 최대 수분)을 초과할 수 있습니다. 대규모 배치 분석은
  로컬 실행(`python app.py` 또는 CLI)을 권장하며, 완전한 클라우드 전환에는 파이프라인의
  작업 큐(예: Supabase Queue, Inngest, QStash) 분리가 추가로 필요합니다.
- **모델 목록 캐시(`models_cache.json`)**: 클라우드에서는 파일 쓰기가 실패해도 무해하게 무시되고
  인스턴스 메모리 캐시 + `config.yaml`의 fallback_models로 동작합니다.

## 6. 구버전 데이터 이관

- 로컬에 구버전 `session_progress.json`이 남아 있으면, 로그인 후 프로젝트 대시보드 최초 조회 시
  자동으로 DB 프로젝트로 1회 이관됩니다 (`.migrated`로 백업됨).
- 구 `profiles.yaml`의 프로필은 비밀번호가 없었으므로 자동 이관하지 않습니다 — 각 사용자가
  회원가입 후 API 키를 다시 등록해야 합니다 (보안상 의도된 동작).
