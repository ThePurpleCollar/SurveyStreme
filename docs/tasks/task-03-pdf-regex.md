# TASK-03: PDF 문항번호 정규식 패턴 강화

## Status: 🟢 Complete

## Problem
PDF `extract_question_data()`가 단일 정규식으로 `.` 구분자만 지원:
- `)`, `:` 구분자 미지원 (Q1), Q1:)
- 밑줄 하위문항 미지원 (Q1_1, Q2_3)
- 대괄호 패턴 미지원 ([SC2. INDUSTRY (MA)], Q2 [S] text)
- False positive 필터링 없음 (STEP1, PAGE2, RegionCode2 등 오탐)

## Changes Made
- `services/postprocessor.py`:
  - 3-pattern 체계 도입 (llm_extractor와 동일 구조):
    - Pattern A: 표준 구분자 `.` / `)` / `:` + 밑줄 하위문항 `[-_]\d+`
    - Pattern B: 공백+대괄호 타입 힌트 `Q2 [S] text`
    - Pattern C: 대괄호 헤더 `[SC2. INDUSTRY (MA)]`
  - `_match_question_line()` 헬퍼: 3개 패턴 순차 시도 + `_is_valid_question_number()` 필터링
  - `extract_question_data()`: 기존 단일 regex → `_match_question_line()` 사용으로 리팩터링
  - `_is_valid_question_number` import from `llm_extractor` (chunker.py와 동일 패턴)
- `tests/smoke_test_pdf_regex.py`: 20+ 테스트 케이스 (패턴별 + false positive 거부 + 통합)
