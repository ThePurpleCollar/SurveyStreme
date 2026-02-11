# TASK-05: question_type 정규화 매핑 확장

## Status: 🟢 Complete

## Problem
`_normalize_question_type()`이 기본 유형과 일부 한/영 변형만 처리.
LLM이 "single choice", "1-5", "NPS", "dropdown", "free text" 등을 출력하면 원본 그대로 유지되어
downstream SummaryType 계산에서 누락됨.
또한 기존 "5점" 정규식에 버그 (`척도?`가 `척`을 필수로 요구).

## Changes Made
- `services/llm_extractor.py` — `_normalize_question_type()` 확장:
  - **Section 3**: `O` → OE 약어 추가
  - **Section 4** (regex patterns):
    - `Npt scale` → Npt
    - Range notation: `1-5`, `0-10`, `scale 1-7`, `1 to 5`, `1~7` → Npt
    - `Likert N` / `Likert-N` → Npt
    - `NPS` / `Net Promoter Score` → 11pt
  - **Section 4 bugfix**: `5점` regex — `척도?` → `(?:척도?)?` (척 자체를 optional로)
  - **Section 5** (synonym mappings) 대폭 확장:
    - SA: single choice/select, binary, yes/no, dichotomous, boolean, dropdown, 객관식
    - MA: multiple choice/select/response, choose all, check all, pick all
    - OE: free text, freetext, verbatim, open-ended, text entry/input, essay, 서술형, 기술형
    - NUMERIC: constant sum, allocation, 배분
    - SCALE: slider, sliding scale
    - RANK: ranking, rank order
- `tests/smoke_test_normalize_type.py`: 90+ 테스트 케이스 전체 커버
