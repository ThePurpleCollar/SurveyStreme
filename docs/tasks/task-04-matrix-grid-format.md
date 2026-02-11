# TASK-04: LLM 프롬프트에 Matrix/Grid 포맷 추가

## Status: 🟢 Complete

## Problem
SYSTEM_PROMPT에 FORMAT A–E(문항번호 인식)와 타입 정의(Npt x M, MATRIX)가 있으나,
Matrix/Grid 문항이 문서에서 실제로 어떤 형태로 나타나는지 보여주는 FORMAT 섹션이 없음.
테이블 인식 가이드도 불충분하여 2-column 답변 테이블과 grid 테이블을 구별하기 어려움.

## Changes Made
- `services/llm_extractor.py` SYSTEM_PROMPT에 추가:
  - **FORMAT F — Matrix/Grid**: 3가지 변형
    - Variant 1: 마크다운 테이블(행=항목, 열=척도점)
    - Variant 2: 문항 줄기 + 하위항목(a/b/c) 공유 척도
    - Variant 3: 비척도 매트릭스(카테고리 열)
  - **TABLE RECOGNITION** 섹션: 테이블 유형 구별 규칙
    - 2-column(코드+라벨) → 답변 보기
    - Multi-column + 숫자 헤더 + 항목 행 → grid/matrix scale
    - Multi-column + 카테고리 헤더 + 항목 행 → non-scale matrix
  - 기존 IMPORTANT RULES의 중복 테이블 라인 제거
