import os
import streamlit as st
import pandas as pd

EXAMPLE_TEMPLATE_PATH = "template/SurveyStream_QnrTemplate_v1.docx"


def page_user_reference():
    st.title('Survey Stream 사용자 가이드')

    # 상단에 간단한 소개 카드
    st.markdown("""
        <div style="padding: 15px; border-radius: 10px; background-color: #e0f7fa; margin-bottom: 20px; border-left: 5px solid #08c7b4;">
        <h3 style="margin-top: 0;">Survey Stream에 오신 것을 환영합니다</h3>
        <p>이 가이드는 Survey Stream의 주요 기능과 사용 방법을 상세히 설명합니다.</p>
    </div>
    """, unsafe_allow_html=True)

    # 기능 개요 섹션 - 시각적 카드 형태로 구성
    st.markdown("### 주요 기능")

    # 기능별 카드 배치 (2행 3열)
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        <div style="padding: 15px; border-radius: 10px; background-color: #fafafa; height: 200px; border: 1px solid #b2dfdb;">
            <h4 style="color: #00796b; margin-top: 0;">Questionnaire Analyzer</h4>
            <p>설문지 파일(.docx)에서 문항 번호, 텍스트, 유형을 AI 기반으로 자동 추출합니다. 보기, 로직, 필터까지 추출합니다.</p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div style="padding: 15px; border-radius: 10px; background-color: #fafafa; height: 200px; border: 1px solid #b2dfdb;">
            <h4 style="color: #00796b; margin-top: 0;">Table Guide Builder</h4>
            <p>Questionnaire Analyzer 결과를 기반으로 완전한 Table Guide 문서를 생성합니다. Table Title, Net/Recode, Banner, Sort/SubBanner, Special Instructions를 AI + 알고리즘으로 자동 생성하고, 다중시트 Excel로 내보낼 수 있습니다.</p>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div style="padding: 15px; border-radius: 10px; background-color: #fafafa; height: 200px; border: 1px solid #b2dfdb;">
            <h4 style="color: #00796b; margin-top: 0;">Quality Checker</h4>
            <p>설문 문항의 품질 분석(모호한 표현, 이중 질문, 유도 질문 등)과 문법 교정을 두 개의 탭으로 통합 제공합니다.</p>
        </div>
        """, unsafe_allow_html=True)

    col4, col5, col6 = st.columns(3)

    with col4:
        st.markdown("""
        <div style="padding: 15px; border-radius: 10px; background-color: #fafafa; height: 200px; border: 1px solid #b2dfdb;">
            <h4 style="color: #00796b; margin-top: 0;">Length Estimator</h4>
            <p>설문 문항의 예상 응답 소요 시간을 AI가 산출하여, 전체 설문 길이를 최적화할 수 있도록 지원합니다.</p>
        </div>
        """, unsafe_allow_html=True)

    with col5:
        st.markdown("""
        <div style="padding: 15px; border-radius: 10px; background-color: #fafafa; height: 200px; border: 1px solid #b2dfdb;">
            <h4 style="color: #00796b; margin-top: 0;">Skip Logic</h4>
            <p>설문 문항 간의 스킵/분기 로직을 시각화하여 설문 흐름을 한눈에 파악하고 검증할 수 있습니다.</p>
        </div>
        """, unsafe_allow_html=True)

    with col6:
        st.write("")  # empty column for layout balance

    st.markdown("---")

    # 설문지 구성요소 식별 섹션 - 탭 인터페이스 적용
    st.markdown("### 설문지 구성요소 식별")
    st.write("""
    Survey Stream이 설문지 파일에서 주요 정보를 어떻게 인식하고 처리하는지 알아보세요.
    Questionnaire Analyzer는 아래 이미지와 같이 문항 번호, 텍스트, 유형을 자동으로 추출하여 분석의 기초를 마련합니다.
    """)
    # 이미지 추가 - 예외 처리 개선
    try:
        st.image("https://i.imgur.com/pDKxyiV.png", caption='예시: 문항 번호, 문항 텍스트, 문항 유형', use_container_width=False)
    except Exception as e:
        st.error(f"이미지를 불러올 수 없습니다: {e}")

    st.info("아래 탭을 클릭하여 각 구성요소의 **인식 규칙**과 **자동 생성 방식**을 자세히 확인하세요.", icon="👇")

    # 탭 인터페이스로 구분
    tab1, tab2, tab3, tab4 = st.tabs(["문항 번호 인식", "문항 유형 인식", "분석 유형 생성", "자동 행 추가"])

    with tab1:
        st.markdown("""
        <div style="padding: 15px; border-radius: 5px; background-color: #fafafa;">
            <h4 style="margin-top: 0;">문항 번호 인식</h4>
            <p>문항 번호는 일반적으로 알파벳, 숫자, 하이픈(-)의 조합으로 시작하며, 마침표(.)로 끝납니다. 각 문항을 고유하게 식별하는 데 사용됩니다.</p>
            <ul>
                <li>알파벳/숫자/기호 조합 + 마침표(.)</li>
            </ul>
            <p><strong>인식 예시:</strong> <code>Q1.</code>, <code>SQ1a.</code>, <code>A1-1.</code>, <code>문항1.</code></p>
            <p><small><i>참고: 문항 텍스트 시작 부분에서 이 패턴을 찾아 인식합니다.</i></small></p>
        </div>
        """, unsafe_allow_html=True)

    with tab2:
        st.markdown("""
        <div style="padding: 15px; border-radius: 5px; background-color: #fafafa;">
            <h4 style="margin-top: 0;">문항 유형 인식</h4>
            <p>문항 텍스트 끝 부분에 대괄호 <code>[ ]</code> 또는 소괄호 <code>( )</code> 안에 명시된 특정 키워드를 통해 문항 유형을 인식합니다.</p>
        </div>
        """, unsafe_allow_html=True)

        # 테이블 형식으로 문항 유형 정보 제공
        data = {
            "유형 구분": ["단수 응답", "복수 응답", "주관식 (문자)", "주관식 (숫자)", "척도형 (일반/Grid)", "순위형"],
            "인식 키워드 (괄호 안)": ["SA, 단수, SELECT ONE", "MA, 복수, SELECT ALL", "OE, OPEN, 오픈, OPEN/SA", "NUMERIC", "SCALE, PT, 척도", "TOP, RANK, 순위"],
            "인식 예시": ["[SA]", "(복수)", "[OE]", "(NUMERIC)", "[5pt x 7]", "(Top 3)"]
        }

        df = pd.DataFrame(data)
        st.table(df)
        st.markdown("<small><i>참고: 키워드는 대소문자를 구분하지 않습니다. 척도형/순위형의 경우 숫자(예: 5pt, Top 3) 정보도 함께 인식합니다.</i></small>", unsafe_allow_html=True)

    with tab3:
        st.markdown("""
        <div style="padding: 15px; border-radius: 5px; background-color: #fafafa;">
            <h4 style="margin-top: 0;">분석 유형 (SummaryType) 생성</h4>
            <p>인식된 '문항 유형(QuestionType)'을 기반으로, 테이블 결과표에 표시될 분석 지표(예: %, 평균 등)를 나타내는 '분석 유형(SummaryType)'이 자동으로 생성됩니다.</p>
        </div>
        """, unsafe_allow_html=True)

        # 분석 유형 정보 - 표 형식으로 정리
        data = {
            "문항 유형 (예시)": ["SA, MA, OE", "NUMERIC", "N점 척도 (예: 5점)", "Grid 척도 (예: 5점x7개)", "순위형 (예: Top 3)"],
            "자동 생성되는 분석 유형 (SummaryType)": [
                "%",
                "%, mean",
                "%/Top2(4+5)/Mid(3)/Bot2(1+2)/Mean",
                "Summary Top2%, Summary Mean, 각 항목 % (자동 행 추가됨)",
                "각 순위 누적 % (1st, 1st+2nd, 1st+2nd+3rd) (자동 행 추가됨)"
            ]
        }

        df = pd.DataFrame(data)
        st.table(df)
        st.markdown("<small><i>참고: N점 척도의 Top/Mid/Bot 구분은 점수에 따라 달라집니다(4점, 5점, 6점, 7점, 10점 기준 내장). 사용자는 생성된 값을 수정할 수 있습니다.</i></small>", unsafe_allow_html=True)

    with tab4:
        st.markdown("""
        <div style="padding: 15px; border-radius: 5px; background-color: #fafafa;">
            <h4 style="margin-top: 0;">자동 행 추가</h4>
            <p>'Grid 척도형'과 '순위형' 문항의 경우, 분석에 필요한 추가 행이 원본 문항 아래에 자동으로 생성됩니다.</p>
        </div>
        """, unsafe_allow_html=True)

        # 두 개의 열로 나누어 정보 제공
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("""
            <div style="padding: 10px; border-radius: 5px; background-color: #e0f2f1; margin-top: 10px;">
                <h5 style="margin-top: 0;">Grid 척도형 문항 (예: `[5pt x 7]`)</h5>
                <p>Grid의 전체 요약(Top2, Mean 등)과 개별 속성 결과를 보기 위한 행이 추가됩니다.</p>
                <ul>
                    <li><b>원본 행:</b> 문항 정보 표시</li>
                    <li><b>추가 행 1:</b> 요약 (Summary Top2%)</li>
                    <li><b>추가 행 2:</b> 요약 (Summary Mean)</li>
                    <li><b>추가 행 3~N:</b> 각 속성별 결과 (%)</li>
                </ul>
                <pre style="background-color: #f5f5f5; padding: 8px; border-radius: 3px;">
Q5_1: Summary Top2%
Q5_2: Summary Mean
Q5_3: 항목1 %
Q5_4: 항목2 %
...
Q5_9: 항목7 %</pre>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            st.markdown("""
            <div style="padding: 10px; border-radius: 5px; background-color: #e0f2f1; margin-top: 10px;">
                <h5 style="margin-top: 0;">순위형 문항 (예: `[Top 3]`)</h5>
                <p>각 순위별 응답 및 누적 응답 결과를 보기 위한 행이 추가됩니다.</p>
                <ul>
                    <li><b>원본 행:</b> 문항 정보 표시</li>
                    <li><b>추가 행 1:</b> 1순위 (%)</li>
                    <li><b>추가 행 2:</b> 1+2순위 누적 (%)</li>
                    <li><b>추가 행 3:</b> 1+2+3순위 누적 (%)</li>
                </ul>
                <pre style="background-color: #f5f5f5; padding: 8px; border-radius: 3px;">
Q6_1: 1st
Q6_2: 1st+2nd
Q6_3: 1st+2nd+3rd</pre>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("<small><i>참고: 자동 추가된 행의 'TableNumber'는 원본 문항 번호에 `_숫자`가 붙는 형식(예: Q5_1, Q5_2)으로 자동 생성됩니다.</i></small>", unsafe_allow_html=True)

    st.markdown("---")

    # DOCX AI 추출 섹션
    st.markdown("### DOCX AI 추출 기능")
    st.write("""
    DOCX 파일을 업로드하면 AI 기반 하이브리드 추출이 활성화됩니다.
    패턴 인식으로 문항번호/유형을 즉시 추출한 후, LLM이 검증하고 응답 보기, 스킵 로직, 필터 등 추가 필드를 완성합니다.
    """)

    tab_docx1, tab_docx2, tab_docx3 = st.tabs(["추출 항목", "사용 방법", "결과 보기"])

    with tab_docx1:
        st.markdown("""
        <div style="padding: 15px; border-radius: 5px; background-color: #fafafa;">
            <h4 style="margin-top: 0;">DOCX에서 추출되는 항목</h4>
        </div>
        """, unsafe_allow_html=True)

        docx_fields = {
            "항목": [
                "문항 번호 (QuestionNumber)",
                "질문 텍스트 (QuestionText)",
                "문항 유형 (QuestionType)",
                "응답 보기 (AnswerOptions)",
                "스킵 로직 (SkipLogic)",
                "필터 (Filter)",
                "지시문 (Instructions)",
            ],
            "설명": [
                "Q1, SQ1a, A1-1 등 문항 식별자",
                "질문 본문 텍스트",
                "SA, MA, OE, NUMERIC, SCALE, RANK, GRID 등",
                "1.매우 그렇다 | 2.그렇다 | 3.보통 등 개별 보기 목록",
                "조건부 이동 (예: Q1=3 → Q5로 이동)",
                "응답 대상 조건 (예: Q2=3,4 응답자만)",
                "면접원 지시문 (예: SHOW CARD, 보기 로테이션)",
            ],
            "추출 방식": [
                "패턴 + AI 검증",
                "패턴 + AI 검증",
                "패턴 + AI 검증",
                "AI 추출",
                "AI 추출",
                "AI 추출",
                "AI 추출",
            ]
        }
        st.table(pd.DataFrame(docx_fields))

    with tab_docx2:
        st.markdown("""
        <div style="padding: 15px; border-radius: 5px; background-color: #fafafa;">
            <h4 style="margin-top: 0;">DOCX 추출 사용 방법</h4>
            <ol>
                <li>사이드바에서 <b>.docx</b> 파일을 업로드합니다.</li>
                <li>Questionnaire Analyzer 페이지에서 <b>'Extract Questions with AI'</b> 버튼을 클릭합니다.</li>
                <li>AI가 자동으로 문항을 추출합니다. 진행률이 표시되며, 완료 후 결과가 Tree View와 Spreadsheet 탭에 나타납니다.</li>
                <li>CSV 또는 <b>Excel(.xlsx)</b> 형식으로 다운로드할 수 있습니다.</li>
                <li><b>Save Session</b>으로 추출 결과를 JSON 파일로 저장하면 다음에 재추출 없이 불러올 수 있습니다.</li>
            </ol>
        </div>
        """, unsafe_allow_html=True)

    with tab_docx3:
        st.markdown("""
        <div style="padding: 15px; border-radius: 5px; background-color: #fafafa;">
            <h4 style="margin-top: 0;">결과 보기 방식</h4>
            <p>DOCX 추출 결과는 두 가지 탭으로 제공됩니다:</p>
            <ul>
                <li><b>Tree View:</b> 각 문항을 펼칠 수 있는 계층 구조로 표시합니다. 보기 목록, 스킵 로직, 필터, 지시문 등을 시각적으로 확인할 수 있습니다.</li>
                <li><b>Spreadsheet:</b> 전체 문항을 편집 가능한 테이블로 표시합니다. 직접 수정 후 다운로드할 수 있습니다.</li>
            </ul>
            <p><b>다운로드 옵션:</b></p>
            <ul>
                <li><b>CSV:</b> 기존과 동일한 flat 형식 (모든 컬럼 포함)</li>
                <li><b>Excel:</b> 시트 1에 메인 문항 테이블, 시트 2에 응답 보기 flat 테이블 (QuestionNumber, OptionCode, OptionLabel)</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # 팁과 자주 묻는 질문 섹션 추가
    st.markdown("### 사용 팁 및 주의사항")

    # 확장 가능한 FAQ 섹션
    with st.expander("더 정확한 분석 결과를 얻으려면? (설문지 작성 가이드)"):
        st.markdown("""
        - **문항 번호:** 각 문항 시작 시 `Q1.`, `SQ1a.` 와 같이 명확하게 작성하고 **마침표(.)**로 마무리해주세요.
        - **문항 유형:** 문항 텍스트 끝에 `[SA]`, `(MA)`, `[5pt x 7]`, `(Top 3)` 와 같이 **대괄호 `[]` 또는 소괄호 `()`** 안에 표준 키워드를 명확히 표기해주세요. (위에 설명된 키워드 참고)
        - **일관성:** 파일 전체에서 문항 번호와 유형 표기 방식을 일관되게 유지하는 것이 좋습니다.
        """)

    with st.expander("주의사항"):
        st.markdown("""
        - **인식 오류:** 문항 번호나 유형 표기가 불명확하거나 누락된 경우, 해당 문항의 정보가 정확히 추출되지 않거나 `Questionnaire Analyzer` 결과 테이블에서 직접 수정해야 할 수 있습니다.
        - **AI 결과:** `Table Guide Builder`와 `Quality Checker` 등 AI 기반 기능의 결과는 항상 사용자가 검토 후 필요시 수정하는 것을 권장합니다.
         """)

    with st.expander("추천 작업 흐름"):
        st.markdown("""
        1.  **파일 업로드:** 사이드바에서 설문지 파일 (`.docx`)을 업로드합니다.
        2.  **Questionnaire Analyzer:**
            - 'Extract Questions with AI' 버튼을 클릭하면 AI가 자동으로 추출합니다. 문항 번호, 텍스트, 유형뿐만 아니라 보기, 로직, 필터, 지시문까지 추출됩니다.
            - 결과를 Spreadsheet(편집 가능 테이블)에서 확인합니다. 상세 카드뷰는 하단 Tree View expander에서 열 수 있습니다.
            - 필요시 테이블 내에서 직접 수정할 수 있습니다.
            - 하단의 `Download CSV` 또는 `Download Excel` 버튼으로 결과를 저장합니다.
            - **Save Session**으로 추출 결과를 저장해두면 나중에 재추출 없이 불러올 수 있습니다.
        3.  **Table Guide Builder:** 6개 탭을 순서대로 진행합니다.
            - **Table Titles**: 언어 선택 → `Generate Titles`로 테이블 제목 생성
            - **Net/Recode**: `Generate`로 Net/Recode 제안 생성
            - **Banner Setup**: `Auto-Suggest`로 배너 후보 자동 감지, 수동 추가/편집 가능
            - **Sort & SubBanner**: `Auto-Generate`로 정렬 규칙 + SubBanner 자동 생성
            - **Special Instructions**: `Auto-Generate`로 로테이션/파이핑 등 프로그래밍 지시사항 감지
            - **Review & Export**: 완성도 체크리스트 확인 → `Compile Table Guide` → Excel/CSV/Session 다운로드
        4.  **Quality Checker:**
            - **Quality Analysis 탭**: 언어 선택 → `Analyze Quality`로 문항 품질 분석 (모호한 표현, 이중 질문 등 감지)
            - **Grammar Correction 탭**: 언어 선택 → `Grammar Check`로 문법 교정 수행. 원본↔교정 비교 뷰에서 확인 후 `Apply Edits`로 반영합니다.
        5.  **Length Estimator / Skip Logic:** Questionnaire Analyzer 추출 결과를 기반으로 추가 분석을 수행합니다.
        6.  **결과 활용:** 다운로드한 CSV/Excel 파일을 후속 작업(예: 통계 분석 툴, 보고서 작성)에 활용합니다.
        """)

    # 예제 설문지 다운로드 섹션
    st.markdown("""
    <div style="padding: 15px; border-radius: 10px; background-color: #e0f7fa; margin: 20px 0; text-align: center;">
        <h4 style="margin-top: 0;">시작하기</h4>
        <p>아래 예제 설문지(DOCX)를 다운로드하여 Survey Stream의 기능을 직접 테스트해보세요.</p>
    </div>
    """, unsafe_allow_html=True)

    # 파일 존재 여부 확인 및 예외 처리 강화
    if os.path.exists(EXAMPLE_TEMPLATE_PATH):
        try:
            with open(EXAMPLE_TEMPLATE_PATH, "rb") as file:
                centered_col = st.columns([1, 2, 1])[1]
                with centered_col:
                    st.download_button(
                        label="예제 설문지 다운로드 (DOCX)",
                        data=file,
                        file_name=os.path.basename(EXAMPLE_TEMPLATE_PATH),
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True,
                        key="download_example_docx"
                    )
        except Exception as e:
            st.error(f"예제 설문지 파일을 읽는 중 오류 발생: {e}")
    else:
        st.warning(f"예제 설문지 파일을 찾을 수 없습니다: {EXAMPLE_TEMPLATE_PATH}")

    # 하단 푸터
    st.markdown("""
    <div style="text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #eeeeee;">
        <p style="color: #666666; font-size: 0.9em;">&copy; 2024 Survey Stream</p>
    </div>
    """, unsafe_allow_html=True)
