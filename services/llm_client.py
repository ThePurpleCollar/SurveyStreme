import os
import logging
import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# LiteLLM 프록시 설정
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY")
LITELLM_BASE_URL = "https://ipsos.litellm-prod.ai"

# ── 기능별 고정 모델 ──
MODEL_DOC_ANALYZER = "gemini-2.5-pro"          # Questionnaire Analyzer (Gemini 유지)
MODEL_TITLE_GENERATOR = "gpt-5"                # Table Guide Builder
MODEL_GRAMMAR_CHECKER = "gpt-5"                # Grammar Checker
MODEL_QUALITY_CHECKER = "gpt-5"                # Quality Checker
MODEL_LENGTH_ESTIMATOR = "gpt-4.1-mini"        # Length Estimator
MODEL_CHECKLIST_GENERATOR = "gpt-4.1-mini"     # Checklist Generator
DEFAULT_MODEL = "gpt-4.1-mini"

_GEMINI_INITIALIZED = False
_openai_client = None


def _is_gemini(model: str) -> bool:
    """모델명이 Gemini 계열인지 판별."""
    return model.startswith("gemini")


def _get_openai_client() -> OpenAI:
    """OpenAI 호환 클라이언트 싱글턴."""
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    if not LITELLM_API_KEY:
        st.error("LiteLLM API key (LITELLM_API_KEY) not found in .env file.")
        st.stop()

    _openai_client = OpenAI(api_key=LITELLM_API_KEY, base_url=LITELLM_BASE_URL)
    return _openai_client


def init_gemini():
    """Vertex AI SDK를 LiteLLM 프록시 경유로 초기화 (1회만 실행)"""
    global _GEMINI_INITIALIZED
    if _GEMINI_INITIALIZED:
        return

    if not LITELLM_API_KEY:
        st.error("LiteLLM API key (LITELLM_API_KEY) not found in .env file.")
        st.stop()

    try:
        import vertexai
        from google.auth.credentials import Credentials

        class _LiteLLMCredential(Credentials):
            def __init__(self, token):
                super().__init__()
                self.token = token
                self.expiry = None

            def refresh(self, request):
                pass

            @property
            def expired(self):
                return False

            @property
            def valid(self):
                return True

            def apply(self, headers, token=None):
                headers["Authorization"] = f"Bearer {self.token}"

        vertexai.init(
            project="ipsosfacto-prd",
            location="us-central1",
            api_endpoint=f"{LITELLM_BASE_URL}/vertex_ai/",
            credentials=_LiteLLMCredential(token=LITELLM_API_KEY),
            api_transport="rest",
        )
        _GEMINI_INITIALIZED = True
    except Exception as e:
        st.error(f"Failed to initialize Gemini via Vertex AI: {e}")
        st.stop()


def init_client():
    """OpenAI 호환 클라이언트 초기화 (PDF 경로 등 레거시 용)"""
    if not LITELLM_API_KEY:
        st.error("LiteLLM API key (LITELLM_API_KEY) not found in .env file.")
        st.stop()

    try:
        client = OpenAI(
            api_key=LITELLM_API_KEY,
            base_url=LITELLM_BASE_URL
        )
        return client
    except Exception as e:
        st.error(f"Failed to initialize OpenAI client: {e}")
        st.stop()


def call_llm(prompt: str, model: str = DEFAULT_MODEL, *,
             temperature: float = 0.2, top_p: float = 0.8,
             max_tokens: int = 8192) -> str:
    """통합 LLM 호출 — Gemini는 Vertex AI, GPT는 OpenAI SDK 경유.

    Args:
        prompt: 사용자 프롬프트
        model: 모델명
        temperature, top_p, max_tokens: 생성 파라미터

    Returns:
        LLM 응답 텍스트
    """
    if _is_gemini(model):
        init_gemini()
        from vertexai.generative_models import GenerativeModel, GenerationConfig

        gemini = GenerativeModel(model)
        config = GenerationConfig(
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_tokens,
        )
        response = gemini.generate_content(prompt, generation_config=config)
        return response.text.strip()
    else:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()


def call_llm_json(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, *,
                  temperature: float = 0.2, top_p: float = 0.8,
                  max_tokens: int = 8192) -> dict:
    """통합 JSON 구조화 LLM 호출 — Gemini는 Vertex AI, GPT는 OpenAI SDK 경유.

    Args:
        system_prompt: 시스템 프롬프트
        user_prompt: 사용자 프롬프트
        model: 모델명
        temperature, top_p, max_tokens: 생성 파라미터

    Returns:
        파싱된 JSON dict
    """
    import json

    if _is_gemini(model):
        init_gemini()
        from vertexai.generative_models import GenerativeModel, GenerationConfig

        gemini = GenerativeModel(model, system_instruction=system_prompt)
        config = GenerationConfig(
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        )
        response = gemini.generate_content(user_prompt, generation_config=config)
        return json.loads(response.text)
    else:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)


def question_summary(client, text, model=DEFAULT_MODEL):
    """문항 요약 생성"""
    prompt = f"""{text}

Review the questionnaire content and succinctly identify its primary purpose and type in a single sentence."""

    try:
        return call_llm(prompt, model)
    except Exception as e:
        st.error(f"Error during summary generation: {e}")
        return None
