from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path


SEMANTIC_EXTRACTOR_VERSION = 1

BUSINESS_DOMAINS = (
    "课程产品与基本参数",
    "班型定位与适合学员",
    "学科、年级与课程内容",
    "教材版本与配套练习",
    "课程衔接与学习规划",
    "师资、教学过程与学习服务",
    "报名、缴费、续报、转班退费规则",
    "活动营销、优惠与赠品",
)

RELATION_TYPES = frozenset(
    {
        "suitable_for",
        "prerequisite_of",
        "continues_to",
        "overlaps_with",
        "alternative_to",
        "uses_textbook",
        "taught_by",
        "includes_service",
        "applies_campaign",
    }
)

SEMANTIC_DECISIONS = frozenset(
    {"pending", "approved", "blocked", "discarded", "deferred"}
)
SCOPE_STATUSES = frozenset(
    {"tianjin", "tianjin_compatible", "pending", "out_of_scope"}
)

_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_IDENTIFIER_PATTERN = re.compile(
    r"(?:学员号|订单号|员工编号|手机号|联系电话)\s*[:：]?\s*[A-Za-z0-9_-]{5,}"
)
_DATE_PATTERN = re.compile(
    r"(?<!\d)(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?"
)
_LESSON_PATTERN = re.compile(r"(?:共|合计)?\s*(\d{1,3})\s*讲")
_FEE_PATTERN = re.compile(r"(?<!\d)(\d{2,6}(?:\.\d{1,2})?)\s*元")
_GRADE_PATTERN = re.compile(
    r"(?:新)?[一二三四五六七八九]年级|小升初|大升一|中升大|幼升小"
)
_CLASS_PATTERN = re.compile(
    r"(?:A\+|A\+\+|AA\+|S|S\+|A|B)\s*班|全国班|零基础|预备级",
    re.IGNORECASE,
)
_TEXTBOOK_PATTERN = re.compile(
    r"(?:人教|北师大|冀教|苏教|沪教|外研|剑桥|教科|鲁教|部编)版?"
)

_DOMAIN_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (BUSINESS_DOMAINS[7], ("活动", "优惠", "赠品", "老带新", "金币", "奖学金")),
    (BUSINESS_DOMAINS[6], ("报名", "缴费", "续报", "转班", "退费", "补缴")),
    (BUSINESS_DOMAINS[5], ("师资", "老师", "授课", "教学", "回放", "设备", "答疑", "服务")),
    (BUSINESS_DOMAINS[4], ("衔接", "规划", "重复", "后续", "先修", "续学")),
    (BUSINESS_DOMAINS[3], ("教材", "练习", "学生用书", "成长手册", "讲义")),
    (BUSINESS_DOMAINS[1], ("班型", "适合", "A+", "S班", "分层", "零基础", "预备级")),
    (BUSINESS_DOMAINS[2], ("大纲", "知识点", "课程内容", "年级", "数学", "语文", "英语", "物理", "化学", "文综")),
    (BUSINESS_DOMAINS[0], ("课程参数", "讲次", "课时", "时长", "价格", "费用", "校历")),
)

_INTERNAL_TERMS = (
    "内部目标",
    "销售目标",
    "业绩目标",
    "续报率",
    "转化率",
    "负责人",
    "员工编号",
    "项目进度",
    "排期",
    "权限路径",
    "系统操作",
    "制作进度",
    "会议纪要",
    "开课人次",
)
_MARKETING_RISK_TERMS = (
    "包过",
    "保过",
    "保证提分",
    "必然提分",
    "名校效果",
    "效果显著",
    "智力提升",
    "一定有效",
)
_CAMPAIGN_TERMS = ("活动", "优惠", "赠品", "老带新", "金币", "奖学金")

_RELATION_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("suitable_for", ("适合", "适用学员")),
    ("prerequisite_of", ("前置", "先学", "先修")),
    ("continues_to", ("衔接", "后续", "续学", "续报")),
    ("overlaps_with", ("重复", "重叠")),
    ("alternative_to", ("替代", "二选一")),
    ("uses_textbook", ("教材", "用书")),
    ("taught_by", ("师资", "老师", "授课教师")),
    ("includes_service", ("回放", "答疑", "学习服务", "设备")),
    ("applies_campaign", _CAMPAIGN_TERMS),
)


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    candidate_key: str
    revision_id: int
    block_id: int
    block_key: str
    record_kind: str
    business_domain: str
    stage: str
    grade: str
    subject: str
    course_name: str
    period: str
    class_type: str
    textbook_version: str
    suitable_for: str
    service_type: str
    fact_name: str
    fact_value: str
    statement: str
    relation_type: str
    relation_from: str
    relation_to: str
    campaign_name: str
    campaign_content: str
    campaign_scope: str
    campaign_student_scope: str
    campaign_start: str
    campaign_end: str
    campaign_terms: str
    campaign_fulfillment: str
    campaign_status: str
    scope_status: str
    suggested_usage_status: str
    discard_reason: str
    conflict_key: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clean_statement(text: str, maximum: int = 500) -> str:
    value = _URL_PATTERN.sub("[链接]", text)
    value = _PHONE_PATTERN.sub("[手机号]", value)
    value = " ".join(value.split())
    return value if len(value) <= maximum else value[: maximum - 1].rstrip() + "…"


def _candidate_key(*parts: object) -> str:
    payload = "\0".join(str(value) for value in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _course_identity(course_name: str) -> str:
    value = re.sub(r"20\d{2}|(?<!\d)\d{2}(?!\d)", "", course_name)
    value = re.sub(
        r"产品说明|课程说明|招生物料站?|宣传版|美化版|大纲|常规年级|初始年级",
        "",
        value,
    )
    value = re.sub(r"[\s_~～·\-—（）()【】\[\]]+", "", value)
    return value or course_name


def _infer_domains(value: str) -> list[str]:
    domains = [
        domain for domain, terms in _DOMAIN_TERMS if any(term in value for term in terms)
    ]
    return list(dict.fromkeys(domains))


def _infer_stage(value: str) -> str:
    if any(term in value for term in ("启蒙", "幼儿", "大班", "中班", "幼升小")):
        return "启蒙"
    if any(term in value for term in ("小学", "一年级", "二年级", "三年级", "四年级", "五年级", "六年级", "小升初")):
        return "小学"
    if any(term in value for term in ("初中", "初一", "初二", "初三", "七年级", "八年级", "九年级")):
        return "初中"
    if "高中" in value or "高考" in value:
        return "高中"
    return ""


def _infer_subject(value: str) -> str:
    value = value.replace("招生物料", "")
    subjects = [
        term
        for term in ("数学", "语文", "英语", "物理", "化学", "历史", "道法", "生物", "地理")
        if term in value
    ]
    return "/".join(subjects)


def _infer_period(value: str) -> str:
    years = list(dict.fromkeys(re.findall(r"(?<!\d)(20\d{2})(?!\d)", value)))
    seasons = "".join(dict.fromkeys(re.findall(r"[春夏秋冬]", value)))
    return "".join(years[:1]) + seasons


def _infer_scope(source_name: str, value: str) -> tuple[str, str]:
    combined = f"{source_name} {value}"
    if "政策" in source_name and any(term in combined for term in ("天津", "小升初", "招生")):
        return "out_of_scope", "天津升学政策不在本次知识领域"
    if any(term in combined for term in ("上海", "广州")) and "天津适用" not in combined:
        return "out_of_scope", "其他地区独有内容"
    if any(term in combined for term in ("全国班", "全国版", "全国小高")):
        return "pending", "全国资料是否服务天津需核对"
    return "tianjin", ""


def _infer_usage(value: str, scope_status: str) -> tuple[str, str]:
    if scope_status == "out_of_scope":
        return "discarded", "范围外"
    if scope_status == "pending":
        return "pending", "适用天津范围待核对"
    if any(term in value for term in _INTERNAL_TERMS):
        return "discarded", "内部经营、人员、排期或系统管理信息"
    if any(term in value for term in _MARKETING_RISK_TERMS):
        return "discarded", "无法核实的结果性营销主张"
    if _PHONE_PATTERN.search(value) or _IDENTIFIER_PATTERN.search(value):
        return "discarded", "真实联系方式、学员、订单或员工标识符"
    return "advisor", ""


def suggest_block_disposition(
    *, source_name: str, locator: str, text: str
) -> tuple[str, str, str]:
    combined = f"{source_name} {locator} {text}"
    scope_status, scope_reason = _infer_scope(source_name, combined)
    usage_status, discard_reason = _infer_usage(combined, scope_status)
    return usage_status, discard_reason or scope_reason, scope_status


def _infer_dates(value: str) -> tuple[str, str]:
    dates: list[str] = []
    for year, month, day in _DATE_PATTERN.findall(value):
        rendered = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        if rendered not in dates:
            dates.append(rendered)
    return (
        dates[0] if dates else "",
        dates[1] if len(dates) > 1 else "",
    )


def _fact(value: str, textbook_version: str) -> tuple[str, str]:
    lesson = _LESSON_PATTERN.search(value)
    if lesson:
        return "lesson_count", lesson.group(1)
    fee = _FEE_PATTERN.search(value)
    if fee:
        return "price", fee.group(1)
    if textbook_version:
        return "textbook_version", textbook_version
    if any(term in value for term in ("回放", "答疑", "设备", "服务")):
        return "service", ""
    return "course_content", ""


def infer_semantic_candidates(
    *,
    source_name: str,
    revision_id: int,
    block_id: int,
    block_key: str,
    locator: str,
    text: str,
) -> list[SemanticCandidate]:
    statement = _clean_statement(text)
    if not statement:
        return []
    combined = f"{source_name} {locator} {statement}"
    domains = _infer_domains(combined)
    if not domains:
        return []
    stage = _infer_stage(combined)
    grade_match = _GRADE_PATTERN.search(combined)
    grade = grade_match.group(0) if grade_match else ""
    subject = _infer_subject(combined)
    period = _infer_period(combined)
    class_match = _CLASS_PATTERN.search(combined)
    class_type = class_match.group(0) if class_match else ""
    textbook_match = _TEXTBOOK_PATTERN.search(combined)
    textbook_version = textbook_match.group(0) if textbook_match else ""
    scope_status, scope_reason = _infer_scope(source_name, combined)
    usage_status, discard_reason = _infer_usage(combined, scope_status)
    if scope_reason and not discard_reason:
        discard_reason = scope_reason
    course_name = Path(source_name).stem
    course_identity = _course_identity(course_name)
    fact_name, fact_value = _fact(statement, textbook_version)
    campaign_start, campaign_end = _infer_dates(statement)
    is_campaign = any(term in combined for term in _CAMPAIGN_TERMS)
    records: list[SemanticCandidate] = []

    for domain in domains:
        record_kind = "campaign" if domain == BUSINESS_DOMAINS[7] and is_campaign else "fact"
        campaign_status = "pending" if record_kind == "campaign" else ""
        candidate_key = _candidate_key(
            SEMANTIC_EXTRACTOR_VERSION,
            revision_id,
            block_id,
            record_kind,
            domain,
            fact_name,
            fact_value,
        )
        conflict_key = _candidate_key(
            record_kind,
            domain,
            stage,
            grade,
            subject,
            course_identity,
            period,
            class_type,
            fact_name,
        )
        records.append(
            SemanticCandidate(
                candidate_key=candidate_key,
                revision_id=revision_id,
                block_id=block_id,
                block_key=block_key,
                record_kind=record_kind,
                business_domain=domain,
                stage=stage,
                grade=grade,
                subject=subject,
                course_name=course_name,
                period=period,
                class_type=class_type,
                textbook_version=textbook_version,
                suitable_for=statement if "适合" in statement else "",
                service_type=fact_value if fact_name == "service" else "",
                fact_name=fact_name,
                fact_value=fact_value,
                statement=statement,
                relation_type="",
                relation_from="",
                relation_to="",
                campaign_name=course_name if record_kind == "campaign" else "",
                campaign_content=statement if record_kind == "campaign" else "",
                campaign_scope=course_name if record_kind == "campaign" else "",
                campaign_student_scope=(
                    "老生" if "老生" in statement or "续报" in statement else "新生" if "新生" in statement else ""
                ),
                campaign_start=campaign_start if record_kind == "campaign" else "",
                campaign_end=campaign_end if record_kind == "campaign" else "",
                campaign_terms=statement if record_kind == "campaign" else "",
                campaign_fulfillment="",
                campaign_status=campaign_status,
                scope_status=scope_status,
                suggested_usage_status=usage_status,
                discard_reason=discard_reason,
                conflict_key=conflict_key,
            )
        )

    for relation_type, cues in _RELATION_CUES:
        if not any(cue in statement for cue in cues):
            continue
        domain = (
            BUSINESS_DOMAINS[4]
            if relation_type in {"prerequisite_of", "continues_to", "overlaps_with", "alternative_to"}
            else BUSINESS_DOMAINS[1]
            if relation_type == "suitable_for"
            else BUSINESS_DOMAINS[3]
            if relation_type == "uses_textbook"
            else BUSINESS_DOMAINS[5]
            if relation_type in {"taught_by", "includes_service"}
            else BUSINESS_DOMAINS[7]
        )
        candidate_key = _candidate_key(
            SEMANTIC_EXTRACTOR_VERSION,
            revision_id,
            block_id,
            "relation",
            relation_type,
        )
        records.append(
            SemanticCandidate(
                candidate_key=candidate_key,
                revision_id=revision_id,
                block_id=block_id,
                block_key=block_key,
                record_kind="relation",
                business_domain=domain,
                stage=stage,
                grade=grade,
                subject=subject,
                course_name=course_name,
                period=period,
                class_type=class_type,
                textbook_version=textbook_version,
                suitable_for=statement if relation_type == "suitable_for" else "",
                service_type=statement if relation_type == "includes_service" else "",
                fact_name="",
                fact_value="",
                statement=statement,
                relation_type=relation_type,
                relation_from=course_name,
                relation_to=(textbook_version or statement),
                campaign_name="",
                campaign_content="",
                campaign_scope="",
                campaign_student_scope="",
                campaign_start="",
                campaign_end="",
                campaign_terms="",
                campaign_fulfillment="",
                campaign_status="",
                scope_status=scope_status,
                suggested_usage_status=usage_status,
                discard_reason=discard_reason,
                conflict_key="",
            )
        )
    return records


def query_semantic_filters(query: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    grade = _GRADE_PATTERN.search(query)
    if grade:
        filters["grade"] = grade.group(0)
    subject = _infer_subject(query)
    if subject:
        filters["subject"] = subject
    class_type = _CLASS_PATTERN.search(query)
    if class_type:
        filters["class_type"] = class_type.group(0)
    textbook = _TEXTBOOK_PATTERN.search(query)
    if textbook:
        filters["textbook_version"] = textbook.group(0)
    period = _infer_period(query)
    if period:
        filters["period"] = period
    return filters


def semantic_row_matches(row: object, filters: dict[str, str]) -> bool:
    for field, expected in filters.items():
        actual = str(row[field] or "")  # type: ignore[index]
        if actual and expected.casefold() not in actual.casefold():
            return False
    return True


def requests_campaign_information(query: str) -> bool:
    return any(term in query for term in _CAMPAIGN_TERMS)


def requests_internal_information(query: str) -> bool:
    compact = " ".join(query.split())
    restricted_terms = (
        "经营目标",
        "销售目标",
        "业绩目标",
        "续报目标",
        "续报率",
        "转化率",
        "员工编号",
        "负责人联系方式",
        "内部排期",
        "项目进度",
        "权限路径",
    )
    if any(term in compact for term in restricted_terms):
        return True
    return "内部" in compact and any(
        term in compact for term in ("目标", "负责人", "员工", "排期", "进度", "权限")
    )


def requests_national_tianjin_compatibility(query: str) -> bool:
    return "全国" in query and "天津" in query


def requires_live_system_lookup(query: str) -> bool:
    compact = " ".join(query.split())
    patterns = (
        r"App.*(?:没有|没显示|看不到).*(?:课|课程)",
        r"(?:当前|现在).*(?:班级|班里|这个班|该班).*(?:名额|余位|满班)",
        r"(?:订单|付款|支付|缴费).*(?:状态|成功|到账|记录)",
        r"(?:是否|有没有).*(?:报名成功|付款成功)",
    )
    return any(re.search(pattern, compact, re.IGNORECASE) for pattern in patterns)
