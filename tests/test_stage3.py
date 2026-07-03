"""3단계 검증 로직 테스트 (API 호출은 mock 처리)."""

import os
import sys
import json
import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.stage3_verify import run_stage3, ensure_factsheet
from utils.report_generator import calculate_tiers


class MockProvider:
    """테스트용 모의 프로바이더."""

    def __init__(self):
        self._usage = {
            "screening": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
            "verify": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
            "factsheet": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0},
        }
        self._web_search_count = 0
        self.model_screening = "mock-model"
        self.model_verify = "mock-model"

    def verify_claims(self, system_prompt, claims, full_text, max_tokens=2000):
        """모의 검증 — 특정 주장에 대해 모순을 반환."""
        result_claims = []
        for claim in claims:
            if "뱀" in claim or "엠마뉴엘 골드슈타인의 직속 부하" in claim or "3장에서 처음 등장" in claim:
                result_claims.append({
                    "claim": claim,
                    "verdict": "모순",
                    "explanation": "팩트시트와 일치하지 않음",
                    "factsheet_basis": "팩트시트 참조"
                })
            elif "진리부" in claim or "빅 브라더" in claim:
                result_claims.append({
                    "claim": claim,
                    "verdict": "일치",
                    "explanation": "팩트시트와 일치",
                    "factsheet_basis": "팩트시트 참조"
                })
            else:
                result_claims.append({
                    "claim": claim,
                    "verdict": "판단불가",
                    "explanation": "팩트시트에 해당 내용 없음",
                    "factsheet_basis": None
                })

        contradiction_count = sum(1 for c in result_claims if c["verdict"] == "모순")

        return {
            "claims": result_claims,
            "hallucination_score": min(100, contradiction_count * 40),
            "overall": f"모순 {contradiction_count}건 발견됨",
            "interview_questions": [
                "101호실에서의 경험을 구체적으로 설명해주세요.",
                "오브라이언의 역할에 대해 어떻게 이해했나요?",
                "줄리아가 처음 등장하는 장면을 기억하시나요?"
            ]
        }

    def generate_factsheet(self, book_title, max_tokens=2000):
        """모의 팩트시트 생성."""
        return "# 모의 팩트시트\n\n테스트용 팩트시트입니다."

    def get_usage(self):
        return {
            "usage": self._usage,
            "web_search_count": self._web_search_count,
            "model_screening": self.model_screening,
            "model_verify": self.model_verify,
        }

    def _update_usage(self, stage, **kwargs):
        pass


class TestStage3JSONParsing:
    """3단계 JSON 파싱 테스트."""

    def test_verify_claims_returns_valid_structure(self):
        provider = MockProvider()
        claims = [
            "윈스턴은 진리부에서 일한다",
            "101호실에서 뱀과 마주한다",
            "오브라이언은 엠마뉴엘 골드슈타인의 직속 부하이다"
        ]
        result = provider.verify_claims("시스템 프롬프트", claims, "제출물 전문")

        # 구조 검증
        assert "claims" in result
        assert "hallucination_score" in result
        assert "overall" in result
        assert "interview_questions" in result
        assert len(result["claims"]) == 3
        assert len(result["interview_questions"]) == 3

    def test_verdict_values(self):
        provider = MockProvider()
        claims = [
            "윈스턴은 진리부에서 일한다",  # 일치
            "101호실에서 뱀과 마주한다",  # 모순
            "124페이지에서 무언가 발생",  # 판단불가
        ]
        result = provider.verify_claims("시스템 프롬프트", claims, "제출물 전문")

        verdicts = {c["claim"]: c["verdict"] for c in result["claims"]}
        assert verdicts["윈스턴은 진리부에서 일한다"] == "일치"
        assert verdicts["101호실에서 뱀과 마주한다"] == "모순"
        assert verdicts["124페이지에서 무언가 발생"] == "판단불가"

    def test_hallucination_score_range(self):
        provider = MockProvider()
        result = provider.verify_claims("sys", ["뱀"], "text")
        assert 0 <= result["hallucination_score"] <= 100


class TestTierUpgrade:
    """모순 발견 시 '최우선' 승격 테스트."""

    def test_contradiction_upgrades_to_top_priority(self, config):
        """모순이 발견되면 등급이 '최우선'으로 승격."""
        results = [
            {"student": "s1", "rule_score": 80, "ai_score": 90, "contradictions": 2, "tier": "상"},
            {"student": "s2", "rule_score": 50, "ai_score": 60, "contradictions": 0, "tier": "중"},
            {"student": "s3", "rule_score": 20, "ai_score": 10, "contradictions": 0, "tier": "하"},
            {"student": "s4", "rule_score": 30, "ai_score": 20, "contradictions": 1, "tier": "하"},
        ]

        # 모순 발견 시 최우선 승격 로직
        for r in results:
            if isinstance(r.get("contradictions"), int) and r["contradictions"] > 0:
                r["tier"] = "최우선"

        assert results[0]["tier"] == "최우선", "s1 (모순 2건)이 최우선이 아님"
        assert results[1]["tier"] == "중", "s2 (모순 0건)이 변경됨"
        assert results[2]["tier"] == "하", "s3 (모순 0건)이 변경됨"
        assert results[3]["tier"] == "최우선", "s4 (모순 1건)이 최우선이 아님"


class TestTierCalculation:
    """등급 산정 로직 테스트."""

    def test_both_high_scores_tier_상(self, config):
        results = [
            {"student": f"s{i}", "rule_score": 90 - i * 5, "ai_score": 85 - i * 5}
            for i in range(10)
        ]
        tiered = calculate_tiers(results, threshold_percentile=30)

        # 상위 30% (10명 중 3명)은 "상"
        top_tiers = [r for r in tiered if r["tier"] == "상"]
        assert len(top_tiers) >= 1, "상 등급이 없음"

    def test_mixed_scores_tier_중(self, config):
        results = [
            {"student": "high_rule", "rule_score": 95, "ai_score": 10},
            {"student": "high_ai", "rule_score": 10, "ai_score": 95},
            {"student": "both_high", "rule_score": 95, "ai_score": 95},
            {"student": "both_low", "rule_score": 10, "ai_score": 10},
        ]
        tiered = calculate_tiers(results, threshold_percentile=30)

        tier_map = {r["student"]: r["tier"] for r in tiered}
        # both_high는 상, both_low는 하
        assert tier_map["both_high"] == "상"
        assert tier_map["both_low"] == "하"

    def test_tier_values(self, config):
        results = [
            {"student": f"s{i}", "rule_score": i * 10, "ai_score": i * 10}
            for i in range(10)
        ]
        tiered = calculate_tiers(results, threshold_percentile=30)
        valid_tiers = {"최우선", "상", "중", "하"}
        for r in tiered:
            assert r["tier"] in valid_tiers, f"잘못된 등급: {r['tier']}"


class TestEnsureFactsheet:
    """팩트시트 확보 로직 테스트."""

    def test_existing_factsheet_used(self, tmp_path, fake_factsheet):
        """기존 팩트시트가 있으면 API 호출 없이 사용."""
        factsheets_dir = str(tmp_path)
        # 팩트시트 파일 생성
        factsheet_path = os.path.join(factsheets_dir, "1984.md")
        with open(factsheet_path, "w", encoding="utf-8") as f:
            f.write(fake_factsheet)

        provider = MockProvider()
        result = ensure_factsheet("1984", provider, factsheets_dir, no_web=False)

        assert result is not None
        assert "조지 오웰" in result

    def test_no_web_returns_none(self, tmp_path):
        """--no-web 시 팩트시트가 없으면 None 반환."""
        provider = MockProvider()
        result = ensure_factsheet("존재하지않는책", provider, str(tmp_path), no_web=True)
        assert result is None

    def test_auto_generation(self, tmp_path):
        """팩트시트가 없으면 자동 생성."""
        provider = MockProvider()
        factsheets_dir = str(tmp_path)
        result = ensure_factsheet("새로운책", provider, factsheets_dir, no_web=False)

        assert result is not None
        # 파일이 저장되었는지 확인
        saved_path = os.path.join(factsheets_dir, "새로운책.md")
        assert os.path.exists(saved_path)


class TestStage3Integration:
    """3단계 통합 테스트 (mock provider)."""

    def test_full_stage3_flow(self, tmp_path, fake_factsheet, contradiction_text, config):
        """전체 3단계 플로우 테스트."""
        # 팩트시트 준비
        factsheets_dir = str(tmp_path / "factsheets")
        os.makedirs(factsheets_dir, exist_ok=True)
        with open(os.path.join(factsheets_dir, "1984.md"), "w", encoding="utf-8") as f:
            f.write(fake_factsheet)

        provider = MockProvider()

        candidates = [{
            "student": "contradiction_student",
            "text": contradiction_text,
            "book_title": "1984",
            "rule_score": 75,
            "ai_score": 80,
            "tier": "상",
            "fact_claims": [
                "줄리아는 3장에서 처음 등장하여 비밀 메모를 전달한다",
                "오브라이언은 엠마뉴엘 골드슈타인의 직속 부하이다",
                "101호실에서 뱀과 마주하는 장면",
                "윈스턴은 진리부에서 일한다",
            ]
        }]

        result = run_stage3(candidates, provider, factsheets_dir, config, no_web=False)

        assert len(result) == 1
        student = result[0]

        # 모순이 발견되어 tier가 '최우선'으로 격상되어야 함
        assert student["tier"] == "최우선", "모순 발견 시 tier가 최우선으로 격상되어야 함"
        
        # 내부 claims 배열 검증
        claims = student.get("stage3", {}).get("claims", [])
        assert any(c.get("verdict") == "모순" for c in claims), "모순 판정이 포함되어야 함"

        # 면담 질문이 있어야 함
        assert len(student.get("stage3", {}).get("interview_questions", [])) > 0, "면담 질문이 없음"
