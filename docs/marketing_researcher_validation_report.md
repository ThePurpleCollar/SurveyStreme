# Marketing Researcher Validation Report

작성일: 2026-04-28

## 1. 검증 목적

마케팅 리서치 연구원이 실제 설문 프로젝트에서 Survey Stream을 사용하는 상황을 기준으로, 다음 항목을 검증했다.

- DOCX 설문지 업로드 후 문항 구조를 얼마나 빠르고 안정적으로 읽는가
- 연구원이 추출 결과를 검토하고 수정할 수 있는가
- Table Guide와 Banner Spec이 DP 전달 문서로 충분한가
- Logic Checker가 Researcher, Script, Link Test 관점의 확인 항목을 분리해 주는가
- 출력물 Excel이 후속 업무에서 바로 열고 검토할 수 있는 구조인가

## 2. 연구원 사용 시나리오

### 시나리오 A: 신규 TV 카테고리 U&A / 구매 의향 조사

연구원은 TV 카테고리 설문 DOCX를 받아 다음 업무를 수행한다.

1. Questionnaire Analyzer에서 DOCX를 업로드한다.
2. Study Brief에 client brand, study objective를 입력한다.
3. AI 문항 추출을 실행한다.
4. 추출 커버리지 요약을 확인한다.
5. 문항번호, 실제 변수명, 문항유형, 보기, 필터, 스킵 로직을 검토한다.
6. 필요 시 스프레드시트 화면에서 `SourceVariable`, `QuestionType`, `AnswerOptions`, `Filter`, `SkipLogic`을 수정한다.
7. 세션 JSON을 저장한다.
8. Table Guide Builder에서 Table Title, Sort, Net/Recode, SubBanner, Special Instructions, Banner를 생성/수정한다.
9. Review & Export에서 DP Handoff 검증 요약을 확인한다.
10. 내부 검토용 Table Guide Excel과 DP Handoff Excel을 다운로드한다.
11. Logic Checker에서 로직 검증을 실행한다.
12. Summary, Logic Map, Branch Test, Respondent Paths, Checklist를 검토한다.
13. Logic Checker Excel을 다운로드해 Script 구현 확인 및 링크 테스트 준비에 사용한다.

## 3. 검증 범위

이번 검증은 두 층으로 나누어 진행했다.

### 실제 DOCX 구조 검증

로컬 `output` 폴더의 실제 DOCX 파일을 대상으로 다음을 측정했다.
NDA 보호를 위해 원본 파일명과 프로젝트명은 익명화했다.

- 파일 크기
- DOCX 구조 파싱 시간
- 섹션, 단락, 표 수
- AI 처리용 청크 수
- 문항 후보 수
- 표 분류 결과
- `generic`, `unknown` 표 수

### 고정 연구원 시나리오 산출물 검증

LLM 호출 없이도 재현 가능한 TV 조사 시나리오 데이터를 구성해 다음 산출물을 실제 생성했다.

- Analyzer Excel
- 내부 검토용 Table Guide Excel
- DP Handoff Excel
- Logic Checker Excel

이 시나리오는 9개 문항, 5개 배너, 13개 배너 포인트로 구성했다.

## 4. 실제 DOCX 파싱 성능

| 파일 | 크기 | 파싱 시간 | 섹션 | 단락 | 표 | 청크 | 문항 후보 | generic 표 | unknown 표 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DOCX-A Panel Study QNR | 8.32 MB | 0.80s | 3 | 260 | 78 | 1 | 59 | 29 | 1 |
| DOCX-B Tracking QNR | 5.23 MB | 1.92s | 52 | 374 | 48 | 1 | 47 | 43 | 0 |
| DOCX-C Master QNR | 5.23 MB | 2.69s | 9 | 535 | 144 | 2 | 153 | 49 | 1 |
| DOCX-D Daily Usage QNR | 1.45 MB | 5.57s | 8 | 932 | 255 | 2 | 238 | 18 | 26 |
| DOCX-E Global Trend QNR | 0.92 MB | 0.90s | 6 | 156 | 51 | 1 | 59 | 4 | 2 |
| DOCX-F Brand Strategy QNR | 0.42 MB | 1.83s | 8 | 234 | 64 | 1 | 50 | 17 | 0 |

### 해석

- DOCX 구조 파싱 자체는 대부분 수 초 이내로 완료된다.
- 청크 수는 대부분 1-2개로 유지되어 AI 호출 수가 과도하게 늘어나지는 않는다.
- 표가 많은 문서일수록 `generic` 또는 `unknown` 표가 늘어난다.
- `generic` 표가 많은 파일은 보기표, 매트릭스, 제품 카드가 누락될 가능성이 있으므로 커버리지 리포트에서 사용자가 확인할 수 있어야 한다.
- 특히 DOCX-D 유형은 표 255개, unknown 26개로 구조 복잡도가 높다. 이 유형은 AI 추출 결과만 신뢰하지 말고 커버리지와 원문 근거 확인이 필요하다.

## 5. 고정 연구원 시나리오 검증 결과

### 시나리오 구성

| 항목 | 값 |
|---|---:|
| 문항 수 | 9 |
| 배너 수 | 5 |
| 배너 포인트 수 | 13 |
| 배너가 할당된 분석 문항 | 4 |
| 스킵 규칙 | 2 |

### 처리 시간

| 처리 단계 | 소요 시간 |
|---|---:|
| Analyzer Excel 생성 | 0.0314s |
| Table Guide 컴파일 | 0.0001s |
| 내부 검토용 Table Guide Excel 생성 | 0.0266s |
| DP Handoff Excel 생성 | 0.0177s |
| Logic path simulation | 0.0002s |
| Algorithmic review | 0.0002s |
| Algorithmic checklist | 0.0003s |
| Persona generation | 0.0002s |
| Logic Checker Excel 생성 | 0.0262s |

### DP Handoff 검증

| 항목 | 결과 |
|---|---:|
| Table Guide 전체 행 | 9 |
| Table Guide Ready for DP | 9 |
| Table Guide Researcher Review 필요 | 0 |
| Banner Spec 전체 값 | 13 |
| Banner Spec Ready for DP | 13 |
| Banner Spec Researcher Review 필요 | 0 |

### Logic Checker 검증

| 항목 | 결과 |
|---|---:|
| 전체 경로 | 3 |
| 스킵 규칙 | 2 |
| 분기 커버리지 | 100% |
| 테스트 시나리오 | 2 |
| 대표 응답자 경로 | 12 |
| QA 항목 | 8 |
| 구조 검증 Critical | 0 |
| 구조 검증 Warning | 0 |
| 파싱 불가 조건 | 0 |

Logic Checker의 최종 판단은 `확인 후 스크립팅 전달 권장`으로 나왔다. 이는 구조 오류 때문이 아니라 Script 구현 확인과 링크 테스트 확인 항목이 생성되었기 때문이다. 연구원 입장에서는 정상적인 결과다.

## 6. 생성된 산출물

| 산출물 | 경로 | 시트 |
|---|---|---|
| Analyzer Excel | `output/validation/researcher_scenario_analyzer.xlsx` | Questions, AnswerOptions, Banner Spec, Banner Layout, Net Recode Spec |
| 내부 검토용 Table Guide | `output/validation/researcher_scenario_table_guide.xlsx` | Cover, Table Guide, Banner Spec, Banner Layout, Net Recode Spec, Answer Options |
| DP Handoff Excel | `output/validation/researcher_scenario_dp_handoff.xlsx` | Table Guide, Banner Spec |
| Logic Checker Excel | `output/validation/researcher_scenario_logic_checker.xlsx` | Summary, Logic Map, Branch Test, Respondent Paths, Checklist, Unparsed |

### 산출물 헤더 검증

| 검증 항목 | 결과 |
|---|---|
| Analyzer Questions에 `SourceVariable` 포함 | 통과 |
| Analyzer Banner Spec에 `SPSSCondition` 포함 | 통과 |
| 내부 Table Guide에 `QAWarning` 포함 | 통과 |
| 내부 Banner Spec에 `Rationale(KO)` 포함 | 통과 |
| DP Table Guide에 `DP Review Status` 포함 | 통과 |
| DP Banner Spec에 `SPSSCondition` 포함 | 통과 |
| Logic Checker에 `Summary` 시트 포함 | 통과 |
| Logic Checker에 `Checklist` 시트 포함 | 통과 |

## 7. 발견 및 조치한 결함

### 종료 타깃 `END` 파싱 문제

검증 중 `SkipLogic.target = "END"`처럼 짧게 작성된 종료 타깃이 종료 노드로 파싱되지 않는 문제가 발견됐다.

영향:

- 종료 분기가 그래프에 반영되지 않을 수 있다.
- Logic Checker의 `total_skip_rules`와 실제 테스트 시나리오 커버리지가 어긋날 수 있다.
- 연구원이 링크 테스트 케이스를 덜 받게 될 수 있다.

조치:

- `services/skip_logic_service.py`의 종료 패턴을 보정해 `END` 단독 표기를 종료로 인식하도록 수정했다.
- `tests/smoke_test_logic_checker_researcher_ui.py`에 회귀 테스트를 추가했다.
- 동일 시나리오 재검증 결과 분기 커버리지가 50%에서 100%로 개선됐다.

## 8. 품질 평가

### 강점

- 연구원 관점에서 추출 결과, Table Guide, Logic Checker가 하나의 흐름으로 연결된다.
- `SourceVariable`이 Analyzer, 편집 화면, Table Guide, DP Handoff까지 이어져 DP가 Syntax 작성 시 문항번호와 실제 변수명을 혼동할 가능성이 줄었다.
- DP Handoff Excel은 `Table Guide`와 `Banner Spec` 2개 시트로 단순화되어 DP 전달 목적에 맞다.
- `SPSSCondition`, `CodeLabels`, `QAWarning`, `DP Review Status`가 있어 DP팀과 Researcher가 같은 기준으로 확인할 수 있다.
- Logic Checker Excel은 Summary, Logic Map, Branch Test, Respondent Paths, Checklist로 구성되어 Script 구현 확인과 링크 테스트 준비에 적합하다.
- `Rationale(KO)`가 한국어로 제공되어 내부 연구원 리뷰에 더 적합하다.

### 리스크

- 이번 자동 검증에서는 실제 LLM 호출 기반 전체 추출 품질을 재측정하지 않았다. 네트워크/프록시 상태가 안정된 환경에서 실문서 추출 E2E 테스트가 추가로 필요하다.
- 실제 DOCX 중 `generic` 또는 `unknown` 표가 많은 문서가 있다. 이 경우 표 분류 개선이 추출 품질에 직접 영향을 준다.
- 문항 후보 수와 최종 추출 문항 수가 큰 차이를 보이는 경우, 보기 코드나 숫자값의 오탐도 있지만 실제 누락도 섞일 수 있다.
- `SPSSCondition`은 기본적인 `Q=code`, `Q=1,2`, `Q1=1&Q2=2` 조건에는 유효하지만, 복잡한 부정 조건, 범위 조건, 파이핑 조건은 여전히 Researcher/DP 확인이 필요하다.
- UI 전체 클릭 플로우는 HTTP 200과 코드/산출물 수준으로 검증했다. Streamlit 파일 업로드부터 다운로드까지의 브라우저 자동화 E2E는 별도 구축하면 더 좋다.

## 9. 권장 Acceptance Criteria

### 문항 추출

- 커버리지 요약에서 `먼저 확인할 항목`이 0건이거나 연구원이 모두 확인 완료해야 한다.
- 문항 수는 연구원이 기대한 대략적 문항 수와 큰 차이가 없어야 한다.
- 선택형 문항의 `AnswerOptions`가 비어 있지 않아야 한다.
- `Filter`, `SkipLogic`, `Instructions`는 주요 ASK ONLY IF, TERMINATE, ROTATE 조건을 포함해야 한다.
- `SourceVariable`은 실제 DP/Syntax 변수명이 있는 경우 문항번호와 별도로 채워져야 한다.

### Table Guide / Banner

- Table Guide의 `ReviewStatus`가 핵심 분석 문항에서 `Ready for DP`여야 한다.
- `QAWarning`이 있는 행은 Researcher가 검토 후 수정해야 한다.
- Banner Spec의 모든 포인트는 `SourceQuestion`, `SourceVariable`, `HumanCondition`, `SPSSCondition`, `CodeLabels`를 가져야 한다.
- 기본 배너인 성, 연령, 소득수준은 원문에 존재하면 포함되는 것이 바람직하다.
- 배너 rationale은 한국어로 작성되어야 한다.

### Logic Checker

- `branch_coverage_percent`는 100%가 목표다.
- `Unparsed Conditions`는 0건이 이상적이다.
- Critical 항목이 있으면 Script 구현 전달 전에 수정해야 한다.
- Checklist는 `설문지 수정 필요`, `Script 구현 확인`, `링크 테스트 확인`으로 분리되어야 한다.

### DP 전달 파일

- 최종 DP 전달 파일은 `Table Guide`, `Banner Spec` 2개 시트만 포함해야 한다.
- `DP Review Status`가 `Needs Researcher Review`인 항목은 전달 전에 확인해야 한다.
- DP 전달 파일에는 실제 변수명과 SPSS-ready 조건이 포함되어야 한다.

## 10. 다음 개선 우선순위

1. 실제 LLM 추출 E2E 회귀 세트 구축
   - 대표 DOCX 3-5개와 기대 문항 수/핵심 문항/보기/필터 기준을 ground truth로 저장한다.
   - 네트워크가 되는 환경에서 주기적으로 전체 추출 품질을 측정한다.

2. 표 분류 품질 개선
   - `generic`, `unknown` 표 중 실제 보기표/매트릭스/제품 카드인 케이스를 샘플링한다.
   - 표 분류 규칙과 coverage summary의 우선순위를 개선한다.

3. UI E2E 자동화
   - Streamlit 업로드, 추출 버튼, 세션 저장, Table Guide 다운로드, Logic Checker 다운로드까지 자동화한다.
   - 다운로드된 Excel의 시트/헤더/핵심 셀을 자동 검증한다.

4. DP 조건식 고도화
   - `!=`, `NOT`, range, multi-punch, derived net 조건을 DP-ready 수준으로 더 명확히 분류한다.
   - 자동 변환이 어려운 조건은 `Needs Researcher Review`로 확실히 표시한다.

5. 리포트 자동 생성
   - 현재 검증 리포트 형식을 앱 내부 또는 CLI에서 자동 생성할 수 있게 하면 릴리즈 전 품질 확인이 쉬워진다.

## 11. 결론

현재 앱은 연구원이 설문지를 업로드해 문항을 검토하고, Table Guide/Banner Spec을 만들고, Logic Checker 결과를 DP/Script/Link Test 업무로 넘기는 기본 워크플로우를 지원한다.

이번 검증에서 출력물 구조는 DP 전달과 연구원 리뷰 관점에서 필요한 핵심 필드를 갖추고 있음을 확인했다. 특히 `SourceVariable`, `SPSSCondition`, `QAWarning`, `Rationale(KO)`, Logic Checker 업무 구분은 실무 활용도를 높이는 중요한 개선이다.

남은 핵심 리스크는 실제 LLM 추출 품질의 반복 검증과 복잡한 DOCX 표 구조 처리다. 따라서 다음 품질 개선은 ground truth 기반 E2E 추출 테스트와 표 분류 개선에 집중하는 것이 가장 효과적이다.
