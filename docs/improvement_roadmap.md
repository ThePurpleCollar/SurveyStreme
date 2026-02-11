# 🌊 Survey Stream — 핵심 기능 개선 로드맵

> **범위**: Questionnaire Analyzer + Table Guide Builder  
> **관점**: 코드 품질/아키텍처 · UI/UX · 알고리즘/로직 · 프롬프트 엔지니어링  
> **날짜**: 2026-02-10

---

## 1. Questionnaire Analyzer 개선안

### 1-A. 코드 품질 / 아키텍처

| # | 이슈 | 현재 상태 | 개선 방향 | 우선순위 |
|---|------|----------|----------|---------|
| A1 | **PDF↔DOCX 파이프라인 이원화** | PDF는 `postprocessor.py`(정규식만), DOCX는 `llm_extractor.py`(AI 하이브리드). 두 경로의 출력 포맷과 후처리 로직이 완전히 다름 | 공통 인터페이스 `QuestionExtractor` 추상 클래스를 만들고, PDF/DOCX 각각 구현체를 두되 출력은 동일한 `SurveyDocument`로 통일. PDF도 `SurveyQuestion` 객체를 생성하도록 변경 | 🔴 높음 |
| A2 | **SummaryType 중복 계산** | `postprocessor.py`의 `assign_summary_type()`/`update_summary_type()`과 `doc_analyzer.py`의 `_apply_postprocessing()`에 동일한 척도 매핑 로직이 2벌 존재 (`_SCALE_MAP`, `_scale_summary_type`) | 단일 함수 `compute_summary_type(question_type: str) -> str`을 `models/survey.py` 또는 별도 유틸에 정의하고, 모든 곳에서 이를 호출 | 🔴 높음 |
| A3 | **`_process_pdf` 함수 내 인라인 로직** | PDF 처리 시 `st.data_editor`까지 한 함수 안에서 실행. `survey_document` 세션 저장 없음 → 다른 페이지에서 PDF 결과 사용 불가 | PDF 경로에서도 `SurveyDocument` 생성 + 세션 저장. Tree View/Spreadsheet 표시 통일 | 🔴 높음 |
| A4 | **에러 핸들링 체계화** | LLM 호출 실패 시 `try/except`에서 `st.error()` 직접 호출. 재시도 로직 없음 | `services/llm_client.py`에 자동 재시도(exponential backoff) + 구조화된 예외 클래스 도입 | 🟡 중간 |
| A5 | **테스트 부재** | 단위 테스트 없음 (정규식 패턴, 후처리 로직, JSON 파싱 등) | `tests/` 디렉토리에 핵심 함수별 pytest 작성. 특히 `_normalize_question_type`, `_validate_question`, `assign_summary_type` | 🟡 중간 |

### 1-B. UI/UX 사용성

| # | 이슈 | 현재 상태 | 개선 방향 | 우선순위 |
|---|------|----------|----------|---------|
| B1 | **PDF 결과 편집 후 하류 연결 불가** | PDF는 `st.data_editor`에서 편집 가능하지만, 편집 결과가 `survey_document`로 변환되지 않아 Table Guide Builder 등에서 활용 불가 | PDF 편집 완료 후 "Confirm & Proceed" 버튼으로 `SurveyDocument` 생성 → 세션 저장 | 🔴 높음 |
| B2 | **추출 진행 상태의 정보 밀도** | 5단계 Phase 진행이 `st.status`에 텍스트로만 표시. 대용량 문서에서 어디까지 진행됐는지 체감 어려움 | 각 Phase에 예상 소요시간 표시 + 전체 진행률 바 추가 | 🟢 낮음 |
| B3 | **세션 복원 시 "다시 추출" 유도 부족** | 세션 로드 후 파일을 다시 업로드하면 이전 세션이 날아감 (경고 없음) | "기존 세션이 있습니다. 덮어쓰시겠습니까?" 확인 다이얼로그 | 🟡 중간 |
| B4 | **Tree View에서의 직접 편집** | Tree View는 읽기 전용. 수정은 Spreadsheet 탭으로 이동해야 함 | Tree View 각 문항 옆에 "Edit" 아이콘 → expander 내 편집 폼 제공 (또는 클릭 시 Spreadsheet 해당 행으로 스크롤) | 🟢 낮음 |

### 1-C. 알고리즘 / 로직 정확도

| # | 이슈 | 현재 상태 | 개선 방향 | 우선순위 |
|---|------|----------|----------|---------|
| C1 | **PDF 문항번호 정규식 한계** | `r'^([A-Za-z]+[a-z]*\d+[a-z]?(?:-\d+)*\|[A-Za-z]+\d+[A-Za-z])\.\s*(.*)'` — 순수 숫자 시작(`1.`, `2.`), 한글 접두사(`문항1.`), 점 없는 번호(`Q1 `) 미인식 | 정규식을 티어별로 분리: Tier 1(높은 신뢰) `[A-Z]+\d+\.`, Tier 2(중간) `\d+\.`, Tier 3(낮음) 문맥 기반. 각 티어별 신뢰도 점수 부여 | 🔴 높음 |
| C2 | **Grid 문항 행 복제 로직** | `duplicate_and_insert_rows`에서 `"Npt x M"` 패턴의 M값+1만큼 행 추가. 그러나 LLM이 Grid의 각 하위 항목을 별도 문항으로 추출하면 중복 발생 | LLM 추출 결과에서 이미 분리된 Grid 하위 항목이 있는지 확인 후, 없을 때만 행 복제. `SurveyQuestion`에 `is_grid_child` 플래그 추가 | 🟡 중간 |
| C3 | **LLM 추출 결과 병합 시 문항 순서** | `_merge_chunk_results`에서 `seen` dict로 중복 제거하지만, 청크 경계에서 같은 문항이 분할되었을 때 텍스트 병합이 단순 길이 비교만 수행 | 문항 텍스트 유사도 비교(레벤슈타인 또는 단어 겹침률) 추가. 일정 이상 유사하면 긴 쪽 채택, 아니면 별도 문항으로 유지 | 🟡 중간 |
| C4 | **비문항 필터링 안전망** | `_is_valid_question_number` 함수가 존재하지만, 실제 구현에서 어떤 패턴을 거부하는지 불명확. `RegionCode1`, `SegCode1` 등은 프롬프트에서만 제외 요청 | 화이트리스트(`Q`, `SQ`, `S`, `DQ`, `A`, `SC` 등 일반적 접두사) + 블랙리스트(camelCase, `Code`, `Step`, `Page` 등) 이중 필터 | 🟡 중간 |
| C5 | **`_normalize_question_type` 누락 패턴** | `OPEN/SA`, `SELECT ONE`, `SELECT ALL` 등 일부 복합형이 처리되지 않고 원본 그대로 통과 | 정규화 매핑 테이블 확장: `{"OPEN/SA": "OE", "SELECT ONE": "SA", "SELECT ALL": "MA", "SINGLE": "SA", "MULTIPLE": "MA"}` | 🟡 중간 |

### 1-D. 프롬프트 엔지니어링

| # | 이슈 | 현재 상태 | 개선 방향 | 우선순위 |
|---|------|----------|----------|---------|
| D1 | **SYSTEM_PROMPT의 FORMAT 예시 불균형** | Format A~E 5가지를 설명하지만, 실제 설문지에서 흔한 "Matrix/Grid 형식"(행=항목, 열=척도)에 대한 명시적 가이드 없음 | FORMAT F로 Matrix/Grid 패턴 추가: "Q5. 다음 각 항목에 대해 평가해주세요" + 표 형태의 척도 | 🔴 높음 |
| D2 | **answer_options 추출 품질** | 테이블 형태의 보기는 잘 추출되지만, 줄바꿈으로 나열된 보기(`1. 남자\n2. 여자`)는 LLM이 놓치는 경우 있음 | 프롬프트에 "보기는 다음 형태로도 나타날 수 있음: 번호+텍스트 줄바꿈 나열, 쉼표 구분, 탭 구분" 예시 추가 | 🟡 중간 |
| D3 | **청크 컨텍스트 부족** | 각 청크가 독립적으로 LLM에 전달되어 이전 청크의 문항 흐름 정보가 없음 | 이전 청크의 마지막 2~3 문항 번호/유형을 다음 청크 프롬프트에 컨텍스트로 주입: "이전 섹션의 마지막 문항: Q15(SA), Q16(MA)" | 🟡 중간 |
| D4 | **filter/skip_logic 추출 일관성** | `[PN: ASK IF Q1=1]`과 `Q1=1 응답자에게만 질문` 같은 자연어 필터를 동일하게 인식하지 못하는 경우 | 프롬프트에 한국어/영어 필터 패턴 예시 쌍 추가. "다음은 동일한 필터 조건의 다른 표현입니다" 섹션 | 🟡 중간 |

---

## 2. Table Guide Builder 개선안

### 2-A. 코드 품질 / 아키텍처

| # | 이슈 | 현재 상태 | 개선 방향 | 우선순위 |
|---|------|----------|----------|---------|
| A6 | **`pages/table_guide.py` 파일 크기** | 단일 파일에 6개 탭의 UI + 로직이 모두 포함 (추정 1000줄+). 읽기/유지보수 어려움 | 탭별로 `pages/table_guide/` 패키지로 분리: `titles.py`, `base_net.py`, `banner.py`, `sort_sub.py`, `special_instr.py`, `review.py` | 🟡 중간 |
| A7 | **`_sync_field_to_df_and_doc` 범용 헬퍼** | 좋은 패턴이지만, 각 탭에서 반복적으로 유사한 동기화 코드 작성 | `SurveyDocument`에 `update_field(question_number, field, value)` 메서드 추가. DataFrame↔Document 양방향 자동 동기화 | 🟡 중간 |
| A8 | **Excel 내보내기 로직의 위치** | `export_table_guide_excel`이 `table_guide_service.py`에 있으면서 `openpyxl` 직접 조작. 스타일 코드가 비즈니스 로직과 혼재 | `services/excel_exporter.py`로 분리. 스타일 상수/헬퍼를 별도 정의 | 🟢 낮음 |

### 2-B. UI/UX 사용성

| # | 이슈 | 현재 상태 | 개선 방향 | 우선순위 |
|---|------|----------|----------|---------|
| B5 | **6단계 탭의 순차 진행 강제력 부족** | 모든 탭이 동시에 접근 가능. Title 없이 Review로 가면 빈 결과 | 이전 단계 미완료 시 탭에 경고 배지 표시 + "이전 단계를 먼저 완료하세요" 안내. 단, 접근 자체는 허용(유연성 유지) | 🟡 중간 |
| B6 | **Banner Setup의 자동 추천 결과 확인** | Auto-Suggest 결과가 즉시 적용되지만, 사용자가 추천 근거를 이해하기 어려움 | 각 배너 추천에 "왜 이 문항이 배너로 적합한지" 한 줄 설명 표시. Intelligence 분석 결과와 연계 | 🟡 중간 |
| B7 | **Completeness Checklist 위치** | Review & Export 탭에서만 확인 가능 | 사이드바 또는 상단에 전체 완성도 미니 진행률 바를 항상 표시 | 🟢 낮음 |

### 2-C. 알고리즘 / 로직 정확도

| # | 이슈 | 현재 상태 | 개선 방향 | 우선순위 |
|---|------|----------|----------|---------|
| C6 | **Survey Intelligence 단일 호출** | 전체 설문지를 한 번의 LLM 호출로 분석. 100문항 이상에서 컨텍스트 윈도우 압박 | 문항 요약 → Intelligence 분석 2단계로 분리. 1단계에서 각 문항의 역할(screening/awareness/usage 등)을 먼저 태깅, 2단계에서 전체 구조 분석 | 🟡 중간 |
| C7 | **Net/Recode 자동 생성 정확도** | AI 기반이라 "기타(직접 기재)"를 Net에 포함시키거나, 논리적으로 맞지 않는 그룹핑이 발생할 수 있음 | 생성 후 검증 단계 추가: 보기 코드 존재 여부 확인, 중복 코드 검출, Top/Bottom Box 계산 검증 | 🟡 중간 |
| C8 | **TableNumber 충돌** | Grid 문항 행 복제 시 `_1`, `_2` 접미사로 구분하지만, 원본에 이미 `_`가 포함된 번호와 충돌 가능 | 구분자를 `_`에서 `.`이나 `-`로 변경하거나, 충돌 검사 로직 추가 | 🟢 낮음 |

### 2-D. 프롬프트 엔지니어링

| # | 이슈 | 현재 상태 | 개선 방향 | 우선순위 |
|---|------|----------|----------|---------|
| D5 | **Title 생성 프롬프트 — Survey Context 활용** | "When Survey Context is provided" 조건부 처리이지만, 컨텍스트가 주어져도 간혹 일반적인 제목 생성 | 컨텍스트에서 추출한 study_type과 연구 목적을 프롬프트 상단에 명시적으로 배치: "이 설문은 {study_type} 조사이며, 목적은 {objective}입니다" | 🟡 중간 |
| D6 | **Intelligence 프롬프트의 출력 안정성** | JSON 구조가 복잡해서 LLM이 가끔 필드를 누락하거나 잘못된 문항번호를 반환 | JSON Schema를 프롬프트에 더 명시적으로 포함. 각 필드에 "REQUIRED" / "OPTIONAL" 표시. 예시 출력도 실제 설문지 기반으로 작성 | 🟡 중간 |

---

## 3. 공통 / 횡단적 개선안

| # | 이슈 | 개선 방향 | 우선순위 |
|---|------|----------|---------|
| X1 | **LLM 호출 비용/시간 로깅** | 각 LLM 호출의 토큰 수, 소요 시간, 비용을 기록하는 `services/llm_logger.py` 추가. 디버깅과 최적화에 필수 | 🟡 중간 |
| X2 | **설정 하드코딩** | 모델명, 배치 크기, 청크 크기 등이 코드에 직접 기입. `.env` 또는 `config.py`로 통합 | 🟡 중간 |
| X3 | **다국어 프롬프트 관리** | 한국어/영어 시스템 프롬프트가 각 서비스 파일에 문자열 상수로 존재. 관리 어려움 | `prompts/` 디렉토리에 YAML 또는 별도 .txt 파일로 분리 | 🟢 낮음 |

---

## 4. 추천 실행 순서

### Phase 1 — 즉시 효과 (1~2주)
1. **A1 + A3 + B1**: PDF 파이프라인을 DOCX와 동일한 `SurveyDocument` 출력으로 통일 → 전체 앱 흐름 정상화
2. **A2**: SummaryType 중복 제거 → 유지보수성 대폭 향상
3. **C1**: PDF 정규식 패턴 강화 → PDF 추출 정확도 향상

### Phase 2 — 품질 도약 (2~3주)
4. **D1 + D2**: LLM 프롬프트에 Matrix/Grid 포맷 + 보기 패턴 추가 → DOCX 추출 정확도 향상
5. **C5 + C4**: question_type 정규화 + 비문항 필터링 강화
6. **B3 + B5**: 세션 덮어쓰기 경고 + Table Guide 탭 진행 안내

### Phase 3 — 아키텍처 정비 (3~4주)
7. **A4 + A5**: 재시도 로직 + 테스트 코드
8. **A6 + A7**: Table Guide 코드 분리 + Document 동기화 개선
9. **D3 + D4**: 청크 컨텍스트 주입 + 필터 패턴 프롬프트 보강

---

## 5. 작업 시작점 제안

**가장 임팩트가 큰 첫 번째 작업**: **A1 + A3 + B1 통합** (PDF↔DOCX 출력 통일)

이유:
- 현재 PDF로 업로드한 사용자는 Table Guide Builder, Quality Checker 등 후속 기능을 전혀 사용할 수 없음
- 이 하나의 변경으로 앱의 전체 가치가 PDF 사용자에게도 열림
- 코드 중복(A2)도 이 과정에서 자연스럽게 해소 가능
