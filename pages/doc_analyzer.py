import os
import time
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

import streamlit as st
from services.llm_client import MODEL_DOC_ANALYZER
from services.postprocessor import apply_postprocessing
from services.docx_parser import parse_docx
from services.docx_renderer import render_sections_to_annotated_text
from services.chunker import chunk_sections
from services.docx_preflight import check_docx_preflight
from services.llm_extractor import LLMExtractionError, extract_survey_questions
from services.coverage_checker import check_extraction_coverage
from services.coverage_user_summary import summarize_coverage_for_user
from models.survey import SurveyDocument, SurveyQuestion
from services.table_guide_service import analyze_survey_intelligence
from services.survey_context import enrich_document
from ui.tree_view import render_tree_view
from ui.spreadsheet import apply_spreadsheet_edits_to_document, render_spreadsheet_view


DOCX_STRUCTURE_CACHE_VERSION = "docx-structure-v2"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@st.cache_data(show_spinner=False)
def _parse_and_chunk_docx_cached(
    file_bytes: bytes,
    filename: str,
    cache_version: str,
):
    """Parse and chunk a DOCX once per file content and parser version."""
    sections = parse_docx(io.BytesIO(file_bytes))
    chunks = chunk_sections(sections)
    return sections, chunks


def page_document_processing(uploaded_file, client=None):
    st.title('Questionnaire Analyzer')

    # 세션 로드 결과가 있으면 파일 업로드 없이도 즉시 표시
    if uploaded_file is None and 'survey_document' in st.session_state:
        doc = st.session_state['survey_document']
        st.success(f"세션 복원 완료: **{doc.filename}** — {len(doc.questions)}개 문항", icon="✅")
        st.caption("💡 저장된 세션 파일에서 불러왔습니다. 다른 도구로 바로 진행할 수 있습니다.")
        _render_intelligence_summary(doc)
        _display_docx_results(doc)
        return

    if uploaded_file is not None:
        st.success("업로드된 파일에서 문항 번호, 문항 텍스트, 문항 유형을 추출합니다.", icon="✅")
    else:
        st.info('사이드바에서 설문지 파일을 업로드해주세요.', icon="ℹ️")
        return

    if uploaded_file is not None:
        if uploaded_file.name.endswith('.docx'):
            _process_docx(uploaded_file, client)
        else:
            st.error("지원하지 않는 파일 형식입니다. .docx 파일을 업로드해주세요.")


def _process_docx(uploaded_file, client):
    """DOCX AI 추출 파이프라인"""

    # ── Study Brief (optional) ──
    with st.expander("Study Brief (선택사항 — 분석 품질 향상에 도움)", expanded=False):
        brief_col1, brief_col2 = st.columns(2)
        with brief_col1:
            client_brand = st.text_input(
                "Client Brand",
                value=st.session_state.get("study_client_brand", ""),
                placeholder="e.g. Hyundai, Samsung, LG",
                help="The brand commissioning the study.",
                key="study_client_brand_input",
            )
            st.session_state["study_client_brand"] = client_brand
        with brief_col2:
            study_objective = st.text_input(
                "Study Objective",
                value=st.session_state.get("study_objective", ""),
                placeholder="e.g. Brand health tracking, Customer satisfaction",
                help="Research purpose.",
                key="study_objective_input",
            )
            st.session_state["study_objective"] = study_objective

    # 추출 버튼
    extract_button = st.button('AI로 문항 추출 시작', key='extract_docx_button', use_container_width=True)

    # 이전 결과가 있으면 표시
    if 'survey_document' in st.session_state and not extract_button:
        _display_docx_results(st.session_state['survey_document'])
        return

    if not extract_button:
        st.info("'AI로 문항 추출 시작' 버튼을 눌러 설문지 분석을 시작하세요.", icon="🤖")
        return

    # ── 추출 파이프라인 시작 ──
    model = MODEL_DOC_ANALYZER
    file_bytes = uploaded_file.getvalue()
    file_digest = _hash_bytes(file_bytes)

    with st.status("1/5단계: DOCX 구조 파싱 중...", expanded=True) as status:
        phase_line = status.empty()
        detail_line = status.empty()
        # Phase 1: DOCX 파싱
        phase_line.write("DOCX 구조를 분석하고 있습니다 (스타일, 목록, 표)...")
        try:
            sections, chunks = _parse_and_chunk_docx_cached(
                file_bytes,
                uploaded_file.name,
                DOCX_STRUCTURE_CACHE_VERSION,
            )
        except Exception as e:
            status.update(label="DOCX 파싱 실패", state="error")
            st.error(f"DOCX 파싱 오류: {e}")
            return

        if not sections:
            status.update(label="DOCX에서 내용을 찾을 수 없습니다.", state="error")
            st.warning("DOCX 파일에서 내용을 추출할 수 없습니다.")
            return

        total_paragraphs = sum(len(s.paragraphs) for s in sections)
        total_tables = sum(len(s.tables) for s in sections)
        preflight = check_docx_preflight(sections)
        phase_line.write(f"✅ 파싱 완료: {len(sections)}개 섹션, "
                         f"{total_paragraphs}개 단락, {total_tables}개 표")

        # Phase 1 cont: 어노테이션 텍스트 + 청킹
        detail_line.write(
            f"AI 처리를 위해 {len(chunks)}개 청크로 분할 | "
            f"Parse cache key: {file_digest[:12]}"
        )
        _render_preflight_report(preflight)

        # Phase 3 준비: LLM 추출 (적응형 재청킹 포함)
        # 동적 업데이트용 컨테이너
        progress_bar = status.progress(0.0)
        stats_line = status.empty()

        start_time = time.time()
        chunks_done = [0]  # mutable for closure
        total_questions_found = [0]  # 누적 문항 수

        def on_progress(event, data):
            elapsed = time.time() - start_time

            if event == "regex_done":
                status.update(label="2/5단계: 문항 패턴 스캔 중...")
                phase_line.write(f"✅ 빠른 스캔으로 ~{data['total_hints']}개 문항 후보 발견")
                detail_line.write("AI 추출을 준비하고 있습니다...")

            elif event == "rechunk":
                detail_line.write(
                    f"ℹ️ 적응형 재분할: {data['original_chunks']} → "
                    f"{data['new_chunks']}개 청크 ({data['reason']})"
                )

            elif event == "chunk_start":
                total = data['total_chunks']
                status.update(
                    label=f"3/5단계: AI로 문항 추출 중... "
                          f"(청크 {chunks_done[0]}/{total} 완료)"
                )
                frac = max(chunks_done[0] / total, 0.0)
                progress_bar.progress(frac)
                detail_line.write(
                    f"청크 {data['chunk_index'] + 1}/{total} 처리 중 | "
                    f"후보 {data.get('regex_hints', 0)}개"
                )

            elif event == "chunk_done":
                chunks_done[0] += 1
                extracted = data['questions_extracted']
                total_questions_found[0] += extracted
                done = chunks_done[0]
                total = data['total_chunks']
                progress_bar.progress(done / total)

                # 청크별 완료 로그
                e_m, e_s = divmod(int(elapsed), 60)
                phase_line.write(
                    f"✅ 청크 {done}/{total} 완료 | 이번 청크 {extracted}개 | "
                    f"누적 {total_questions_found[0]}개"
                )

                status.update(
                    label=f"3/5단계: AI로 문항 추출 중... "
                          f"(청크 {done}/{total} 완료)"
                )

                remaining = (elapsed / done * (total - done)) if done > 0 else 0
                remain_m, remain_s = divmod(int(remaining), 60)
                stats_line.write(
                    f"경과 {e_m}:{e_s:02d} | 남은 시간 ~{remain_m}:{remain_s:02d}"
                )

            elif event == "chunk_error":
                phase_line.write(f"⚠️ 청크 {data['chunk_index'] + 1} 실패")
                detail_line.write(str(data["error"]))

            elif event == "missed_questions":
                detail_line.write(
                    f"⚠️ 패턴 스캔에서 감지되었으나 AI가 놓친 문항 {data['count']}건: "
                    f"{', '.join(data['question_numbers'][:10])}"
                    f"{'...' if data['count'] > 10 else ''}"
                )

            elif event == "merge_done":
                progress_bar.progress(1.0)
                missed = data.get('missed_count', 0)
                missed_note = f" (⚠️ {missed}건 누락 가능)" if missed else ""
                phase_line.write(
                    f"📊 총 **{data['total_questions']}**개 문항 추출 완료{missed_note}"
                )
                stats_line.write("AI 추출 단계가 완료되었습니다.")

        event_queue = Queue()

        def queued_progress(event, data):
            event_queue.put((event, data))

        def drain_progress_events():
            drained = False
            while True:
                try:
                    event, data = event_queue.get_nowait()
                except Empty:
                    return drained
                on_progress(event, data)
                drained = True

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    extract_survey_questions,
                    client=client,
                    chunks=chunks,
                    model=model,
                    progress_callback=queued_progress,
                )
                heartbeat = 0
                while not future.done():
                    got_event = drain_progress_events()
                    elapsed = time.time() - start_time
                    e_m, e_s = divmod(int(elapsed), 60)
                    if not got_event:
                        dots = "." * ((heartbeat % 3) + 1)
                        phase_line.write(
                            f"AI 응답을 기다리는 중{dots} "
                            f"누적 {total_questions_found[0]}개 문항"
                        )
                        stats_line.write(f"경과 {e_m}:{e_s:02d} | 화면은 계속 갱신 중")
                        heartbeat += 1
                    time.sleep(1)
                drain_progress_events()
                questions = future.result()
        except LLMExtractionError as e:
            status.update(label="AI extraction failed", state="error")
            st.error(
                "AI extraction could not run. The document was parsed, but the "
                f"LLM request failed before extraction completed.\n\n{e}"
            )
            return

        elapsed_total = time.time() - start_time
        em, es = divmod(int(elapsed_total), 60)
        status.update(
            label=f"4/5단계: 마무리 중 — {len(questions)}개 문항, {em}:{es:02d} 소요",
            state="running", expanded=True,
        )

    if not questions:
        st.warning("문항을 추출할 수 없습니다. 문서에 설문 문항이 포함되어 있는지 확인해주세요.")
        return

    # SurveyDocument 생성
    client_brand = st.session_state.get("study_client_brand", "")
    study_objective = st.session_state.get("study_objective", "")
    survey_doc = SurveyDocument(
        filename=uploaded_file.name,
        questions=questions,
        client_brand=client_brand,
        study_objective=study_objective,
    )

    # 후처리: SummaryType, TableNumber 계산
    apply_postprocessing(survey_doc)

    # ── Phase 5: Survey Enrichment ──
    with st.status("5/5단계: 설문 인텔리전스 분석 중...", expanded=True) as enrich_status:
        try:
            intelligence = analyze_survey_intelligence(
                questions, language="en",
                client_brand=client_brand,
                study_objective=study_objective,
            )
            enrich_document(survey_doc, intelligence)
            obj_count = len(intelligence.get("research_objectives", []))
            seg_count = len(intelligence.get("key_segments", []))
            enrich_status.write(
                f"Study: {intelligence.get('study_type', '')} | "
                f"{obj_count} objectives | {seg_count} key segments"
            )
            enrich_status.update(label="5/5단계: 인텔리전스 분석 완료!", state="complete")
        except Exception as e:
            enrich_status.update(label=f"5/5단계: 인텔리전스 분석 건너뜀 ({e})", state="error")

    # 세션 상태 저장
    st.session_state['survey_document'] = survey_doc
    st.session_state['edited_df'] = survey_doc.to_dataframe()

    st.success(f"**{len(questions)}**개 문항을 추출했습니다.", icon="✅")

    # Coverage Report — 원본과 추출 결과 비교
    coverage = check_extraction_coverage(sections, questions)
    _render_coverage_report(coverage)

    # Intelligence 요약 카드
    _render_intelligence_summary(survey_doc)

    # 세션 저장 유도 배너
    with st.container(border=True):
        save_col1, save_col2 = st.columns([3, 1])
        with save_col1:
            st.markdown(
                "💾 **세션을 저장**하면 다음에 이 단계를 건너뛸 수 있습니다.  \n"
                "저장된 `.json` 파일을 업로드하면 모든 결과를 즉시 복원합니다."
            )
        with save_col2:
            st.download_button(
                label="💾 세션 저장",
                data=survey_doc.to_json_bytes(),
                file_name=f"{os.path.splitext(uploaded_file.name)[0]}_session.json",
                mime='application/json',
                use_container_width=True,
                type="primary",
            )

    st.toast("추출이 완료되었습니다! 세션을 저장해두세요.", icon="💾")

    # 결과 표시
    _display_docx_results(survey_doc)


def _render_coverage_report(report):
    """Render extraction diagnostics as user-facing review guidance."""
    summary = summarize_coverage_for_user(report)

    with st.container(border=True):
        st.markdown("### 추출 결과 점검")
        body = (
            f"**상태: {summary.status_label}**\n\n"
            f"{summary.headline}\n\n"
            f"{summary.guidance}"
        )
        if summary.tone == "warning":
            st.warning(body, icon="⚠️")
        elif summary.tone == "info":
            st.info(body, icon="ℹ️")
        else:
            st.success(body, icon="✅")

        st.markdown("**점검 요약**")
        for start in range(0, len(summary.metrics), 2):
            metric_cols = st.columns(2)
            for col, metric in zip(metric_cols, summary.metrics[start:start + 2]):
                with col:
                    with st.container(border=True):
                        status_icon = {
                            "ok": "✅",
                            "info": "ℹ️",
                            "warning": "⚠️",
                        }.get(metric.tone, "ℹ️")
                        st.markdown(f"{status_icon} **{metric.label}**")
                        st.markdown(f"{metric.value} · **{metric.status}**")
                        if metric.detail:
                            st.caption(metric.detail)

        if summary.key_items:
            st.markdown("**먼저 확인할 항목**")
            st.caption(
                "아래 항목은 결과 품질에 영향을 줄 수 있습니다. "
                "결과 테이블에서 정상 반영 여부를 먼저 확인해주세요."
            )
            _render_user_coverage_items(summary.key_items[:8])
            if len(summary.key_items) > 8:
                with st.expander(f"나머지 중요 확인 항목 {len(summary.key_items) - 8}개", expanded=False):
                    _render_user_coverage_items(summary.key_items[8:])

        if summary.reference_items:
            with st.expander(
                f"참고 항목 {len(summary.reference_items)}개 "
                "(보기 코드나 안내 표일 가능성이 높은 항목)",
                expanded=False,
            ):
                st.caption(
                    "아래 항목은 자동 점검에서 문항 후보로 감지되었지만, "
                    "실제로는 보기 코드, 나이, TV 사이즈, 가격값 또는 안내 표일 가능성이 높습니다. "
                    "결과에 이상이 없어 보이면 별도로 수정하지 않아도 됩니다."
                )
                _render_user_coverage_items(summary.reference_items[:30])
                if len(summary.reference_items) > 30:
                    st.caption(f"그 외 참고 항목 {len(summary.reference_items) - 30}개는 생략했습니다.")


def _render_user_coverage_items(items):
    """Render compact action items for extraction review."""
    for idx, item in enumerate(items, start=1):
        st.markdown(f"{idx}. **{item.title}** — {item.message}")
        if item.evidence:
            st.caption(f"근거: {item.evidence}")


def _render_preflight_report(report):
    """Render DOCX format readiness before the costly LLM extraction."""
    label = report.readiness_label
    if report.score >= 85:
        icon = "✅"
    elif report.score >= 70:
        icon = "ℹ️"
    else:
        icon = "⚠️"

    with st.expander(
        f"{icon} DOCX Preflight — {report.score}/100 ({label})",
        expanded=report.score < 85,
    ):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Question candidates", report.question_candidates)
        c2.metric("Typed", f"{report.typed_question_candidates}/{report.question_candidates}")
        c3.metric("Option tables", report.option_tables)
        c4.metric("Generic/Unknown", f"{report.generic_tables}/{report.unknown_tables}")

        st.caption(
            f"Sections {report.sections} · Paragraphs {report.paragraphs} · "
            f"Tables {report.tables} · Grid/Matrix {report.grid_tables} · "
            f"Merged tables {report.merged_tables} · Textboxes {report.textbox_paragraphs}"
        )

        if report.issues:
            st.markdown("**수정/검수 권장 항목**")
            for issue in report.issues:
                mark = "⚠️" if issue.severity in ("high", "medium") else "ℹ️"
                st.markdown(f"- {mark} {issue.message}")
                if issue.evidence:
                    st.caption(issue.evidence)
        else:
            st.markdown("서식상 큰 리스크가 감지되지 않았습니다.")


def _render_intelligence_summary(doc: SurveyDocument):
    """Intelligence 결과 요약 카드 + Re-analyze 버튼."""
    intel = doc.survey_intelligence
    if not intel or not intel.get("study_type"):
        return

    client = intel.get("client_name", "") or doc.client_brand
    study = intel.get("study_type", "")
    header = f"{client} — {study}" if client else study
    objectives = intel.get("research_objectives", [])
    obj_str = " | ".join(objectives[:4]) if objectives else ""
    segments = intel.get("key_segments", [])
    seg_str = " · ".join(
        f"{s.get('name', '')}({s.get('type', '')})" for s in segments
    ) if segments else ""

    intel_lines = [f"**{header}**"]
    if obj_str:
        intel_lines.append(f"Objectives: {obj_str}")
    if seg_str:
        intel_lines.append(f"Key Segments: {seg_str}")
    st.info("\n\n".join(intel_lines), icon="\U0001f4cb")

    # Re-analyze 버튼
    if st.button("Re-analyze Intelligence", key="re_analyze_intel_btn"):
        client_brand = st.session_state.get("study_client_brand", doc.client_brand)
        study_objective = st.session_state.get("study_objective", doc.study_objective)
        doc.client_brand = client_brand
        doc.study_objective = study_objective
        with st.spinner("Re-analyzing survey intelligence..."):
            try:
                intelligence = analyze_survey_intelligence(
                    doc.questions, language="en",
                    client_brand=client_brand,
                    study_objective=study_objective,
                )
                enrich_document(doc, intelligence)
                st.session_state['survey_document'] = doc
                st.session_state['edited_df'] = doc.to_dataframe()
                st.success("Intelligence re-analyzed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Re-analysis failed: {e}")


def _display_docx_results(survey_doc: SurveyDocument):
    """추출 결과를 스프레드시트(기본) + 트리뷰(접힘)로 표시"""
    edited_df = render_spreadsheet_view(survey_doc)
    survey_doc = apply_spreadsheet_edits_to_document(survey_doc, edited_df)
    st.session_state['survey_document'] = survey_doc
    st.session_state['edited_df'] = edited_df

    if st.checkbox("Show Tree View (detailed question cards)", value=False,
                    key="show_tree_view"):
        render_tree_view(survey_doc)
