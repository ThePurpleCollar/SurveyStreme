import os
import time
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
MODEL_DOC_ANALYZER = "gemini-2.5-pro"      # Questionnaire Analyzer (복잡한 구조 파싱)
MODEL_TITLE_GENERATOR = "gemini-2.5-pro"   # Table Guide Builder (배너 설계)
MODEL_GRAMMAR_CHECKER = "gemini-2.5-flash"     # Grammar Checker (패턴 기반 교정)
MODEL_QUALITY_CHECKER = "gpt-5"                # Quality Checker (분석적 추론)
MODEL_LENGTH_ESTIMATOR = "gemini-2.5-flash"    # Length Estimator (경량 추정)
MODEL_CHECKLIST_GENERATOR = "gemini-2.5-flash" # Checklist Generator (속도 우선)
DEFAULT_MODEL = "gemini-2.5-flash"

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


_RETRYABLE_ERRORS = (ConnectionError, TimeoutError, OSError)
_MAX_RETRIES = 3
_BASE_DELAY = 2  # seconds


def _is_retryable(error: Exception) -> bool:
    """재시도 가능한 에러인지 판별."""
    if isinstance(error, _RETRYABLE_ERRORS):
        return True
    msg = str(error).lower()
    return any(kw in msg for kw in ('429', '500', '502', '503', 'rate limit', 'timeout', 'overloaded'))


def _retry_with_backoff(func, *args, **kwargs):
    """Exponential backoff 재시도 래퍼."""
    last_error = None
    for attempt in range(_MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < _MAX_RETRIES - 1 and _is_retryable(e):
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(f"LLM call failed (attempt {attempt + 1}/{_MAX_RETRIES}): {e}. "
                               f"Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise
    raise last_error


def call_llm(prompt: str, model: str = DEFAULT_MODEL, *,
             temperature: float = 0.2, top_p: float = 0.8,
             max_tokens: int = 16384) -> str:
    """통합 LLM 호출 — Gemini는 Vertex AI, GPT는 OpenAI SDK 경유.

    Args:
        prompt: 사용자 프롬프트
        model: 모델명
        temperature, top_p, max_tokens: 생성 파라미터

    Returns:
        LLM 응답 텍스트
    """
    def _do_call():
        if _is_gemini(model):
            init_gemini()
            from vertexai.generative_models import (
                GenerativeModel, GenerationConfig,
                HarmCategory, HarmBlockThreshold,
            )

            gemini = GenerativeModel(model)
            config = GenerationConfig(
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_tokens,
            )
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
            response = gemini.generate_content(
                prompt, generation_config=config, safety_settings=safety_settings,
            )
            if not response.candidates:
                raise ValueError("Gemini response blocked or empty (no candidates)")
            try:
                return response.text.strip()
            except ValueError:
                block_reason = getattr(response.candidates[0], "finish_reason", "unknown")
                raise ValueError(f"Gemini response blocked (reason: {block_reason})")
        else:
            client = _get_openai_client()
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content if response.choices else None
            if content is None:
                raise ValueError("OpenAI response returned empty content")
            return content.strip()

    return _retry_with_backoff(_do_call)


def call_llm_json(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, *,
                  temperature: float = 0.2, top_p: float = 0.8,
                  max_tokens: int = 16384) -> dict:
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
    import re

    def _parse_json_safe(text: str) -> dict:
        """Parse JSON with fallback: strip markdown fences if present."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try stripping markdown code fences (```json ... ```)
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            raise

    def _do_call():
        if _is_gemini(model):
            init_gemini()
            from vertexai.generative_models import (
                GenerativeModel, GenerationConfig,
                HarmCategory, HarmBlockThreshold,
            )

            gemini = GenerativeModel(model, system_instruction=system_prompt)
            config = GenerationConfig(
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            )
            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
            response = gemini.generate_content(
                user_prompt, generation_config=config, safety_settings=safety_settings,
            )
            if not response.candidates:
                raise ValueError("Gemini JSON response blocked or empty (no candidates)")
            try:
                raw_text = response.text
            except ValueError:
                block_reason = getattr(response.candidates[0], "finish_reason", "unknown")
                raise ValueError(f"Gemini JSON response blocked (reason: {block_reason})")
            return _parse_json_safe(raw_text)
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
            content = response.choices[0].message.content if response.choices else None
            if content is None:
                raise ValueError("OpenAI JSON response returned empty content")
            return _parse_json_safe(content)

    return _retry_with_backoff(_do_call)


def question_summary(client, text, model=DEFAULT_MODEL):
    """문항 요약 생성"""
    prompt = f"""{text}

Review the questionnaire content and succinctly identify its primary purpose and type in a single sentence."""

    try:
        return call_llm(prompt, model)
    except Exception as e:
        st.error(f"Error during summary generation: {e}")
        return None
