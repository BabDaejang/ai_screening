"""1단계 규칙 기반 점수 테스트."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stages.stage1_rules import (
    run_stage1,
    check_special_chars,
    check_markdown_remnants,
    check_chatbot_phrases,
    check_paste_artifacts,
    check_structural_homogeneity,
)


class TestNormalStudent:
    """정상 글 — 낮은 rule_score."""

    def test_low_total_score(self, normal_text, config):
        result = run_stage1(normal_text, None, "normal_student", config)
        assert result["rule_score"] < 30, f"정상 글의 rule_score가 너무 높음: {result['rule_score']}"

    def test_no_markdown_detection(self, normal_text, config):
        result = check_markdown_remnants(normal_text, config)
        assert result["score"] < 10, "정상 글에서 마크다운이 검출됨"

    def test_no_chatbot_phrases(self, normal_text, config):
        result = check_chatbot_phrases(normal_text, config)
        assert result["score"] < 20, "정상 글에서 상투구가 많이 검출됨"


class TestMarkdownStudent:
    """마크다운 잔재 포함 글 — 항목 2 검출."""

    def test_markdown_detection(self, markdown_text, config):
        result = check_markdown_remnants(markdown_text, config)
        assert result["score"] > 50, f"마크다운 잔재 점수가 너무 낮음: {result['score']}"

    def test_evidence_includes_patterns(self, markdown_text, config):
        result = check_markdown_remnants(markdown_text, config)
        evidence = result["evidence"]
        assert len(evidence) > 0, "마크다운 검출 근거가 없음"

        # 볼드, 헤딩, 목록 중 최소 2가지 이상 검출되어야 함
        pattern_names = {e["pattern_name"] for e in evidence}
        expected_patterns = {"bold_markers", "heading_markers", "unordered_list", "ordered_list"}
        found = pattern_names & expected_patterns
        assert len(found) >= 2, f"검출된 패턴이 부족: {found}"

    def test_higher_total_score(self, markdown_text, config):
        result = run_stage1(markdown_text, None, "markdown_student", config)
        assert result["rule_score"] > 20, f"마크다운 글의 총점이 너무 낮음: {result['rule_score']}"


class TestChatbotStudent:
    """상투구 포함 글 — 항목 3 검출."""

    def test_chatbot_phrase_detection(self, chatbot_text, config):
        result = check_chatbot_phrases(chatbot_text, config)
        assert result["score"] > 50, f"상투구 점수가 너무 낮음: {result['score']}"

    def test_evidence_includes_phrases(self, chatbot_text, config):
        result = check_chatbot_phrases(chatbot_text, config)
        evidence = result["evidence"]
        assert len(evidence) >= 3, f"검출된 상투구가 부족: {len(evidence)}"

        # 실제 발견된 문구 확인
        found_phrases = {e["phrase"] for e in evidence}
        expected = {"물론입니다", "도움이 되었기를", "요약하자면"}
        overlap = found_phrases & expected
        assert len(overlap) >= 2, f"주요 상투구 미검출: found={found_phrases}"

    def test_higher_total_score(self, chatbot_text, config):
        result = run_stage1(chatbot_text, None, "chatbot_student", config)
        assert result["rule_score"] > 20, f"상투구 글의 총점이 너무 낮음: {result['rule_score']}"


class TestSpecialChars:
    """특수문자 밀도 테스트."""

    def test_text_with_special_chars(self, config):
        text = "이 책의 『제목』은 《특별한 이야기》이며, 「1장」에서 시작된다. 주요 내용은 다음과 같다··· 결론은—이렇다."
        result = check_special_chars(text, config)
        assert result["score"] > 0, "특수문자가 포함된 텍스트에서 점수가 0"

    def test_normal_text_low_score(self, config):
        text = "이것은 일반적인 글입니다. 특수문자가 거의 없는 평범한 문장들로 이루어져 있습니다."
        result = check_special_chars(text, config)
        assert result["score"] < 10, "일반 텍스트의 특수문자 점수가 높음"


class TestPasteArtifacts:
    """복붙 절단 흔적 테스트."""

    def test_paste_detection(self, config):
        text = "는 매우 인상적이었다. 이 부분에서 주인공의 심리가 잘 드러났다.\n\n을 통해 작가의 의도를 파악할 수 있었다.\n\n이 소설의 결론은"
        result = check_paste_artifacts(text, config)
        assert result["score"] > 0, "복붙 절단 흔적이 검출되지 않음"


class TestStructuralHomogeneity:
    """구조 균질성 테스트."""

    def test_uniform_paragraphs(self, config):
        # 균질한 문단 (같은 길이)
        para = "이것은 테스트 문장입니다. 대략 비슷한 길이의 문장들로 구성되어 있습니다."
        text = "\n\n".join([para] * 6)
        result = check_structural_homogeneity(text, config)
        assert result["score"] > 50, "균질한 문단의 점수가 낮음"

    def test_varied_paragraphs(self, config):
        # 다양한 길이의 문단
        text = "짧은 문단.\n\n이것은 좀 더 긴 문단입니다. 여러 문장이 포함되어 있고, 다양한 내용을 담고 있습니다. 문단의 길이가 일정하지 않아서 자연스러운 글쓰기 패턴을 보여줍니다.\n\n중간 길이.\n\n아주 긴 문단은 여러 생각을 담고 있습니다. 이런 문단은 보통 학생들이 자유롭게 쓸 때 나타나는 패턴입니다. 특정 주제에 대해 열정적으로 쓰다 보면 자연스럽게 길어지게 됩니다. 반면 다른 문단은 간결하게 핵심만 전달합니다.\n\n끝."
        result = check_structural_homogeneity(text, config)
        assert result["score"] < 30, "다양한 문단의 균질성 점수가 높음"


class TestMetadataAnomaly:
    """메타데이터 이상 검사 테스트."""

    def test_no_metadata(self, config):
        from stages.stage1_rules import check_metadata_anomaly
        result = check_metadata_anomaly(None, "student1", config)
        assert result["score"] == 0, "메타데이터 없을 때 점수가 0이 아님"
        assert any("판정 불가" in str(e) for e in result["evidence"]), "판정 불가 표기 없음"

    def test_suspicious_edit_time(self, config):
        from stages.stage1_rules import check_metadata_anomaly
        # 5000자 글에 편집 시간 5분 → 1000자당 1분 → 의심
        metadata = {"total_time_minutes": 5, "author": "student2", "created": None, "modified": None}
        result = check_metadata_anomaly(metadata, "student2", config, char_count=5000)
        assert result["score"] >= 50, "의심스러운 편집 시간에 대해 점수가 부여되어야 함"
