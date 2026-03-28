"""Survey Quality Checker UI 페이지.

Quality Analysis 탭과 Grammar Correction 탭을 통합 제공한다.
- Quality Analysis: SurveyDocument 문항의 품질 분석 (대시보드 + 이슈 카드)
- Grammar Correction: 문항 문법 교정 (비교 뷰 + 편집 테이블)
"""

import streamlit as st

from services.llm_client import MODEL_QUALITY_CHECKER
from services.quality_checker import (
    check_survey_quality,
    QuestionQualityResult,
    CATEGORY_LABELS,
    SEVERITY_LABELS,
    CATEGORIES,
    SEVERITIES,
)
from services.grammar_checker import check_grammar, apply_grammar_results
from ui.download import render_download_buttons
from typing import List


def page_quality_checker():
    st.title("Quality Checker")

    # ── 탭 구조 (guard는 각 탭 내부에서 개별 적용) ──
    tab_quality, tab_grammar = st.tabs(["Quality Analysis", "Grammar Correction"])

    with tab_quality:
        _render_quality_analysis_tab()

    with tab_grammar:
        _render_grammar_correction_tab()


# ============================================================
# Quality Analysis 탭
# ============================================================

def _render_quality_analysis_tab():
    """기존 Quality Analysis 로직."""
    # Guard: survey_document 필요
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning(
            '먼저 Questionnaire Analyzer에서 문서를 처리해주세요.',
            icon="⚠️",
        )
        return

    survey_doc = st.session_state["survey_document"]
    questions = survey_doc.questions
    if not questions:
        st.warning("문서에서 문항을 찾을 수 없습니다.", icon="⚠️")
        return

    st.info(
        f"**{survey_doc.filename}**에서 **{len(questions)}**개 문항을 발견했습니다. "
        "언어를 선택하고 **품질 분석** 버튼을 눌러주세요.",
        icon="ℹ️",
    )

    ctrl_col1, ctrl_col2 = st.columns([1, 3])
    with ctrl_col1:
        language = st.selectbox(
            "분석 언어",
            options=["ko", "en"],
            format_func=lambda x: "한국어" if x == "ko" else "English",
        )
    with ctrl_col2:
        st.write("")  # spacing
        st.write("")
        analyze_clicked = st.button("품질 분석", type="primary")

    if analyze_clicked:
        with st.status("설문 품질 분석 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()
            batch_done_count = [0]
            total_batches = [1]

            def _progress_callback(event: str, data: dict):
                if event == "batch_start":
                    total_batches[0] = data["total_batches"]
                    log_area.text(
                        f"배치 {data['batch_index'] + 1}/{data['total_batches']} 처리 중 "
                        f"({data['question_count']}개 문항)..."
                    )
                elif event == "batch_done":
                    batch_done_count[0] += 1
                    progress = batch_done_count[0] / total_batches[0]
                    progress_bar.progress(progress)
                    log_area.text(
                        f"배치 {data['batch_index'] + 1}/{data['total_batches']} 완료 "
                        f"({data['issues_found']}건 발견)"
                    )

            results = check_survey_quality(
                questions=questions,
                model=MODEL_QUALITY_CHECKER,
                language=language,
                progress_callback=_progress_callback,
            )
            st.session_state["quality_results"] = results
            st.session_state["quality_language"] = language

            total_issues = sum(len(r.issues) for r in results)
            status.update(
                label=f"분석 완료! {total_issues}건의 이슈를 발견했습니다.",
                state="complete",
            )

    # ── 결과 표시 ──
    if "quality_results" not in st.session_state:
        return

    results: List[QuestionQualityResult] = st.session_state["quality_results"]
    lang = st.session_state.get("quality_language", "ko")

    if not results:
        return

    st.divider()

    # ── 심각도 필터 ──
    severity_options = SEVERITIES.copy()
    severity_display = {s: SEVERITY_LABELS[lang][s] for s in severity_options}
    selected_severities = st.multiselect(
        "심각도 필터",
        options=severity_options,
        default=severity_options,
        format_func=lambda x: severity_display[x],
    )

    # 필터 적용된 결과
    filtered_results = _filter_results(results, selected_severities)

    _render_quality_dashboard(filtered_results, lang)
    st.divider()
    _render_issue_cards(filtered_results, lang)


def _filter_results(
    results: List[QuestionQualityResult],
    severities: List[str],
) -> List[QuestionQualityResult]:
    """심각도 필터를 적용하여 결과를 반환."""
    filtered = []
    for r in results:
        filtered_issues = [i for i in r.issues if i.severity in severities]
        filtered.append(QuestionQualityResult(
            question_number=r.question_number,
            question_text=r.question_text,
            issues=filtered_issues,
        ))
    return filtered


def _render_quality_dashboard(results: List[QuestionQualityResult], lang: str):
    """요약 대시보드 렌더링."""
    total_questions = len(results)
    all_issues = [iss for r in results for iss in r.issues]

    critical_count = sum(1 for i in all_issues if i.severity == "CRITICAL")
    warning_count = sum(1 for i in all_issues if i.severity == "WARNING")
    info_count = sum(1 for i in all_issues if i.severity == "INFO")
    questions_with_issues = sum(1 for r in results if r.issues)

    # 메트릭 카드
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 문항", total_questions)
    with col2:
        st.metric("심각", critical_count)
    with col3:
        st.metric("경고", warning_count)
    with col4:
        st.metric("정보", info_count)

    if not all_issues:
        st.success("품질 이슈가 감지되지 않았습니다!", icon="✅")
        return

    st.caption(
        f"전체 {total_questions}개 문항 중 {questions_with_issues}개에서 이슈 발견"
    )

    st.subheader("카테고리별 분포")
    cat_labels = CATEGORY_LABELS[lang]
    cat_counts = {cat: 0 for cat in CATEGORIES}
    for iss in all_issues:
        if iss.category in cat_counts:
            cat_counts[iss.category] += 1

    max_count = max(cat_counts.values()) if cat_counts else 1
    for cat in CATEGORIES:
        count = cat_counts[cat]
        if count == 0:
            continue
        label = cat_labels.get(cat, cat)
        col_label, col_bar, col_count = st.columns([2, 6, 1])
        with col_label:
            st.text(label)
        with col_bar:
            st.progress(count / max_count if max_count > 0 else 0)
        with col_count:
            st.text(str(count))


def _render_issue_cards(results: List[QuestionQualityResult], lang: str):
    """문항별 이슈 카드 렌더링."""
    st.subheader("문항별 상세")

    cat_labels = CATEGORY_LABELS[lang]
    sev_labels = SEVERITY_LABELS[lang]

    severity_badge = {
        "CRITICAL": "🔴",
        "WARNING": "⚠️",
        "INFO": "ℹ️",
    }

    for result in results:
        has_critical = any(i.severity == "CRITICAL" for i in result.issues)
        has_warning = any(i.severity == "WARNING" for i in result.issues)
        has_issues = len(result.issues) > 0

        if has_critical:
            icon = "🔴"
        elif has_warning:
            icon = "⚠️"
        elif has_issues:
            icon = "ℹ️"
        else:
            icon = "✅"

        q_text_preview = result.question_text[:80]
        if len(result.question_text) > 80:
            q_text_preview += "..."

        issue_count = f" ({len(result.issues)} issues)" if result.issues else ""
        label = f"{icon} {result.question_number}. {q_text_preview}{issue_count}"

        with st.expander(label, expanded=has_issues):
            if not result.issues:
                st.success("품질 이슈 없음", icon="✅")
            else:
                for issue in result.issues:
                    badge = severity_badge.get(issue.severity, "")
                    sev_text = sev_labels.get(issue.severity, issue.severity)
                    cat_text = cat_labels.get(issue.category, issue.category)

                    st.markdown(f"**{badge} {sev_text} — {cat_text}**")
                    st.markdown(f"> {issue.description}")
                    st.info(f"💡 {issue.suggestion}")


# ============================================================
# Grammar Correction 탭
# ============================================================

def _render_grammar_correction_tab():
    """Grammar Correction 탭 전체 렌더링."""
    # Guard: edited_df 필요
    if "edited_df" not in st.session_state or st.session_state["edited_df"] is None or st.session_state["edited_df"].empty:
        st.warning('먼저 Questionnaire Analyzer에서 문서를 처리해주세요.', icon="⚠️")
        return

    df = st.session_state["edited_df"]
    total_questions = df["QuestionNumber"].nunique()

    st.info(
        f"고유 문항 **{total_questions}**개를 발견했습니다. "
        "언어를 선택하고 **문법 검사** 버튼을 눌러주세요.",
        icon="ℹ️",
    )

    ctrl_col1, ctrl_col2 = st.columns([1, 3])
    with ctrl_col1:
        language = st.selectbox(
            "언어",
            options=["ko", "en"],
            format_func=lambda x: "한국어" if x == "ko" else "English",
            key="grammar_language_select",
        )
    with ctrl_col2:
        st.write("")
        st.write("")
        check_clicked = st.button("문법 검사", type="primary", key="grammar_check_btn")

    if check_clicked:
        with st.status("문법 검사 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()
            batch_done_count = [0]
            total_batches = [1]

            def _progress_callback(event: str, data: dict):
                if event == "batch_start":
                    total_batches[0] = data["total_batches"]
                    log_area.text(
                        f"배치 {data['batch_index'] + 1}/{data['total_batches']} 처리 중 "
                        f"({data['question_count']}개 문항)..."
                    )
                elif event == "batch_done":
                    batch_done_count[0] += 1
                    progress = batch_done_count[0] / total_batches[0]
                    progress_bar.progress(progress)
                    log_area.text(
                        f"배치 {data['batch_index'] + 1}/{data['total_batches']} 완료 "
                        f"({data['changed_count']}개 교정)"
                    )

            results = check_grammar(df, language, _progress_callback)
            st.session_state["grammar_results"] = results

            apply_grammar_results(results)

            changed_count = sum(1 for r in results if r["has_changes"])
            status.update(
                label=f"문법 검사 완료! {changed_count}/{len(results)}개 문항 교정됨.",
                state="complete",
            )

    # ── 결과 표시 ──
    if "grammar_results" not in st.session_state:
        # GrammarChecker 컬럼 초기화
        if "GrammarChecker" not in df.columns:
            df["GrammarChecker"] = ""
            st.session_state["edited_df"] = df
        _render_grammar_editable_table()
        render_download_buttons("Quality Checker", include_excel=True)
        return

    results = st.session_state["grammar_results"]
    if not results:
        return

    st.divider()

    # ── Dashboard ──
    _render_grammar_dashboard(results)

    # ── Filter ──
    filter_mode = st.radio(
        "필터",
        options=["All", "Changed Only", "Unchanged Only"],
        format_func=lambda x: {"All": "전체", "Changed Only": "교정된 항목만", "Unchanged Only": "변경 없음만"}[x],
        horizontal=True,
        key="grammar_filter_radio",
    )

    # ── Comparison View ──
    _render_grammar_comparison(results, filter_mode)

    st.divider()

    # ── Editable Table ──
    st.subheader("편집 테이블")
    _render_grammar_editable_table()

    # ── Download ──
    render_download_buttons("Quality Checker", include_excel=True)


def _render_grammar_dashboard(results: list):
    """메트릭 대시보드 4칸."""
    total = len(results)
    changed = sum(1 for r in results if r["has_changes"])
    unchanged = sum(1 for r in results if not r["has_changes"] and "Error" not in r.get("changes_summary", ""))
    errors = sum(1 for r in results if "Error" in r.get("changes_summary", ""))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 문항", total)
    with col2:
        st.metric("교정됨", changed)
    with col3:
        st.metric("변경 없음", unchanged)
    with col4:
        st.metric("오류", errors)


def _render_grammar_comparison(results: list, filter_mode: str):
    """원본↔교정 비교 뷰."""
    filtered = results
    if filter_mode == "Changed Only":
        filtered = [r for r in results if r["has_changes"]]
    elif filter_mode == "Unchanged Only":
        filtered = [r for r in results if not r["has_changes"]]

    if not filtered:
        st.info("선택한 필터에 해당하는 문항이 없습니다.")
        return

    for r in filtered:
        qn = r["question_number"]
        has_changes = r["has_changes"]
        summary = r.get("changes_summary", "")

        if "Error" in summary:
            icon = "🔴"
            label = f"{icon} {qn}: {summary}"
        elif has_changes:
            icon = "✏️"
            label = f'{icon} {qn}: "{summary}"' if summary else f"{icon} {qn}: Changed"
        else:
            icon = "✅"
            label = f"{icon} {qn}: No changes"

        with st.expander(label, expanded=has_changes):
            if has_changes:
                col_orig, col_corr = st.columns(2)
                with col_orig:
                    st.markdown("**원본**")
                    st.text(r["original_text"])
                with col_corr:
                    st.markdown("**교정**")
                    st.text(r["corrected_text"])

                # 보기 비교 (변경된 경우)
                if r["corrected_options"]:
                    st.markdown("---")
                    col_o2, col_c2 = st.columns(2)
                    with col_o2:
                        st.markdown("**원본 보기**")
                        st.text(r["original_options"])
                    with col_c2:
                        st.markdown("**교정된 보기**")
                        for opt in r["corrected_options"]:
                            st.text(f"{opt['code']}. {opt['label']}")

                if summary:
                    st.caption(f"Changes: {summary}")
            else:
                st.success("문법 이슈 없음", icon="✅")


def _render_grammar_editable_table():
    """편집 가능 테이블 + Apply Edits 버튼."""
    if "edited_df" not in st.session_state:
        return

    df = st.session_state["edited_df"]

    display_cols = ["QuestionNumber", "TableNumber", "QuestionText", "GrammarChecker"]
    if "AnswerOptions" in df.columns:
        display_cols.append("AnswerOptions")
    display_cols.extend(["QuestionType", "SummaryType"])

    # 존재하는 컬럼만 필터
    display_cols = [c for c in display_cols if c in df.columns]

    edited = st.data_editor(
        df[display_cols],
        height=600,
        hide_index=True,
        num_rows="dynamic",
        key="grammar_editor",
        use_container_width=True,
    )

    if st.button("수정사항 적용", type="primary", key="apply_grammar_edits"):
        for col in display_cols:
            st.session_state["edited_df"][col] = edited[col]

        # survey_document에도 GrammarChecker 반영
        if "survey_document" in st.session_state and st.session_state["survey_document"]:
            qn_to_gc = dict(zip(edited["QuestionNumber"], edited["GrammarChecker"]))
            for q in st.session_state["survey_document"].questions:
                if q.question_number in qn_to_gc:
                    q.grammar_checked = str(qn_to_gc[q.question_number])

        st.success("수정사항이 적용되었습니다!", icon="✅")
        st.rerun()
