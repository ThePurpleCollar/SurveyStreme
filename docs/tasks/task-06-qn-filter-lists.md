# TASK-06: 비문항 필터링 화이트/블랙리스트 도입

## Status: 🟢 Complete

## Problem
`_is_valid_question_number()`의 블랙리스트가 10개 항목(대소문자 중복 포함)으로 작고,
화이트리스트가 없어 유효한 접두어(BVT, DEM 등)가 휴리스틱에 의해 잘못 거부될 수 있음.
대소문자 비교도 문자열 정확 매칭이라 'step1' 등을 놓침.

## Changes Made
- `services/llm_extractor.py`:
  - **`_VALID_QN_PREFIXES` 화이트리스트 신설** (18개):
    Q, SQ, SC, S, A, B, C, D, F, P, T, QA, QB, QC, QD, BV, BVT, DM, DEM, PR
  - **`_NON_QUESTION_PREFIXES` 블랙리스트 확장** (10 → 23개, 대문자 통일):
    기존: STEP, PAGE, ITEM, NOTE, PART
    추가: GOTO, SKIP, LOOP, SECTION, BLOCK, MODULE, INFO, TEXT, MSG,
          INTRO, END, CLOSE, THANK, DISPLAY, SHOW, HIDE, QUOTA, SAMPLE, CELL
  - **`_is_valid_question_number()` 재구조화**:
    1. 화이트리스트 → 항상 허용
    2. 블랙리스트 → 항상 거부 (대소문자 무시)
    3. 휴리스틱(길이, camelCase) → 기존과 동일
    4. 기타 → 허용
- `tests/smoke_test_qn_filter.py`: 화이트/블랙/휴리스틱/PDF regex 통합 50+ 테스트
