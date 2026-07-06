-- =============================================================
-- AI 사용 의심 선별·검증 도구 — Supabase (PostgreSQL) 스키마
--
-- 적용 방법: Supabase 대시보드 → SQL Editor 에서 이 파일 전체를 실행.
-- 서버(FastAPI)는 SERVICE_ROLE 키로만 접근하므로 RLS는 전부 잠금(deny-all)
-- 상태로 활성화한다 (anon 키로는 어떤 행도 읽을 수 없음).
-- =============================================================

create extension if not exists pgcrypto;

-- -------------------------------------------------------------
-- 1. 사용자 계정 (구 ~/.ai_screening/profiles.yaml 대체)
--    - hashed_password    : passlib(bcrypt) 단방향 해시
--    - encrypted_api_keys : {"gemini": "<fernet token>", "anthropic": ...}
--                           Fernet(AES-128-CBC + HMAC) 암호문. 마스터 키는
--                           환경 변수 ENCRYPTION_KEY (Vercel Secrets).
--    - default_models     : {"screening_provider": .., "screening_model": ..,
--                            "verify_provider": .., "verify_model": ..}
-- -------------------------------------------------------------
create table if not exists users (
    id                 uuid primary key default gen_random_uuid(),
    username           text unique not null,
    hashed_password    text not null,
    encrypted_api_keys jsonb not null default '{}'::jsonb,
    default_models     jsonb not null default '{}'::jsonb,
    created_at         timestamptz not null default now()
);

-- -------------------------------------------------------------
-- 2. 프로젝트 + 세션 스냅샷 (구 data/projects/{profile}/{id}/session.json 대체)
--    세션 파일과 프로젝트는 1:1 관계였으므로 한 테이블로 병합한다.
--    results 는 기존 session.json 의 results 배열을 그대로 담는다.
-- -------------------------------------------------------------
create table if not exists projects (
    id           text not null,                    -- 'YYYYMMDD_HHMMSS_xxxxxx'
    user_id      uuid not null references users(id) on delete cascade,
    name         text not null default '',
    status       text not null default 'created',  -- created/loaded/running/completed/...
    created_at   text not null default '',         -- 'YYYY-MM-DD HH:MM:SS' (기존 포맷 유지)
    saved_at     text not null default '',
    cost_summary jsonb not null default '{}'::jsonb,
    results      jsonb not null default '[]'::jsonb,
    primary key (user_id, id)
);

create index if not exists idx_projects_user on projects (user_id, created_at desc);

-- -------------------------------------------------------------
-- 3. 체크포인트 (구 {project}/screening_results.jsonl 대체)
--    학생 1명(Atomic Unit) 처리 완료 시마다 upsert — 재실행 시 Resume 엔진이
--    이 테이블을 조회하여 중복 API 호출(토큰 낭비)을 차단한다.
-- -------------------------------------------------------------
create table if not exists checkpoints (
    user_id    uuid not null references users(id) on delete cascade,
    project_id text not null,
    student    text not null,                      -- '학번_이름' 복합키
    record     jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    primary key (user_id, project_id, student)
);

-- -------------------------------------------------------------
-- 4. 도서 팩트시트 캐시 (구 book_cache.json + factsheets/*.md 대체)
--    여러 사용자·프로젝트가 공유하는 글로벌 자산 (Cache Hit 시 토큰 0).
-- -------------------------------------------------------------
create table if not exists factsheets (
    cache_key   text primary key,                  -- normalize_cache_key(도서명, 저자)
    book_title  text not null default '',
    author      text not null default '',
    factsheet   text not null default '',          -- 마크다운 본문
    is_enriched boolean not null default false,
    updated_at  text not null default ''           -- 'YYYY-MM-DD HH:MM:SS' (기존 포맷 유지)
);

-- -------------------------------------------------------------
-- RLS: 전 테이블 잠금. 서버는 service_role 키를 사용하므로 RLS를 우회한다.
-- anon/authenticated 역할용 정책은 의도적으로 만들지 않는다 (deny-all).
-- -------------------------------------------------------------
alter table users       enable row level security;
alter table projects    enable row level security;
alter table checkpoints enable row level security;
alter table factsheets  enable row level security;
