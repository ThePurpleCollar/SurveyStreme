# TASK-02: SummaryType 계산 로직 단일화

## Status: 🟢 Complete

## Problem
SummaryType/TableNumber 계산 로직이 두 곳에 중복 존재:
1. `services/postprocessor.py` — DataFrame 기반 (`assign_summary_type`, `update_summary_type`, `duplicate_and_insert_rows`, `add_table_number_column`)
2. `pages/doc_analyzer.py` — SurveyQuestion 기반 (`_scale_summary_type`, `_apply_postprocessing`)

TASK-01에서 PDF 경로도 SurveyDocument 기반으로 전환되어 DataFrame 기반 함수는 더 이상 사용되지 않음.
또한 비즈니스 로직이 UI 파일(`pages/`)에 있어 코딩 컨벤션 위반.

## Goal
SummaryType/TableNumber 계산 로직을 `services/postprocessor.py`에 단일화.

## Changes Made
- `services/postprocessor.py`: DataFrame 기반 함수 4개 제거, `scale_summary_type()` + `apply_postprocessing()` 추가
- `pages/doc_analyzer.py`: 로컬 `_scale_summary_type()`, `_apply_postprocessing()` 제거, `apply_postprocessing` import로 대체
- `tests/smoke_test_pdf_postprocess.py`: import 경로 업데이트
- 미사용 import 정리 (`re`, `pandas`)
