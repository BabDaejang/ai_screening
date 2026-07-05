"""book_cache.json의 '도서명(저자명)' 미분리 레거시 항목을 정리하는 1회성 마이그레이션 스크립트."""
import io
import json
import os
import re
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "book_cache.json")
FACTSHEETS_DIR = os.path.join(BASE_DIR, "factsheets")

_TITLE_AUTHOR_PATTERN = re.compile(r'^(.+?)\s*[\(\[](.+?)[\)\]]$')


def parse_book_title_author(raw_title):
    if not raw_title:
        return "", None
    cleaned = raw_title.strip()
    if not cleaned:
        return "", None
    match = _TITLE_AUTHOR_PATTERN.match(cleaned)
    if match:
        title_part = match.group(1).strip()
        author_part = match.group(2).strip()
        if title_part and author_part:
            return title_part, author_part
    return cleaned, None


def normalize_cache_key(title, author):
    cleaned_title = re.sub(r'[\s\\/:*?"<>|]', '', title).strip()
    cleaned_author = re.sub(r'[\s\\/:*?"<>|]', '', author).strip()
    return f"{cleaned_title}_{cleaned_author}"


def normalize_title_for_file(title):
    import unicodedata
    normalized = unicodedata.normalize("NFC", title)
    normalized = re.sub(r"[^\w가-힣a-zA-Z0-9]", "", normalized)
    return normalized.lower()


with open(CACHE_PATH, "r", encoding="utf-8") as f:
    book_cache = json.load(f)

print(f"원본 항목 수: {len(book_cache)}")

# 안전을 위한 백업
backup_path = os.path.join(BASE_DIR, f"book_cache.json.bak.{time.strftime('%Y%m%d_%H%M%S')}")
shutil.copy2(CACHE_PATH, backup_path)
print(f"백업 생성: {backup_path}")

new_cache = {}
renamed = []
skipped_collision = []
unchanged = 0

for cache_key, entry in book_cache.items():
    book_title_raw = entry.get("book_title", "") or ""
    author_raw = (entry.get("author") or "").strip()

    is_broken = (not author_raw or author_raw.lower() == "unknown")
    if is_broken:
        parsed_title, parsed_author = parse_book_title_author(book_title_raw)
        if parsed_author:
            new_key = normalize_cache_key(parsed_title, parsed_author)
            if new_key in new_cache or new_key in book_cache:
                # 이미 올바른 항목이 존재하면 깨진 항목은 버리고 기존 항목을 보존한다.
                skipped_collision.append((cache_key, new_key))
                continue

            entry["book_title"] = parsed_title
            entry["author"] = parsed_author
            new_cache[new_key] = entry
            renamed.append((cache_key, new_key, parsed_title, parsed_author))

            # factsheets/*.md 파일명도 도서명 기준으로 정규화되므로, 제목이 바뀌어도
            # 정규화 결과(공백/특수문자 제거 후 소문자)가 동일하면 파일 그대로 재사용된다.
            continue

    new_cache[cache_key] = entry
    unchanged += 1

with open(CACHE_PATH, "w", encoding="utf-8") as f:
    json.dump(new_cache, f, ensure_ascii=False, indent=4)
    f.flush()
    os.fsync(f.fileno())

print(f"\n정리 완료: 총 {len(new_cache)}개 항목 (변경 없음 {unchanged}개, 재분리 {len(renamed)}개, 충돌로 스킵 {len(skipped_collision)}개)\n")

for old_key, new_key, title, author in renamed:
    print(f"  [재분리] '{old_key}' -> '{new_key}'  (도서명='{title}', 저자='{author}')")

for old_key, new_key in skipped_collision:
    print(f"  [스킵-충돌] '{old_key}' -> 이미 존재하는 '{new_key}'와 충돌하여 깨진 항목 제거")
