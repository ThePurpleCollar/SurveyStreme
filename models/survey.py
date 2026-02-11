from dataclasses import dataclass, field
from typing import List, Optional
import json
import pandas as pd


@dataclass
class AnswerOption:
    """설문 문항의 개별 응답 보기"""
    code: str        # "1", "2", "a"
    label: str       # "매우 그렇다", "브랜드A"

    def to_display(self) -> str:
        return f"{self.code}. {self.label}"


@dataclass
class SkipLogic:
    """설문 문항의 스킵/분기 로직"""
    condition: str   # "Q1=1 또는 2 응답자"
    target: str      # "Q5로 이동"

    def to_display(self) -> str:
        return f"{self.condition} -> {self.target}"


@dataclass
class BannerPoint:
    """배너 내 개별 포인트 (교차분석 컬럼)"""
    point_id: str              # "BP_1"
    label: str                 # "Male" (배너값 라벨)
    source_question: str       # "S1" or "A1&A2" (복합 조건 시)
    condition: str = ""        # "SQ1=1" or "A1=2&A2=5" (배너값 조건)
    codes: List[str] = field(default_factory=list)       # ["1", "2"]
    code_labels: List[str] = field(default_factory=list) # ["Male", "Female"]
    is_net: bool = False
    net_definition: str = ""

    def to_json_dict(self) -> dict:
        return {
            "point_id": self.point_id,
            "label": self.label,
            "source_question": self.source_question,
            "condition": self.condition,
            "codes": self.codes,
            "code_labels": self.code_labels,
            "is_net": self.is_net,
            "net_definition": self.net_definition,
        }

    @classmethod
    def from_json_dict(cls, d: dict) -> 'BannerPoint':
        return cls(
            point_id=d.get("point_id", ""),
            label=d.get("label", ""),
            source_question=d.get("source_question", ""),
            condition=d.get("condition", ""),
            codes=d.get("codes", []),
            code_labels=d.get("code_labels", []),
            is_net=d.get("is_net", False),
            net_definition=d.get("net_definition", ""),
        )


@dataclass
class Banner:
    """교차분석 배너 (복수 BannerPoint 포함)"""
    banner_id: str             # "A", "B"
    name: str                  # "Demographics"
    points: List[BannerPoint] = field(default_factory=list)
    rationale: str = ""        # 이 배너를 생성한 이유
    banner_type: str = "simple"  # "simple" | "composite"
    category: str = ""         # "Demographics", "Brand Relationship", etc.

    def to_json_dict(self) -> dict:
        return {
            "banner_id": self.banner_id,
            "name": self.name,
            "rationale": self.rationale,
            "banner_type": self.banner_type,
            "category": self.category,
            "points": [p.to_json_dict() for p in self.points],
        }

    @classmethod
    def from_json_dict(cls, d: dict) -> 'Banner':
        return cls(
            banner_id=d.get("banner_id", ""),
            name=d.get("name", ""),
            rationale=d.get("rationale", ""),
            banner_type=d.get("banner_type", "simple"),
            category=d.get("category", ""),
            points=[
                BannerPoint.from_json_dict(p) for p in d.get("points", [])
            ],
        )


@dataclass
class TableGuideDocument:
    """최종 Table Guide 문서 조립용"""
    project_name: str = ""
    filename: str = ""
    generated_at: str = ""     # ISO timestamp
    banners: List[Banner] = field(default_factory=list)
    rows: List[dict] = field(default_factory=list)
    language: str = "ko"


@dataclass
class SurveyQuestion:
    """설문 문항 전체 정보"""
    question_number: str
    question_text: str
    question_type: Optional[str] = None
    answer_options: List[AnswerOption] = field(default_factory=list)
    skip_logic: List[SkipLogic] = field(default_factory=list)
    filter_condition: Optional[str] = None     # "Q2=3,4 응답자만"
    instructions: Optional[str] = None         # "SHOW CARD", "보기 로테이션"
    # 기존 호환 필드
    summary_type: str = ""
    table_number: str = ""
    table_title: str = ""
    grammar_checked: str = ""
    # Phase 2: Base & Net/Recode
    base: str = ""
    net_recode: str = ""
    # Phase 3: Sort & SubBanner & Banner
    sort_order: str = ""
    sub_banner: str = ""
    banner_ids: str = ""
    # Phase 4: Special Instructions
    special_instructions: str = ""
    # Phase 5: Semantic metadata (Enrichment)
    role: str = ""              # "screening" | "demographics" | "awareness" |
                                # "usage_experience" | "evaluation" | "intent_loyalty" | "other"
    variable_type: str = ""     # "demographic" | "behavioral" | "attitudinal" | "brand" | ""
    analytical_value: str = ""  # "high" | "medium" | "low" | ""
    section: str = ""           # 조사 흐름상 섹션명

    def answer_options_display(self) -> str:
        """응답 보기를 여러 줄 문자열로 반환 (Excel용)"""
        if not self.answer_options:
            return ""
        return "\n".join(opt.to_display() for opt in self.answer_options)

    def answer_options_compact(self) -> str:
        """응답 보기를 한 줄 문자열로 반환 (CSV/스프레드시트용)"""
        if not self.answer_options:
            return ""
        return " | ".join(opt.to_display() for opt in self.answer_options)

    def skip_logic_display(self) -> str:
        """스킵 로직을 문자열로 반환"""
        if not self.skip_logic:
            return ""
        return " | ".join(sl.to_display() for sl in self.skip_logic)

    def to_dict(self) -> dict:
        """DataFrame 변환용 딕셔너리"""
        return {
            "QuestionNumber": self.question_number,
            "TableNumber": self.table_number,
            "QuestionText": self.question_text,
            "QuestionType": self.question_type or "",
            "AnswerOptions": self.answer_options_compact(),
            "SkipLogic": self.skip_logic_display(),
            "Filter": self.filter_condition or "",
            "Instructions": self.instructions or "",
            "SummaryType": self.summary_type,
            "TableTitle": self.table_title,
            "GrammarChecker": self.grammar_checked,
            "Base": self.base,
            "NetRecode": self.net_recode,
            "Sort": self.sort_order,
            "SubBanner": self.sub_banner,
            "BannerIDs": self.banner_ids,
            "SpecialInstructions": self.special_instructions,
            "Role": self.role,
            "VariableType": self.variable_type,
        }

    def to_json_dict(self) -> dict:
        """세션 저장용 JSON 딕셔너리 (모든 필드 포함, 무손실)"""
        return {
            "question_number": self.question_number,
            "question_text": self.question_text,
            "question_type": self.question_type,
            "answer_options": [
                {"code": o.code, "label": o.label} for o in self.answer_options
            ],
            "skip_logic": [
                {"condition": s.condition, "target": s.target} for s in self.skip_logic
            ],
            "filter_condition": self.filter_condition,
            "instructions": self.instructions,
            "summary_type": self.summary_type,
            "table_number": self.table_number,
            "table_title": self.table_title,
            "grammar_checked": self.grammar_checked,
            "base": self.base,
            "net_recode": self.net_recode,
            "sort_order": self.sort_order,
            "sub_banner": self.sub_banner,
            "banner_ids": self.banner_ids,
            "special_instructions": self.special_instructions,
            "role": self.role,
            "variable_type": self.variable_type,
            "analytical_value": self.analytical_value,
            "section": self.section,
        }

    @classmethod
    def from_json_dict(cls, d: dict) -> 'SurveyQuestion':
        """세션 JSON에서 SurveyQuestion 복원 (후처리 필드 포함)"""
        return cls(
            question_number=d.get("question_number", ""),
            question_text=d.get("question_text", ""),
            question_type=d.get("question_type"),
            answer_options=[
                AnswerOption(code=str(o.get("code", "")), label=str(o.get("label", "")))
                for o in d.get("answer_options", [])
                if isinstance(o, dict) and "label" in o
            ],
            skip_logic=[
                SkipLogic(condition=str(s.get("condition", "")), target=str(s.get("target", "")))
                for s in d.get("skip_logic", [])
                if isinstance(s, dict) and "condition" in s
            ],
            filter_condition=d.get("filter_condition"),
            instructions=d.get("instructions"),
            summary_type=d.get("summary_type", ""),
            table_number=d.get("table_number", ""),
            table_title=d.get("table_title", ""),
            grammar_checked=d.get("grammar_checked", ""),
            base=d.get("base", ""),
            net_recode=d.get("net_recode", ""),
            sort_order=d.get("sort_order", ""),
            sub_banner=d.get("sub_banner", ""),
            banner_ids=d.get("banner_ids", ""),
            special_instructions=d.get("special_instructions", ""),
            role=d.get("role", ""),
            variable_type=d.get("variable_type", ""),
            analytical_value=d.get("analytical_value", ""),
            section=d.get("section", ""),
        )

    @classmethod
    def from_llm_dict(cls, d: dict) -> 'SurveyQuestion':
        """LLM 추출 JSON에서 SurveyQuestion 생성"""
        return cls(
            question_number=d.get("question_number", ""),
            question_text=d.get("question_text", ""),
            question_type=d.get("question_type"),
            answer_options=[
                AnswerOption(code=str(o.get("code", "")), label=str(o.get("label", "")))
                for o in d.get("answer_options", [])
                if isinstance(o, dict) and "label" in o
            ],
            skip_logic=[
                SkipLogic(condition=str(s.get("condition", "")), target=str(s.get("target", "")))
                for s in d.get("skip_logic", [])
                if isinstance(s, dict) and "condition" in s
            ],
            filter_condition=d.get("filter"),
            instructions=d.get("instructions"),
        )


@dataclass
class SurveyDocument:
    """파싱된 설문 문서 전체"""
    filename: str
    questions: List[SurveyQuestion] = field(default_factory=list)
    raw_summary: str = ""
    banners: List[Banner] = field(default_factory=list)
    # Study-level metadata (Enrichment)
    client_brand: str = ""
    study_type: str = ""                   # "Brand Tracking", "U&A", etc.
    study_objective: str = ""
    research_objectives: List[str] = field(default_factory=list)
    survey_intelligence: dict = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        """기존 edited_df와 호환되는 DataFrame 생성"""
        if not self.questions:
            return pd.DataFrame(columns=[
                "QuestionNumber", "TableNumber", "QuestionText", "QuestionType",
                "AnswerOptions", "SkipLogic", "Filter",
                "Instructions", "SummaryType", "TableTitle", "GrammarChecker",
                "Base", "NetRecode", "Sort", "SubBanner", "BannerIDs",
                "SpecialInstructions", "Role", "VariableType",
            ])
        return pd.DataFrame([q.to_dict() for q in self.questions])

    def to_json_dict(self) -> dict:
        """세션 저장용 JSON 딕셔너리"""
        return {
            "version": 5,
            "filename": self.filename,
            "raw_summary": self.raw_summary,
            "questions": [q.to_json_dict() for q in self.questions],
            "banners": [b.to_json_dict() for b in self.banners],
            "client_brand": self.client_brand,
            "study_type": self.study_type,
            "study_objective": self.study_objective,
            "research_objectives": self.research_objectives,
            "survey_intelligence": self.survey_intelligence,
        }

    def to_json_bytes(self) -> bytes:
        """세션 저장용 JSON 바이트"""
        return json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2).encode("utf-8")

    @classmethod
    def from_json_dict(cls, d: dict) -> 'SurveyDocument':
        """세션 JSON에서 SurveyDocument 복원 (v4/v5 호환)"""
        return cls(
            filename=d.get("filename", ""),
            raw_summary=d.get("raw_summary", ""),
            questions=[
                SurveyQuestion.from_json_dict(q) for q in d.get("questions", [])
            ],
            banners=[
                Banner.from_json_dict(b) for b in d.get("banners", [])
            ],
            client_brand=d.get("client_brand", ""),
            study_type=d.get("study_type", ""),
            study_objective=d.get("study_objective", ""),
            research_objectives=d.get("research_objectives", []),
            survey_intelligence=d.get("survey_intelligence", {}),
        )
