"""pytest 공통 fixtures."""

import os
import sys
import pytest
import yaml

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def config():
    """config.yaml 로드."""
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def samples_dir():
    """테스트 샘플 디렉토리 경로."""
    return os.path.join(os.path.dirname(__file__), "samples")


@pytest.fixture
def normal_text(samples_dir):
    """정상 글 샘플."""
    with open(os.path.join(samples_dir, "normal_student.txt"), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def markdown_text(samples_dir):
    """마크다운 잔재 포함 글."""
    with open(os.path.join(samples_dir, "markdown_student.txt"), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def chatbot_text(samples_dir):
    """상투구 포함 글."""
    with open(os.path.join(samples_dir, "chatbot_student.txt"), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def contradiction_text(samples_dir):
    """모순 주장 포함 글."""
    with open(os.path.join(samples_dir, "contradiction_student.txt"), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def fake_factsheet(samples_dir):
    """가짜 팩트시트."""
    with open(os.path.join(samples_dir, "fake_factsheet_1984.md"), "r", encoding="utf-8") as f:
        return f.read()
