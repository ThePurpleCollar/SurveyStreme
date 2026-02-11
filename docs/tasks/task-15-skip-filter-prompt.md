# TASK-15: SYSTEM_PROMPT에 skip_logic/filter 추출 규칙·예시 추가

## Status: 🟢 Complete

## Problem
SYSTEM_PROMPT에 skip_logic/filter 추출에 대한 구체적 규칙과 예시가 없어,
LLM이 복합 조건이나 [PN:] 노트에서 라우팅 정보를 놓침 (추출율 ~20-35%).
"ASK IF", "[PN: ...]" 언급만 있고, 조건 형식이나 파싱 방법의 예시가 전무.

## Changes Made
- `services/llm_extractor.py` — SYSTEM_PROMPT에 2개 섹션 추가:

  **SKIP LOGIC — EXTRACTION RULES**:
  - Source 1: 보기 옆 goto/skip (→ Go to Q5)
  - Source 2: [PN: IF...GO TO...] 프로그래머 노트
  - Source 3: Arrow notation (──→ Skip to Q10)
  - Source 4: Conditional blocks (IF Q2=1,2: ASK Q3-Q7)
  - Condition format: QN=code, QN=code1,code2, QN!=code, & for AND

  **FILTER CONDITION — EXTRACTION RULES**:
  - Source 1: [PN: ASK IF ...] 프로그래머 노트
  - Source 2: "ASK IF" / "ONLY IF" / "ASK ALL" 텍스트
  - Source 3: "모두에게" / "전원 응답" 한국어 패턴
  - Source 4: Inline filter in bracket headers
  - Source 5: Implicit filter 설명 (추론하지 말고 명시적 텍스트만 추출)
  - Format rules: 동일한 조건 형식, "All respondents" 표준화
