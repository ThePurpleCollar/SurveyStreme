"""Grammar Checker 서비스 로직.

설문 문항의 문법을 LLM으로 배치 교정한다.
UI 렌더링은 포함하지 않으며 pages/quality_checker.py에서 호출한다.
"""

import logging
import pandas as pd
import streamlit as st

from services.llm_client import call_llm_json, MODEL_GRAMMAR_CHECKER

logger = logging.getLogger(__name__)

BATCH_SIZE = 20

# ── 시스템 프롬프트 ────────────────────────────────────────────────

_SYSTEM_PROMPT_KO = """당신은 한국어 설문 조사 전문 교정자입니다. 설문 문항의 문법, 맞춤법, 표현을 교정하세요.

## 교정 규칙

1. **의도·톤 유지**: 원본 질문의 의미와 의도를 정확히 유지합니다.
2. **격식체/비격식체 보존**: 원본이 "~하십니까"이면 "~하십니까"를 유지하고, "~하나요"이면 "~하나요"를 유지합니다. 존칭 수준을 변경하지 마세요.
3. **실질적 오류만 교정**: 문법 오류, 맞춤법 오류, 어색한 표현만 교정합니다. 동의어 치환, 어미 미세 변경, 스타일 선호 차이는 교정하지 마세요.
4. **변경 없음**: 오류가 없으면 원본 텍스트를 그대로 반환하고 has_changes를 false로 설정합니다.

## 보존 목록 (절대 수정 금지)

- 파이핑 참조: `[Q1 응답]`, `{Q2_answer}`, `[이전 응답]`, `${...}` 등
- 지시문: `[SHOW CARD]`, `[보기 제시]`, `[복수 응답]`, `[단일 응답]`
- 척도 라벨: "전혀 그렇지 않다 ← → 매우 그렇다" 등
- 코드 번호: 보기의 번호(1, 2, 3, ..., 98, 99)
- 특수 표기: `%`, `N/A`, `기타(직접 기재)`, `없음`

## 보기(Options) 교정

- 보기가 제공된 경우, 각 보기의 label만 교정합니다.
- code(번호)는 절대 변경하지 마세요.
- 보기에 오류가 없으면 corrected_options를 빈 배열로 반환합니다.

## JSON 출력 형식

{
  "results": [
    {
      "question_number": "Q1",
      "corrected_text": "교정된 질문 텍스트",
      "corrected_options": [{"code": "1", "label": "교정된 보기"}],
      "has_changes": true,
      "changes_summary": "~했습니다 → ~하셨습니까"
    }
  ]
}

- has_changes가 false이면 corrected_text는 원본과 동일해야 합니다.
- changes_summary는 주요 변경 내용을 간결하게 요약합니다 (변경 없으면 빈 문자열)."""

_SYSTEM_PROMPT_EN = """You are an expert English survey proofreader. Correct grammar, spelling, and phrasing of survey questions.

## Correction Rules

1. **Preserve Intent**: Maintain the original meaning and intent exactly.
2. **Preserve Tone**: Keep formal/informal register consistent with the original.
3. **Only Fix Real Errors**: Correct grammar errors, spelling mistakes, typos, and awkward phrasing only. Do NOT make synonym substitutions, minor stylistic changes, or rephrase for preference.
4. **No Changes**: If there are no errors, return the original text unchanged and set has_changes to false.

## Preserve List (Do NOT modify)

- Piping references: `[Q1 response]`, `{Q2_answer}`, `[previous answer]`, `${...}`
- Instructions: `[SHOW CARD]`, `[MULTIPLE RESPONSE]`, `[SINGLE RESPONSE]`
- Scale labels: "Not at all ← → Very much" etc.
- Code numbers: option numbers (1, 2, 3, ..., 98, 99)
- Special notations: `%`, `N/A`, `Other (specify)`, `None`

## Options Correction

- When options are provided, correct only the label text.
- NEVER change the code (number).
- If options have no errors, return corrected_options as an empty array.

## JSON Output Format

{
  "results": [
    {
      "question_number": "Q1",
      "corrected_text": "Corrected question text",
      "corrected_options": [{"code": "1", "label": "Corrected option"}],
      "has_changes": true,
      "changes_summary": "Fixed subject-verb agreement"
    }
  ]
}

- If has_changes is false, corrected_text must be identical to the original.
- changes_summary briefly describes the key changes (empty string if no changes)."""


# ── 배치 포맷 ─────────────────────────────────────────────────────

def _format_question_for_prompt(qn: str, text: str, options_str: str) -> str:
    """문항 정보를 프롬프트용 텍스트로 포맷."""
    parts = [f"[{qn}]", f"Text: {text}"]
    if options_str and options_str.strip():
        parts.append(f"Options: {options_str}")
    return "\n".join(parts)


def _build_batch_prompt(batch: list) -> str:
    """배치 내 문항들을 하나의 프롬프트로 결합."""
    sections = []
    for item in batch:
        sections.append(
            _format_question_for_prompt(item["qn"], item["text"], item["options"])
        )
    return (
        "Correct the grammar of the following survey questions:\n\n"
        + "\n\n---\n\n".join(sections)
    )


# ── 결과 파싱 ─────────────────────────────────────────────────────

def _parse_batch_result(raw: dict, batch: list) -> list:
    """LLM JSON 응답을 결과 리스트로 변환.

    Returns:
        List[dict]: question_number, original_text, original_options,
                    corrected_text, corrected_options, has_changes, changes_summary
    """
    results_raw = raw.get("results", [])
    qn_to_item = {item["qn"]: item for item in batch}

    parsed = []
    seen_qn = set()

    for r in results_raw:
        qn = str(r.get("question_number", "")).strip()
        if not qn:
            continue
        seen_qn.add(qn)

        original = qn_to_item.get(qn, {})
        has_changes = bool(r.get("has_changes", False))
        corrected_text = str(r.get("corrected_text", original.get("text", "")))

        # corrected_options 파싱
        corrected_options = []
        for opt in r.get("corrected_options", []):
            if isinstance(opt, dict) and "code" in opt and "label" in opt:
                corrected_options.append(
                    {"code": str(opt["code"]), "label": str(opt["label"])}
                )

        parsed.append({
            "question_number": qn,
            "original_text": original.get("text", ""),
            "original_options": original.get("options", ""),
            "corrected_text": corrected_text,
            "corrected_options": corrected_options,
            "has_changes": has_changes,
            "changes_summary": str(r.get("changes_summary", "")),
        })

    # LLM이 누락한 문항은 변경 없음으로 추가
    for item in batch:
        if item["qn"] not in seen_qn:
            parsed.append({
                "question_number": item["qn"],
                "original_text": item["text"],
                "original_options": item["options"],
                "corrected_text": item["text"],
                "corrected_options": [],
                "has_changes": False,
                "changes_summary": "",
            })

    return parsed


# ── 메인 처리 ─────────────────────────────────────────────────────

def check_grammar(df: pd.DataFrame, language: str, progress_callback) -> list:
    """DataFrame에서 문항을 추출하여 배치 문법 검사를 수행.

    Returns:
        List[dict] — 문항별 교정 결과
    """
    # 고유 문항 추출 (QuestionNumber 기준 중복 제거)
    seen = set()
    items = []
    for _, row in df.iterrows():
        qn = str(row.get("QuestionNumber", "")).strip()
        if not qn or qn in seen:
            continue
        text = str(row.get("QuestionText", "")).strip()
        if not text:
            continue
        seen.add(qn)
        options = str(row.get("AnswerOptions", "")).strip() if "AnswerOptions" in df.columns else ""
        items.append({"qn": qn, "text": text, "options": options})

    if not items:
        return []

    system_prompt = _SYSTEM_PROMPT_KO if language == "ko" else _SYSTEM_PROMPT_EN

    # 배치 분할
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    total_batches = len(batches)
    all_results = []

    for batch_idx, batch in enumerate(batches):
        progress_callback("batch_start", {
            "batch_index": batch_idx,
            "total_batches": total_batches,
            "question_count": len(batch),
        })

        user_prompt = _build_batch_prompt(batch)
        try:
            raw = call_llm_json(system_prompt, user_prompt, MODEL_GRAMMAR_CHECKER)
            results = _parse_batch_result(raw, batch)
        except Exception as e:
            logger.error(f"Grammar batch {batch_idx} failed: {e}")
            # 실패 시 모든 문항을 변경 없음으로 반환
            results = [{
                "question_number": item["qn"],
                "original_text": item["text"],
                "original_options": item["options"],
                "corrected_text": item["text"],
                "corrected_options": [],
                "has_changes": False,
                "changes_summary": f"Error: {e}",
            } for item in batch]

        all_results.extend(results)

        progress_callback("batch_done", {
            "batch_index": batch_idx,
            "total_batches": total_batches,
            "changed_count": sum(1 for r in results if r["has_changes"]),
        })

    return all_results


def apply_grammar_results(results: list):
    """교정 결과를 edited_df와 survey_document에 반영."""
    if "edited_df" not in st.session_state:
        return

    df = st.session_state["edited_df"]
    qn_to_result = {r["question_number"]: r for r in results}

    # GrammarChecker 컬럼 업데이트
    if "GrammarChecker" not in df.columns:
        df["GrammarChecker"] = ""

    for idx, row in df.iterrows():
        qn = str(row.get("QuestionNumber", "")).strip()
        if qn in qn_to_result:
            r = qn_to_result[qn]
            df.at[idx, "GrammarChecker"] = r["corrected_text"]

            # 보기 업데이트 (corrected_options가 있는 경우)
            if r["corrected_options"] and "AnswerOptions" in df.columns:
                opts_str = " | ".join(
                    f"{o['code']}. {o['label']}" for o in r["corrected_options"]
                )
                df.at[idx, "AnswerOptions"] = opts_str

    st.session_state["edited_df"] = df

    # survey_document에도 반영
    if "survey_document" in st.session_state and st.session_state["survey_document"]:
        for q in st.session_state["survey_document"].questions:
            if q.question_number in qn_to_result:
                r = qn_to_result[q.question_number]
                q.grammar_checked = r["corrected_text"]
