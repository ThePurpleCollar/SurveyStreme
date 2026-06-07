# Survey Stream 개선 로드맵

> Claude Code 작업 관리 파일. 각 작업의 `[ ]`를 `[x]`로 변경하여 진행을 추적합니다.

## Phase 1–6 — 기초 구축 ✅

- [x] Phase 1: 구조 통일 (PDF→SurveyDocument, SummaryType 단일화)
- [x] Phase 2: 추출 품질 향상 (Matrix/Grid, 정규화, 필터링, 컨텍스트)
- [x] Phase 3: UX 개선 (세션 덮어쓰기 경고, 재시도)
- [x] Phase 5: 추출 정확도 (answer_options, skip_logic/filter 프롬프트)
- [x] Phase 6: Table Guide 품질 (배너 할당, SubBanner, Special Instructions)

## Phase 7 — 안정성 ✅

- [x] LLM 호출 자동 재시도 (exponential backoff)
- [x] Enrichment 실패 시 사용자 알림
- [x] 2-pass 검증 (정규식 vs LLM 비교, 누락 문항 감지)

## Phase 8–10 — 신규 기능 & 배너 ✅

- [x] Expert Consensus Banner (전문가 합의 파이프라인)
- [x] Intelligence Dashboard, Piping Intelligence, Path Simulator, Checklist Generator
- [x] Banner Pipeline Enhancement + Banner Management UI

## Phase P — 파서 레이어 강화 ✅

- [x] DocxCell + 병합 셀 처리
- [x] 취소선 셀 처리
- [x] 7-type 표 분류기 (section_header, coding_reference, multi_question, code_label, grid, matrix, generic)
- [x] 텍스트 박스 추출
- [x] 타입별 렌더링 마커 + SYSTEM_PROMPT
- [x] SurveyQuestion 스키마 확장 (sub_items, ProgrammingGuide)
- [x] 1셀 표 섹션 헤더 감지

## Phase R — 아키텍처 리팩토링 ✅

- [x] 정규식 의존 축소 → LLM 전면 위임 (Concept-based Prompting)
- [x] Gemini Safety Filter 해제 (BLOCK_NONE)
- [x] 대괄호 [DE1.] 형태 문항 지원
- [x] merge_chunk_results 동일 ID 다른 문항 보호
- [x] LLM 직접 배열 반환 처리
- [x] 대형 설문지 출력 잘림 방지 (청크 한도 400→150)
- [x] code_label 표 분류 확장 (2~4열, 문자 코드, 가로 배치)

## Phase U — UI/UX 통합 ✅

- [x] 사이드바 3메뉴 구조 (Questionnaire Analyzer, Table Guide Builder, Logic Checker)
- [x] Table Guide Builder 단순화 (Title + Banner 체크박스 + 원버튼)
- [x] Logic Checker 통합 (Skip Logic + Path Simulator + Checklist + Quality Checker)
- [x] Study Brief 자동 추정 (Enrichment → 프리필 → 사용자 확인)
- [x] Extraction Coverage Report
- [x] Banner Layout 엑셀 (가로 Cross-Tab)
- [x] UI 전체 한국어화
- [x] 체크리스트 step-by-step 가이드 + Negative 테스트 + 파싱 실패 통합

## Phase N — 다음 개선 후보

- [ ] 보기 추출률 추가 개선 (generic → matrix 분류 정밀화)
- [ ] filter_condition을 경로 시뮬레이션에 반영
- [ ] 추출 정확도 Ground Truth 비교 평가
- [ ] DP 사양서 자동 생성
- [ ] 페르소나 기반 시나리오 고도화 (filter 반영 + behavioral 포함)

## Phase A — Agentic Link Test Handoff

- [x] **TASK-A1**: 실행 가능한 스킵 조건 평가 기반 시나리오 생성 → full condition parser 사용
- [x] **TASK-A2**: 실제 trace 기준 분기 커버리지 검증 → source 미도달 false positive 제거
- [x] **TASK-A3**: 미커버 분기 원인 진단 → `Branch Diagnostics` UI/Excel 추가
- [ ] **TASK-A4**: SurveyStreme → survey-link-tester A2A handoff schema 설계 → @docs/tasks/task-a4-link-test-handoff-schema.md
- [ ] **TASK-A5**: 링크 테스트 시나리오 export payload 생성 → SurveyStreme에서 agent 입력 JSON 출력
- [ ] **TASK-A6**: survey-link-tester가 payload를 받아 브라우저 테스트 실행 → 화면 확인/녹화/reasoning 로그 연결
- [ ] **TASK-A7**: 테스트 결과를 SurveyStreme QA 리포트로 회수 → 오류, 재현 경로, 스크린샷/녹화 링크 정리
