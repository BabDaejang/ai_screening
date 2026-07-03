"""LLM 프로바이더 팩토리."""

from providers.base import LLMProvider
from providers.anthropic_provider import AnthropicProvider
from providers.gemini_provider import GeminiProvider
from providers.openai_provider import OpenAIProvider


from typing import Optional

def create_provider(provider_name: str, api_key: str, model_screening: str, model_verify: str, cost_tracker: Optional[object] = None) -> LLMProvider:
    """프로바이더 이름으로 LLM 프로바이더 인스턴스 생성."""
    providers = {
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
    }
    if provider_name not in providers:
        raise ValueError(f"지원하지 않는 프로바이더: {provider_name}. 사용 가능: {list(providers.keys())}")
    return providers[provider_name](
        api_key=api_key,
        model_screening=model_screening,
        model_verify=model_verify,
        cost_tracker=cost_tracker
    )
