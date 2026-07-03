"""결과 보고서 생성 모듈.

CSV 내보내기, 학생별 마크다운 보고서, 등급 산출,
콘솔 요약 출력 기능을 제공합니다.
"""

import csv
import logging
import os
from pathlib import Path
from typing import Optional



logger = logging.getLogger(__name__)


# ============================================================
# CSV 생성
# ============================================================

_CSV_COLUMNS = [
    "student",
    "book_title",
    "rule_score",
    "rule_evidence",
    "edit_time_min",
    "ai_score",
    "ai_signals",
    "contradictions",
    "hallucination_score",
    "tier",
    "report",
]


def generate_csv(results: list[dict], output_path: str) -> bool:
    """결과를 UTF-8 BOM CSV 파일로 저장합니다.

    Args:
        results: 학생별 결과 딕셔너리 목록.
        output_path: 출력 CSV 파일 경로.

    Returns:
        성공 여부.
    """
    try:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=_CSV_COLUMNS,
                quoting=csv.QUOTE_ALL,
                extrasaction="ignore",
            )
            writer.writeheader()

            for row in results:
                # 리스트 값을 문자열로 변환
                write_row = {}
                for col in _CSV_COLUMNS:
                    value = row.get(col, "")
                    if isinstance(value, list):
                        value = "; ".join(str(v) for v in value)
                    write_row[col] = value if value is not None else ""
                writer.writerow(write_row)

        logger.info("CSV 저장 완료: %s (%d건)", output_path, len(results))
        return True
    except OSError as e:
        logger.error("CSV 저장 실패: %s", e)
        return False


# ============================================================
# 학생별 마크다운 보고서
# ============================================================

def generate_report(student_data: dict, output_dir: str) -> Optional[str]:
    """학생별 상세 보고서를 마크다운으로 생성합니다.

    Args:
        student_data: 학생 결과 딕셔너리 (전 단계 정보 포함).
        output_dir: 보고서 저장 디렉토리.

    Returns:
        생성된 파일 경로, 실패 시 None.
    """
    student = student_data.get("student", "unknown")
    reports_dir = Path(output_dir)

    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("보고서 디렉토리 생성 실패: %s", e)
        return None

    file_path = reports_dir / f"{student}.md"

    # 데이터 추출 (안전하게 기본값 제공, stage2/stage3 중첩 구조 지원)
    stage2 = student_data.get("stage2", {})
    stage3 = student_data.get("stage3", {})

    book_title = stage2.get("book_title") or student_data.get("book_title", "미상")
    tier = student_data.get("tier", "-")
    rule_score = student_data.get("rule_score", "-")
    ai_score = student_data.get("ai_score", "-")
    hallucination_score = stage3.get("hallucination_score") or student_data.get("hallucination_score", "-")
    edit_time = student_data.get("edit_time_min", "-")
    text = student_data.get("text", "")

    # 1단계 근거: rule_details에서 추출
    rule_details = student_data.get("rule_details", {})
    rule_evidence = []
    for check_name, detail in rule_details.items():
        if detail.get("score", 0) > 0:
            rule_evidence.append(f"[{check_name}] 점수={detail['score']:.1f}, 근거: {detail.get('evidence', [])}")

    ai_signals = stage2.get("signals") or student_data.get("ai_signals", [])
    ai_rationale = stage2.get("rationale") or student_data.get("ai_rationale", "")
    claims = stage3.get("claims") or student_data.get("stage3_claims", [])
    interview_questions = stage3.get("interview_questions") or student_data.get("interview_questions", [])

    # 마크다운 조립
    lines = [
        f"# 📝 AI 사용 의심 선별 보고서 — {student}",
        "",
        f"- **도서명**: {book_title or '미상'}",
        f"- **등급**: {tier}",
        f"- **규칙 점수**: {rule_score}",
        f"- **AI 점수**: {ai_score}",
        f"- **할루시네이션 점수**: {hallucination_score}",
        f"- **편집 시간(분)**: {edit_time}",
        "",
        "---",
        "",
        "## 1단계: 규칙 기반 검사 결과",
        "",
    ]

    if rule_evidence:
        for ev in rule_evidence:
            lines.append(f"- {ev}")
    else:
        lines.append("- (검출된 증거 없음)")

    lines += [
        "",
        "---",
        "",
        "## 2단계: AI 스크리닝 결과",
        "",
        "### 감지 신호",
        "",
    ]

    if ai_signals:
        for sig in ai_signals:
            lines.append(f"- {sig}")
    else:
        lines.append("- (감지된 신호 없음)")

    lines += [
        "",
        "### 판단 근거",
        "",
        ai_rationale if ai_rationale else "(근거 없음)",
        "",
        "---",
        "",
        "## 3단계: 사실 검증 결과",
        "",
    ]

    # 주장 판정 테이블
    if claims:
        lines.append("| 주장 | 판정 | 설명 | 팩트시트 근거 |")
        lines.append("|------|------|------|---------------|")
        for claim in claims:
            c_text = claim.get("claim", "")
            verdict = claim.get("verdict", "")
            explanation = claim.get("explanation", "")
            basis = claim.get("factsheet_basis", "") or ""
            # 테이블 셀 내 파이프 이스케이프
            c_text = c_text.replace("|", "\\|")
            explanation = explanation.replace("|", "\\|")
            basis = basis.replace("|", "\\|")
            lines.append(f"| {c_text} | {verdict} | {explanation} | {basis} |")
    else:
        lines.append("(사실 검증 데이터 없음)")

    lines += [
        "",
        "---",
        "",
        "## 📌 면담 확인 질문",
        "",
    ]

    if interview_questions:
        for i, q in enumerate(interview_questions, 1):
            lines.append(f"{i}. {q}")
    else:
        lines.append("(면담 질문 없음)")

    lines += [
        "",
        "---",
        "",
        "## 원문 (제출물 전문)",
        "",
        "```",
        text,
        "```",
        "",
    ]

    content = "\n".join(lines)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("보고서 생성: %s", file_path)
        return str(file_path)
    except OSError as e:
        logger.error("보고서 저장 실패 (%s): %s", file_path, e)
        return None


# ============================================================
# 등급 산출
# ============================================================

def calculate_tiers(results: list[dict], threshold_percentile: int = 30) -> list[dict]:
    """결과 목록에 등급(tier)을 부여합니다.

    - rule_score AND ai_score 모두 상위 N% → '상'
    - 둘 중 하나만 → '중'
    - 둘 다 아닌 경우 → '하'
    - 모순(contradiction) 발견 → '최우선' (최고 우선 등급, 위 등급 무시)

    Args:
        results: 학생별 결과 목록 (rule_score, ai_score, contradictions 필요).
        threshold_percentile: 상위 백분위 기준 (기본 30).

    Returns:
        tier 필드가 추가된 결과 목록 (원본 수정).
    """
    if not results:
        return results

    # 점수 배열 구성 (결측값은 0으로 처리, 'ERROR'도 0으로)
    rule_scores = []
    ai_scores = []
    for r in results:
        rs = r.get("rule_score", 0)
        ais = r.get("ai_score", 0)
        rule_scores.append(float(rs) if isinstance(rs, (int, float)) else 0.0)
        ai_scores.append(float(ais) if isinstance(ais, (int, float)) else 0.0)

    # 순수 Python 백분위 계산
    def percentile(data: list[float], pct: float) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (pct / 100.0) * (len(sorted_data) - 1)
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        d = k - f
        return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])

    # 상위 N% 기준값 (percentile은 "이하" 비율이므로 100-N으로 변환)
    rule_threshold = percentile(rule_scores, 100 - threshold_percentile)
    ai_threshold = percentile(ai_scores, 100 - threshold_percentile)

    for i, r in enumerate(results):
        rule_high = rule_scores[i] >= rule_threshold
        ai_high = ai_scores[i] >= ai_threshold

        # 모순 검사
        contradictions = r.get("contradictions", 0)
        has_contradiction = isinstance(contradictions, int) and contradictions > 0

        if has_contradiction:
            r["tier"] = "최우선"
        elif rule_high and ai_high:
            r["tier"] = "상"
        elif rule_high or ai_high:
            r["tier"] = "중"
        else:
            r["tier"] = "하"

    return results


# ============================================================
# 콘솔 요약 출력
# ============================================================

def print_console_summary(results: list[dict]) -> None:
    """'최우선'과 '상' 등급 학생만 콘솔에 요약 출력합니다."""
    priority_tiers = {"최우선", "상"}
    filtered = [r for r in results if r.get("tier") in priority_tiers]

    if not filtered:
        print("\n✅ 주의 대상 학생이 없습니다.")
        return

    # 최우선 먼저, 그 다음 상
    tier_order = {"최우선": 0, "상": 1}
    filtered.sort(key=lambda x: (tier_order.get(x.get("tier", ""), 99), x.get("student", "")))

    print("\n" + "=" * 70)
    print("  ⚠️  주의 대상 학생 요약")
    print("=" * 70)

    print(f"\n  {'학생':<15} {'등급':<8} {'규칙':>6} {'AI':>6} {'할루':>6}  주요 증거")
    print("  " + "-" * 65)

    for r in filtered:
        student = r.get("student", "?")
        tier = r.get("tier", "-")
        rule = r.get("rule_score", "-")
        ai = r.get("ai_score", "-")
        hall = r.get("hallucination_score", "-")

        # 주요 증거 요약 (첫 2개)
        evidence_items = []
        for ev in (r.get("rule_evidence") or [])[:1]:
            evidence_items.append(str(ev))
        for sig in (r.get("ai_signals") or [])[:1]:
            evidence_items.append(str(sig))
        evidence_str = "; ".join(evidence_items) if evidence_items else "-"

        # 긴 증거는 잘라내기
        if len(evidence_str) > 45:
            evidence_str = evidence_str[:42] + "..."

        tier_emoji = "🔴" if tier == "최우선" else "🟡"
        print(f"  {student:<15} {tier_emoji}{tier:<7} {rule:>6} {ai:>6} {hall:>6}  {evidence_str}")

    print("\n  " + "-" * 65)
    total = len(results)
    priority_count = len(filtered)
    print(f"  전체 {total}명 중 주의 대상 {priority_count}명")
    print("=" * 70 + "\n")
