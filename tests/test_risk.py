from lexiaodu.risk import (
    DeterministicRiskRules,
    RiskLevel,
    TransferStatus,
)


def test_complaint_rule_is_high_risk_and_requires_transfer() -> None:
    assessment = DeterministicRiskRules().assess(
        "家长要求退款并表示要投诉",
        "我先帮您处理。",
        has_policy_evidence=True,
    )

    assert assessment.level is RiskLevel.HIGH
    assert assessment.transfer_status is TransferStatus.REQUIRED
    assert assessment.requires_copy_confirmation
    assert any("投诉" in warning for warning in assessment.warnings)


def test_missing_policy_evidence_is_always_high_risk() -> None:
    assessment = DeterministicRiskRules().assess(
        "家长咨询活动",
        "我先核实。",
        has_policy_evidence=False,
    )

    assert assessment.level is RiskLevel.HIGH
    assert "未检索到权威制度依据" in assessment.warnings[0]


def test_fee_rule_is_medium_risk_when_policy_evidence_exists() -> None:
    assessment = DeterministicRiskRules().assess(
        "家长询问收费标准",
        "请参考制度说明。",
        has_policy_evidence=True,
    )

    assert assessment.level is RiskLevel.MEDIUM
    assert assessment.transfer_status is TransferStatus.REVIEW_RECOMMENDED
    assert not assessment.requires_copy_confirmation


def test_regular_grounded_reply_is_low_risk() -> None:
    assessment = DeterministicRiskRules().assess(
        "家长想了解阅读安排",
        "本周安排两次共读。",
        has_policy_evidence=True,
    )

    assert assessment.level is RiskLevel.LOW
    assert assessment.transfer_status is TransferStatus.NOT_REQUIRED
