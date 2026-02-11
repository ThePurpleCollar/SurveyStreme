# Survey Stream 개선 로드맵

> Claude Code 작업 관리 파일. 각 작업의 `[ ]`를 `[x]`로 변경하여 진행을 추적합니다.
> 상세 스펙이 있는 작업은 `docs/tasks/` 폴더 참조.

## Phase 1 — 구조 통일 ✅

- [x] **TASK-01**: PDF 파이프라인 SurveyDocument 출력 통일 → @docs/tasks/task-01-pdf-unification.md
- [x] **TASK-02**: SummaryType 계산 로직 단일화 → @docs/tasks/task-02-summary-type-dedup.md
- [x] **TASK-03**: PDF 문항번호 정규식 패턴 강화 → @docs/tasks/task-03-pdf-regex.md

## Phase 2 — 추출 품질 향상 ✅

- [x] **TASK-04**: LLM 프롬프트에 Matrix/Grid 포맷 추가 → @docs/tasks/task-04-matrix-grid-format.md
- [x] **TASK-05**: question_type 정규화 매핑 확장 → @docs/tasks/task-05-normalize-type-expand.md
- [x] **TASK-06**: 비문항 필터링 화이트/블랙리스트 도입 → @docs/tasks/task-06-qn-filter-lists.md
- [x] **TASK-07**: 청크 간 컨텍스트 전달 (이전 문항 정보 주입) → @docs/tasks/task-07-chunk-context.md

## Phase 3 — UX 개선

- [x] **TASK-08**: 세션 덮어쓰기 경고 다이얼로그
- [ ] **TASK-09**: Table Guide 탭 진행 상태 표시
- [ ] **TASK-10**: LLM 호출 자동 재시도 (exponential backoff)

## Phase 4 — 아키텍처 정비

- [ ] **TASK-11**: 핵심 함수 단위 테스트 작성
- [ ] **TASK-12**: Table Guide 코드 모듈 분리
- [ ] **TASK-13**: 프롬프트 파일 외부화 (prompts/ 디렉토리)

## Phase 5 — 추출 정확도 ✅

- [x] **TASK-14**: SYSTEM_PROMPT에 answer_options 추출 가이드 추가 → @docs/tasks/task-14-answer-options-prompt.md
- [x] **TASK-15**: SYSTEM_PROMPT에 skip_logic/filter 추출 규칙·예시 추가 → @docs/tasks/task-15-skip-filter-prompt.md
- [x] **TASK-16**: PDF 경로에 LLM 추출 적용 (DOCX 파이프라인 통일)

## Phase 6 — Table Guide 품질 ✅

- [x] **TASK-17**: 배너→문항 할당 semantic fitness scoring 도입
- [x] **TASK-18**: SubBanner 프롬프트 강화 (매트릭스 항목 추출, 파이핑 처리)
- [x] **TASK-19**: Special Instructions 프롬프트 개선 (도메인별 예시, 패턴 확장)

## Phase 7 — 안정성

- [ ] **TASK-20**: LLM 호출 자동 재시도 (exponential backoff) — TASK-10 통합
- [ ] **TASK-21**: Phase 5 enrichment 실패 시 사용자 알림

## Phase 8 — 신규 기능 ✅

- [x] **Expert Consensus Banner**: 전문가 합의 기반 배너 생성 파이프라인
- [x] **Intelligence Dashboard**: 설문지 전체 요약 대시보드 (LOI 추정, 유형 분포, 스킵 복잡도)
- [x] **Piping Intelligence**: 파이핑 로직 분석 및 시각화
- [x] **Path Simulator**: DFS 경로 열거, 테스트 시나리오 생성, 인터랙티브 경로 추적기
- [x] **Checklist Generator**: 알고리즘 + LLM 기반 링크테스트 체크리스트 생성
- [x] **Translation Helper**: 다국어 번역 지원 도구

## Phase 9 — 감사 & 품질

- [x] **Audit Fix**: inline import 이동, stale state 초기화, 빈 결과 메시지 개선, magic number 상수화
