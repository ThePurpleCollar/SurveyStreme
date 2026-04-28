import pandas as pd
import streamlit as st


def _table(rows: list[dict]):
    st.table(pd.DataFrame(rows))


def _step(number: int, title: str, body: str):
    st.markdown(f"### {number}. {title}")
    st.markdown(body)


def page_user_reference():
    st.title("도움말 & 사용자 가이드")
    st.caption("현재 구현된 Streamlit 앱 기준의 사용자 워크플로우입니다.")

    st.info(
        "Survey Stream은 연구원이 DOCX 설문지를 업로드해 문항을 추출하고, "
        "Table Guide/Banner Spec을 만든 뒤, DP팀과 Script/Link Test 담당자에게 "
        "검토 가능한 산출물을 전달하는 흐름으로 설계되어 있습니다.",
        icon="ℹ️",
    )

    _table([
        {
            "순서": "1",
            "화면": "Sidebar",
            "사용자가 하는 일": ".docx 설문지 또는 저장된 .json 세션 업로드",
            "결과": "작업 세션 시작 또는 복원",
        },
        {
            "순서": "2",
            "화면": "Questionnaire Analyzer",
            "사용자가 하는 일": "Study Brief 입력 후 AI 문항 추출 실행",
            "결과": "문항, 보기, 필터, 스킵 로직, 지시문 추출",
        },
        {
            "순서": "3",
            "화면": "Questionnaire Analyzer",
            "사용자가 하는 일": "추출 점검 리포트와 Spreadsheet 검토/수정",
            "결과": "후속 작업에 사용할 확정 문항 테이블",
        },
        {
            "순서": "4",
            "화면": "Table Guide Builder",
            "사용자가 하는 일": "Study Brief 확인, Table Title/Banner 생성",
            "결과": "Table Guide 초안과 Banner Spec 초안",
        },
        {
            "순서": "5",
            "화면": "Table Guide Builder > 다운로드",
            "사용자가 하는 일": "DP Handoff 검증 후 Excel 다운로드",
            "결과": "DP 전달용 2-sheet Excel, 내부 리뷰용 Excel",
        },
        {
            "순서": "6",
            "화면": "Logic Checker",
            "사용자가 하는 일": "QA 분석 실행, 로직/분기/체크리스트 확인",
            "결과": "Script 구현 및 링크 테스트 확인 항목 Excel",
        },
    ])

    st.divider()

    _step(
        1,
        "파일 업로드 또는 세션 복원",
        """
사이드바의 **파일 업로드 (.docx / .json)** 영역에서 작업을 시작합니다.

- 새 설문지를 분석할 때는 `.docx` 파일을 업로드합니다.
- 이전 작업을 이어서 할 때는 저장해둔 `_session.json` 파일을 업로드합니다.
- 이미 세션이 있는 상태에서 다른 파일을 올리면 세션 덮어쓰기 확인 창이 표시됩니다.
- 세션이 복원되면 Questionnaire Analyzer, Table Guide Builder, Logic Checker를 바로 사용할 수 있습니다.
""",
    )

    _step(
        2,
        "Questionnaire Analyzer에서 문항 추출",
        """
`.docx` 파일을 업로드하면 Questionnaire Analyzer에서 **AI로 문항 추출 시작** 버튼을 눌러 추출을 실행합니다.
추출 전 Study Brief에 Client Brand와 Study Objective를 입력하면 Survey Intelligence와 후속 Table Guide 품질이 좋아집니다.

처리 단계는 화면에 스트리밍 형태로 표시됩니다.

1. DOCX 구조 파싱: 섹션, 단락, 표, 병합 셀, 취소선, 텍스트박스, 표 유형을 읽습니다.
2. DOCX Preflight: 문항 후보, 문항유형 표기율, 보기표/매트릭스/일반표 리스크를 보여줍니다.
3. 문항 패턴 스캔 및 청크 분할: AI 처리 전 문항 후보를 빠르게 확인합니다.
4. AI 문항 추출: 문항번호, SourceVariable, 질문문, 문항유형, 보기, 필터, 스킵 로직, 지시문을 추출합니다.
5. Survey Intelligence 분석: 조사 유형, 조사 목적, 주요 세그먼트를 추정합니다.
""",
    )

    with st.expander("추출되는 주요 필드", expanded=False):
        _table([
            {"필드": "QuestionNumber", "의미": "문서에 표시된 문항 번호입니다. 예: SC1, Q1, B3"},
            {"필드": "SourceVariable", "의미": "DP/Syntax에서 사용할 원천 변수명입니다. 비어 있으면 문항번호가 기본값으로 사용됩니다."},
            {"필드": "QuestionText", "의미": "질문 본문입니다. Table Title과 Logic Checker의 핵심 입력입니다."},
            {"필드": "QuestionType", "의미": "SA, MA, OE, NUMERIC, 5pt, Top 3, 5pt x 7 등 문항 유형입니다."},
            {"필드": "AnswerOptions", "의미": "보기 코드와 라벨입니다. Banner 조건과 CodeLabels 생성에 사용됩니다."},
            {"필드": "Filter", "의미": "응답 대상 조건입니다. 예: ASK ONLY IF SC1=1"},
            {"필드": "SkipLogic", "의미": "조건부 이동/종료 로직입니다. Logic Checker의 핵심 입력입니다."},
            {"필드": "Instructions", "의미": "로테이션, 파이핑, 단독 보기, SHOW CARD 등 Script 구현 지시사항입니다."},
        ])

    _step(
        3,
        "추출 결과 점검 및 Spreadsheet 수정",
        """
추출이 끝나면 먼저 **추출 결과 점검**을 확인합니다.
이 화면은 개발자 로그가 아니라 연구원이 우선 확인해야 할 리스크를 요약합니다.

- 문항 커버리지가 낮으면 실제 문항 누락 가능성을 확인합니다.
- 보기 커버리지는 보기 코드/라벨이 충분히 추출되었는지 확인합니다.
- 필터와 스킵 로직은 후속 Script 구현과 링크 테스트 품질에 직접 영향을 줍니다.
- 참고 항목에는 보기 코드, 나이, TV 사이즈, 가격값처럼 문항처럼 보이지만 실제 문항이 아닐 수 있는 항목도 포함됩니다.

그 다음 Spreadsheet에서 잘못된 값을 직접 수정합니다. 특히 `SourceVariable`, `QuestionType`, `AnswerOptions`, `Filter`, `SkipLogic`, `Instructions`를 우선 확인하세요.
""",
    )

    with st.expander("DOCX 작성 권장 구조", expanded=False):
        st.markdown(
            """
아래처럼 문항번호, 변수명, 문항유형, 필터/스킵, 보기 코드를 일관되게 작성하면 추출 정확도가 높아집니다.

```text
[SC1. AGE (SA)]
[PN: ASK ALL]
[PN: QUOTA CHECK]
What is your age?

18-24 years old | 1 | QUOTA CHECK
25-34 years old | 2 | QUOTA CHECK
35-44 years old | 3 | QUOTA CHECK
45-54 years old | 4 | QUOTA CHECK
55 years old or older | 5 | QUOTA CHECK

[Q1. KEY BUYING FACTORS (MA)]
[PN: ASK ONLY IF SC1=1,2,3,4,5]
[PN: ROTATE]
Which of the following are important when choosing your next TV?

Picture quality | 1
Price | 2
Brand | 3
Smart features | 4
Design | 5
```

핵심은 문항번호, SourceVariable, 문항유형, Script 지시문, 보기 코드가 서로 분리되어 보이도록 쓰는 것입니다.
"""
        )

    _step(
        4,
        "세션 저장 및 Analyzer 결과 다운로드",
        """
추출 결과를 검토한 뒤에는 세션을 저장하는 것이 좋습니다.

- 사이드바 또는 추출 완료 화면의 **세션 저장** 버튼으로 `_session.json`을 내려받습니다.
- 저장한 JSON을 다시 업로드하면 AI 재추출 없이 같은 상태를 복원할 수 있습니다.
- Questionnaire Analyzer 하단 다운로드 버튼에서 CSV/Excel 형태로 추출 결과를 받을 수 있습니다.
- Analyzer Excel은 문항 테이블, 보기 목록, Banner Layout, Net Recode Spec 등 후속 검토에 필요한 시트를 포함합니다.
""",
    )

    st.divider()

    _step(
        5,
        "Table Guide Builder에서 Study Brief 확인",
        """
Table Guide Builder는 Questionnaire Analyzer의 확정 문항 테이블을 사용합니다.
먼저 앱이 추정한 Study Brief를 확인하고 필요하면 수정합니다.

확인할 항목:

- Client Brand
- Study Type
- Study Objective
- Research Objectives
- Key Segments

이 정보는 Table Title과 Banner 생성에 직접 사용됩니다. 조사 목적이 잘못 잡히면 제목과 배너가 질문문을 기계적으로 요약하는 방향으로 흐를 수 있습니다.
""",
    )

    _step(
        6,
        "Table Title 생성 및 검토",
        """
출력 언어를 선택한 뒤 **Table Titles**를 생성합니다.
현재 구현은 질문문만 요약하지 않고 다음 정보를 함께 사용합니다.

- Survey Intelligence와 Study Brief
- SourceVariable과 QuestionNumber
- 질문문, 문항유형, 보기 코드/라벨
- 필터, 스킵 로직, 로테이션/파이핑 등 지시문
- 문항 역할, 변수 유형, 분석 가치

생성 후 편집 테이블에서 어색한 제목을 수정할 수 있습니다. 앱은 `Key Buying Factors`, `Purchase Intent`, `Aided Brand Awareness`, `Brand Consideration`, `Main Brand` 같은 마케팅 리서치 표준 표현을 우선하도록 후처리합니다.
""",
    )

    with st.expander("Table Title 예시", expanded=False):
        _table([
            {"질문 의도": "구매/선택 시 중요한 요소", "권장 Table Title": "Key Buying Factors"},
            {"질문 의도": "향후 구매 가능성/의향", "권장 Table Title": "Purchase Intent"},
            {"질문 의도": "인지 브랜드", "권장 Table Title": "Aided Brand Awareness"},
            {"질문 의도": "고려 브랜드", "권장 Table Title": "Brand Consideration"},
            {"질문 의도": "현재 보유/사용 브랜드", "권장 Table Title": "Main Brand"},
        ])

    _step(
        7,
        "Banner 생성 및 편집",
        """
필요하면 **Banner (Beta)**를 선택해 배너를 생성합니다.
배너는 단순히 문항을 나열하는 것이 아니라, 모든 테이블을 읽을 분석 축을 설계하는 단계입니다.

검토 포인트:

- 성별, 연령, 소득수준처럼 기본적으로 필요한 인구통계 축이 포함되었는지 확인합니다.
- 핵심 타깃, 브랜드 사용자, 구매 의향자, 사용 행태, 태도 세그먼트가 필요한지 확인합니다.
- 각 Banner Point의 조건이 실제 보기 코드와 맞는지 확인합니다.
- `Rationale(KO)`는 왜 해당 배너가 필요한지 한국어로 설명합니다.
- 필요 없는 배너 값은 제외하거나 삭제하고, 필요한 값은 수동으로 추가합니다.
""",
    )

    _step(
        8,
        "DP 전달 파일 다운로드",
        """
다운로드 탭에서 **Table Guide 컴파일**을 실행한 뒤 파일을 내려받습니다.
다운로드 직전 DP Handoff 검증 메시지를 확인합니다.

- 문제가 없으면 Ready for DP 상태로 안내됩니다.
- 확인 필요 항목이 있으면 Table Guide 또는 Banner Spec에서 수정한 뒤 다시 컴파일합니다.
""",
    )

    with st.expander("다운로드 파일 구성", expanded=False):
        _table([
            {
                "파일": "내부 리뷰용 Table Guide Excel",
                "대상": "Researcher",
                "내용": "Cover, Table Guide, Banner Spec, Banner Layout, Net Recode Spec, Answer Options",
            },
            {
                "파일": "DP Handoff Excel",
                "대상": "DP팀",
                "내용": "Table Guide, Banner Spec 2개 시트. SPSS Syntax와 Tabulation 작업의 기준 문서입니다.",
            },
            {
                "파일": "CSV",
                "대상": "Researcher",
                "내용": "간단한 리뷰나 다른 도구 연동을 위한 flat table입니다.",
            },
            {
                "파일": "Session JSON",
                "대상": "작업자",
                "내용": "현재 Table Guide 작업 상태를 저장하고 이어서 작업할 때 사용합니다.",
            },
        ])

    st.divider()

    _step(
        9,
        "Logic Checker로 Script/링크 테스트 리스크 점검",
        """
Table Guide 전달 전후로 **Logic Checker**에서 `QA 분석 실행`을 눌러 설문 흐름을 점검합니다.
Logic Checker는 LLM 없이 알고리즘으로 실행되며, 다음 결과를 제공합니다.
""",
    )

    _table([
        {
            "탭": "로직 시각화",
            "사용 목적": "스킵 로직, 필터 조건, 순차 진행을 그래프와 표로 확인합니다.",
            "누가 보나": "Researcher / Script",
        },
        {
            "탭": "분기 테스트",
            "사용 목적": "스킵 분기를 커버하는 필수 테스트 시나리오를 확인합니다.",
            "누가 보나": "Researcher / Link Test",
        },
        {
            "탭": "응답자 경로",
            "사용 목적": "대표 타깃, 비타깃, 탈락 응답자의 예상 경로를 확인합니다.",
            "누가 보나": "Researcher / Link Test",
        },
        {
            "탭": "체크리스트",
            "사용 목적": "설문지 수정 필요, Script 구현 확인, 링크 테스트 확인 항목을 업무별로 봅니다.",
            "누가 보나": "Researcher / Script / Link Test",
        },
    ])

    with st.expander("Logic Checker Excel 구성", expanded=False):
        st.markdown(
            """
`Logic Checker 결과 다운로드 (Excel)` 파일에는 다음 시트가 포함됩니다.

- **Summary**: 전체 상태, 분기 커버리지, 업무 구분별 확인 항목 수
- **Logic Map**: 기준 문항, 조건, 대상 문항, 확인 포인트
- **Branch Test**: 링크 테스트에 사용할 분기 테스트 시나리오
- **Respondent Paths**: 대표 응답자 유형별 예상 경로
- **Checklist**: 담당, 업무 구분, 심각도, 문항, 상세, 기대 동작, 메모
- **Unparsed**: 자동 파싱이 어려운 조건과 수동 확인 방법
"""
        )

    st.divider()

    _step(
        10,
        "최종 전달 전 확인",
        """
최종 전달 전에는 아래 순서로 확인하는 것을 권장합니다.

1. 문항 수와 주요 스크리너/본조사 문항이 누락되지 않았는지 확인합니다.
2. SourceVariable이 DP/Syntax에서 사용할 변수명과 맞는지 확인합니다.
3. 문항유형과 보기 코드가 실제 설문지와 맞는지 확인합니다.
4. Table Title이 질문 직역이 아니라 조사 도메인에서 쓰는 표현인지 확인합니다.
5. Banner 조건과 CodeLabels가 실제 보기 코드와 맞는지 확인합니다.
6. DP Handoff Excel의 확인 필요 항목이 남아 있지 않은지 확인합니다.
7. Logic Checker의 Script 구현 확인/링크 테스트 확인 항목을 담당자에게 전달합니다.
""",
    )

    st.warning(
        "AI가 생성한 결과는 최종 산출물이 아니라 초안입니다. "
        "문항 추출, Table Title, Banner 조건, DP 전달 파일은 반드시 연구원이 검토한 뒤 전달하세요.",
        icon="⚠️",
    )
