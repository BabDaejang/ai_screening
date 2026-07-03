"""1단계: 규칙 기반 AI 사용 의심 점수 산출.

API 호출 없이 텍스트 패턴만으로 점수를 매긴다.
config dict에서 가중치·임계값·패턴 목록을 읽는다.
"""

from __future__ import annotations

import re
import statistics
from typing import Any


# ──────────────────────────────────────────────
# 개별 검사 함수
# ──────────────────────────────────────────────

def check_special_chars(text: str, config: dict) -> dict[str, Any]:
    """특수문자 밀도 검사.

    대상 문자: config.rules.special_chars.targets 에 정의된 문자들.
    밀도 = 등장 횟수 / 전체 글자 수.
    점수 = min(100, density / max_density * 100).
    """
    rules = config.get("rules", {}).get("special_chars", {})
    targets: str = rules.get("targets", "「」『』《》〈〉·—…※")
    max_density: float = rules.get("max_density", 0.03)

    if not text:
        return {"score": 0.0, "evidence": []}

    evidence: list[dict[str, Any]] = []
    total_count = 0

    for ch in set(targets):
        count = text.count(ch)
        if count == 0:
            continue
        total_count += count

        # 해당 문자가 등장하는 문장 전체를 문맥으로 제공
        contexts: list[str] = []
        for m in re.finditer(re.escape(ch), text):
            # 문장 경계 탐색: 마침표·물음표·느낌표·줄바꿈 기준
            start = text.rfind("\n", 0, m.start())
            start = start + 1 if start != -1 else 0
            end = text.find("\n", m.end())
            end = end if end != -1 else len(text)
            sentence = text[start:end].strip()
            if sentence and sentence not in contexts:
                contexts.append(sentence)
        evidence.append({
            "char": ch,
            "count": count,
            "contexts": contexts,
        })

    density = total_count / len(text)
    score = min(100.0, (density / max_density) * 100) if max_density > 0 else 0.0

    return {"score": round(score, 2), "evidence": evidence}


def check_markdown_remnants(text: str, config: dict) -> dict[str, Any]:
    """마크다운 잔재 검출.

    config.rules.markdown_remnants.patterns 의 각 패턴(정규식)에 대해
    MULTILINE 모드로 매치를 찾는다.
    """
    rules = config.get("rules", {}).get("markdown_remnants", {})
    patterns: list[dict] = rules.get("patterns", [])

    evidence: list[dict[str, Any]] = []
    total_matches = 0

    for pat in patterns:
        name = pat.get("name", "unknown")
        regex = pat.get("regex", "")
        description = pat.get("description", "")
        try:
            matches = re.findall(regex, text, re.MULTILINE)
        except re.error:
            matches = []

        count = len(matches)
        if count > 0:
            total_matches += count
            evidence.append({
                "pattern_name": name,
                "description": description,
                "count": count,
                "matched_strings": matches,
            })

    # 점수: 매치 1개당 10점, 최대 100점
    score = min(100.0, total_matches * 10.0)

    return {"score": round(score, 2), "evidence": evidence}


def check_chatbot_phrases(text: str, config: dict) -> dict[str, Any]:
    """챗봇 상투구 검출.

    config.cliche_phrases 목록에서 대소문자 무시로 검색.
    점수 = (발견된 고유 문구 수 / 전체 문구 수) * 100.
    """
    phrases: list[str] = config.get("cliche_phrases", [])
    if not phrases:
        return {"score": 0.0, "evidence": []}

    text_lower = text.lower()
    evidence: list[dict[str, Any]] = []
    found_count = 0

    for phrase in phrases:
        phrase_lower = phrase.lower()
        idx = text_lower.find(phrase_lower)
        if idx == -1:
            continue
        found_count += 1

        # 주변 문맥 추출 (문장 전체)
        contexts: list[str] = []
        search_start = 0
        while True:
            pos = text_lower.find(phrase_lower, search_start)
            if pos == -1:
                break
            line_start = text.rfind("\n", 0, pos)
            line_start = line_start + 1 if line_start != -1 else 0
            line_end = text.find("\n", pos)
            line_end = line_end if line_end != -1 else len(text)
            ctx = text[line_start:line_end].strip()
            if ctx and ctx not in contexts:
                contexts.append(ctx)
            search_start = pos + len(phrase_lower)

        evidence.append({
            "phrase": phrase,
            "contexts": contexts,
        })

    score = (found_count / len(phrases)) * 100.0

    return {"score": round(score, 2), "evidence": evidence}


def check_paste_artifacts(text: str, config: dict) -> dict[str, Any]:
    """복붙 절단 흔적 검사.

    - 문단을 이중 줄바꿈으로 분할.
    - 한국어 조사/어미로 시작하는 문단 검출.
    - 마지막 문단이 문장 중간에 끝나는지 검사.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    if not paragraphs:
        return {"score": 0.0, "evidence": []}

    evidence: list[dict[str, Any]] = []
    findings = 0

    # 조사/어미로 시작하는 문단 검출
    postposition_pattern = re.compile(r"^(는|은|을|를|이|가|에|도|로|의|며|고|다\.)\s")
    for i, para in enumerate(paragraphs):
        if postposition_pattern.match(para):
            findings += 1
            # 문단 앞부분 표시
            preview = para[:80] if len(para) > 80 else para
            evidence.append({
                "type": "조사/어미_시작",
                "paragraph_index": i,
                "preview": preview,
            })

    # 마지막 문단이 문장 중간에 끝나는지 검사
    last_para = paragraphs[-1].rstrip()
    if last_para and not re.search(r"[.!?。]$", last_para):
        findings += 1
        evidence.append({
            "type": "미완성_문장",
            "paragraph_index": len(paragraphs) - 1,
            "preview": last_para,
        })

    score = (findings / len(paragraphs)) * 100.0

    return {"score": round(score, 2), "evidence": evidence}


def check_structural_homogeneity(text: str, config: dict) -> dict[str, Any]:
    """구조 균질성 검사.

    문단 길이의 변동계수(CV = std/mean)가 임계값 미만이면 의심.
    문장 길이 분산도 참고 지표로 포함.
    """
    rules = config.get("rules", {}).get("structural_homogeneity", {})
    cv_threshold: float = rules.get("cv_threshold", 0.25)
    min_paragraphs: int = rules.get("min_paragraphs", 4)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    if len(paragraphs) < min_paragraphs:
        return {
            "score": 0.0,
            "evidence": [{
                "reason": f"문단 수 부족 ({len(paragraphs)}개 < 최소 {min_paragraphs}개)",
            }],
        }

    lengths = [len(p) for p in paragraphs]
    mean_len = statistics.mean(lengths)
    std_len = statistics.stdev(lengths) if len(lengths) > 1 else 0.0
    cv = std_len / mean_len if mean_len > 0 else 0.0

    # 문장 단위 분석
    sentences = re.split(r"[.!?。]\s*", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    sent_lengths = [len(s) for s in sentences]
    sent_mean = statistics.mean(sent_lengths) if sent_lengths else 0.0
    sent_std = statistics.stdev(sent_lengths) if len(sent_lengths) > 1 else 0.0
    sent_cv = sent_std / sent_mean if sent_mean > 0 else 0.0

    if cv < cv_threshold:
        score = (1 - cv / cv_threshold) * 100.0
    else:
        score = 0.0

    evidence = [{
        "paragraph_cv": round(cv, 4),
        "paragraph_mean": round(mean_len, 1),
        "paragraph_std": round(std_len, 1),
        "paragraph_count": len(paragraphs),
        "sentence_cv": round(sent_cv, 4),
        "sentence_mean": round(sent_mean, 1),
        "sentence_std": round(sent_std, 1),
        "sentence_count": len(sentences),
    }]

    return {"score": round(score, 2), "evidence": evidence}


def check_metadata_anomaly(
    metadata: dict | None,
    filename: str,
    config: dict,
    char_count: int = 0,
) -> dict[str, Any]:
    """메타데이터 이상 검사 (docx 전용).

    - metadata가 None이면 '판정 불가' 반환.
    - total_time 존재 시: 글자 수 대비 편집 시간 검사.
    - author와 파일명 학번 비교 (퍼지).
    """
    if metadata is None:
        return {"score": 0.0, "evidence": [{"reason": "판정 불가"}]}

    rules = config.get("rules", {}).get("metadata", {})
    min_edit_time = rules.get("min_edit_time_per_1000_chars", 5)

    evidence: list[dict[str, Any]] = []
    findings = 0

    # 편집 시간 검사
    total_time = metadata.get("total_time_minutes") or metadata.get("total_time")
    actual_char_count = char_count or metadata.get("char_count", 0)
    if total_time is not None and actual_char_count > 0:
        expected_min_time = (actual_char_count / 1000) * min_edit_time
        if total_time < expected_min_time:
            findings += 1
            chars_per_min = actual_char_count / total_time if total_time > 0 else float("inf")
            evidence.append({
                "type": "편집시간_부족",
                "total_time_min": total_time,
                "expected_min_time_min": round(expected_min_time, 1),
                "char_count": actual_char_count,
                "chars_per_min": round(chars_per_min, 1),
            })

    # 작성자-파일명 학번 비교
    author = metadata.get("author", "")
    if author and filename:
        # 파일명에서 숫자(학번) 추출
        file_numbers = re.findall(r"\d{4,}", filename)
        author_numbers = re.findall(r"\d{4,}", author)
        if file_numbers and author:
            # 파일명 학번이 작성자 필드에 포함되지 않으면 의심
            match_found = False
            for fn in file_numbers:
                if fn in author:
                    match_found = True
                    break
                # 부분 매칭 (퍼지): 4자리 이상 숫자의 처음/끝 부분 일치
                for an in author_numbers:
                    overlap = len(set(fn) & set(an))
                    if overlap >= min(len(fn), len(an)) * 0.7:
                        match_found = True
                        break
                if match_found:
                    break

            if not match_found:
                findings += 1
                evidence.append({
                    "type": "작성자_불일치",
                    "filename": filename,
                    "file_numbers": file_numbers,
                    "author": author,
                })

    # 점수 산출: 발견 항목당 50점, 최대 100점
    score = min(100.0, findings * 50.0)

    return {"score": round(score, 2), "evidence": evidence}


# ──────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────

def run_stage1(
    text: str,
    metadata: dict | None,
    filename: str,
    config: dict,
) -> dict[str, Any]:
    """1단계 규칙 기반 검사를 실행하고 가중 합산 점수를 반환한다.

    Args:
        text: 제출물 본문 텍스트.
        metadata: docx 메타데이터 dict 또는 None.
        filename: 원본 파일명.
        config: config.yaml에서 로드된 dict.

    Returns:
        {
            "rule_score": float (0-100),
            "details": {
                "special_chars": {"score": …, "evidence": […]},
                "markdown_remnants": {"score": …, "evidence": […]},
                "chatbot_phrases": {"score": …, "evidence": […]},
                "paste_artifacts": {"score": …, "evidence": […]},
                "structural_homogeneity": {"score": …, "evidence": […]},
                "metadata_anomaly": {"score": …, "evidence": […]},
            }
        }
    """
    weights: dict[str, float] = config.get("weights", {})

    # 각 검사 실행
    details: dict[str, dict[str, Any]] = {
        "special_chars": check_special_chars(text, config),
        "markdown_remnants": check_markdown_remnants(text, config),
        "chatbot_phrases": check_chatbot_phrases(text, config),
        "paste_artifacts": check_paste_artifacts(text, config),
        "structural_homogeneity": check_structural_homogeneity(text, config),
        "metadata_anomaly": check_metadata_anomaly(metadata, filename, config),
    }

    # 가중 합산: sum(score_i * weight_i) / sum(weights)
    weighted_sum = 0.0
    weight_total = 0.0
    for key, result in details.items():
        w = weights.get(key, 0)
        weighted_sum += result["score"] * w
        weight_total += w

    rule_score = (weighted_sum / weight_total) if weight_total > 0 else 0.0
    rule_score = round(min(100.0, max(0.0, rule_score)), 2)

    return {
        "rule_score": rule_score,
        "details": details,
    }
