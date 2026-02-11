# TASK-14: SYSTEM_PROMPT에 answer_options 추출 가이드 추가

## Status: 🟢 Complete

## Problem
SYSTEM_PROMPT에 answer_options 추출에 대한 구체적 가이드가 없어,
LLM이 테이블/리스트에서 보기를 빈 배열로 반환하는 경우가 많음 (추출율 ~30-40%).
TABLE RECOGNITION 섹션에 "2-column table → answer option list"라는 한 줄만 있을 뿐,
어떻게 {code, label} 쌍으로 변환하는지 예시가 없음.

## Changes Made
- `services/llm_extractor.py` — SYSTEM_PROMPT에 `ANSWER OPTIONS — EXTRACTION RULES` 섹션 추가:
  - **Source 1**: 2-column table (code | label) → {code, label} 쌍 변환 예시
  - **Source 2**: Numbered list (#. prefix) → 순차 코드 자동 할당
  - **Source 3**: Inline code=label 쌍 (스케일 앵커) → 파싱 규칙
  - **Source 4**: Bulleted list (- prefix) → 순차 코드 자동 할당
  - **Source 5**: "Code. Label" 패턴 (1. Very satisfied)
  - **CRITICAL RULES**: Grid 스케일 컬럼=옵션, 행=구조, 모든 옵션 빠짐없이 추출, 면접원 지시 제외
