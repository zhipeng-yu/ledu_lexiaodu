from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "低风险"
    MEDIUM = "中风险"
    HIGH = "高风险"


class TransferStatus(StrEnum):
    NOT_REQUIRED = "无需转人工"
    REVIEW_RECOMMENDED = "建议人工复核"
    REQUIRED = "必须转人工"


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: RiskLevel
    warnings: tuple[str, ...]
    transfer_status: TransferStatus

    @property
    def requires_copy_confirmation(self) -> bool:
        return self.level is RiskLevel.HIGH


_HIGH_RISK_RULES = (
    (
        ("退款", "退费", "投诉", "举报", "曝光", "律师", "起诉", "报警"),
        "涉及退款、投诉或法律争议，必须转人工处理。",
    ),
    (
        ("受伤", "安全事故", "人身安全", "生病", "过敏", "医疗"),
        "涉及人身安全或健康信息，必须转人工处理。",
    ),
    (
        ("隐私", "泄露", "个人信息", "手机号外泄"),
        "涉及隐私或个人信息，必须转人工处理。",
    ),
    (
        ("体罚", "欺凌", "霸凌"),
        "涉及儿童保护事件，必须转人工处理。",
    ),
)

_MEDIUM_RISK_RULES = (
    (
        ("保证", "承诺", "一定会", "百分之百", "包过"),
        "包含保证或结果承诺，请复核表述。",
    ),
    (
        ("收费", "价格", "优惠", "合同", "发票", "请假", "补课", "转班", "退课"),
        "涉及费用或服务规则，请核对适用条件。",
    ),
)


class DeterministicRiskRules:
    """Keyword and evidence rules with deterministic, model-independent output."""

    def assess(
        self,
        transcript: str,
        reply: str,
        *,
        has_policy_evidence: bool,
    ) -> RiskAssessment:
        content = f"{transcript}\n{reply}".casefold()
        high_warnings = tuple(
            warning
            for keywords, warning in _HIGH_RISK_RULES
            if any(keyword.casefold() in content for keyword in keywords)
        )
        evidence_warning = (
            ()
            if has_policy_evidence
            else ("未检索到权威制度依据，回复不得直接对外承诺。",)
        )
        if high_warnings or evidence_warning:
            return RiskAssessment(
                RiskLevel.HIGH,
                high_warnings + evidence_warning,
                TransferStatus.REQUIRED,
            )

        medium_warnings = tuple(
            warning
            for keywords, warning in _MEDIUM_RISK_RULES
            if any(keyword.casefold() in content for keyword in keywords)
        )
        if medium_warnings:
            return RiskAssessment(
                RiskLevel.MEDIUM,
                medium_warnings,
                TransferStatus.REVIEW_RECOMMENDED,
            )
        return RiskAssessment(
            RiskLevel.LOW,
            ("未命中确定性高、中风险规则；发送前仍请核对事实。",),
            TransferStatus.NOT_REQUIRED,
        )
