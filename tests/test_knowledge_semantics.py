from __future__ import annotations

import pytest

from lexiaodu.knowledge_semantics import (
    requests_communication_guidance,
    requests_enrollment_rules,
    requests_class_selection,
    requests_online_course_service,
    requests_out_of_scope_region,
    requests_internal_information,
    requests_product_overview,
    requests_style_only_guidance,
    requests_teacher_information,
    suggest_block_disposition,
)


@pytest.mark.parametrize(
    "text",
    [
        "本月分校续报目标及负责人排期",
        "项目招生目标与内部通达进度",
        "本阶段经营目标和转化目标",
    ],
)
def test_internal_business_targets_are_discarded(text: str) -> None:
    usage, reason, scope = suggest_block_disposition(
        source_name="续报方案.docx",
        locator="内部执行",
        text=text,
    )

    assert usage == "discarded"
    assert scope == "tianjin"
    assert "内部经营" in reason


@pytest.mark.parametrize(
    "query",
    [
        "内部备课考核和排课要求是什么",
        "教师考核、师训和触达要求是什么",
        "这个项目的教学执行安排是什么",
    ],
)
def test_internal_teaching_execution_queries_are_blocked(query: str) -> None:
    assert requests_internal_information(query)


@pytest.mark.parametrize("query", ["上海课程能给天津孩子用吗", "广州独有教材怎么样"])
def test_other_region_questions_are_out_of_scope(query: str) -> None:
    assert requests_out_of_scope_region(query)


def test_other_region_name_alone_does_not_block_teacher_lookup() -> None:
    assert not requests_out_of_scope_region("上海交通大学毕业的老师有什么经历")


def test_class_comparison_uses_reviewed_policy_only() -> None:
    assert requests_class_selection("S班和A+班有什么区别，孩子适合哪个")
    assert not requests_class_selection("孩子现在在S班")


def test_teacher_background_uses_reviewed_policy_only() -> None:
    assert requests_teacher_information("谢云琦老师有什么公开教学经历")
    assert requests_teacher_information("老师背景和课堂怎么教")
    assert not requests_teacher_information("老师您好")


def test_stable_enrollment_rules_use_reviewed_policy_only() -> None:
    assert requests_enrollment_rules("报名缴费续报转班退费有什么规则")
    assert requests_enrollment_rules("开课后如何退费")
    assert not requests_enrollment_rules("订单付款状态")


def test_online_replay_service_uses_reviewed_policy_only() -> None:
    assert requests_online_course_service("线上课程能回放吗，需要什么设备")
    assert not requests_online_course_service("孩子上线上课")


def test_product_overview_queries_use_curated_policy() -> None:
    assert requests_product_overview("乐读有哪些课程产品")
    assert requests_product_overview("小学都有什么课程")
    assert requests_product_overview("课程产品总览")
    assert not requests_product_overview("三年级数学课程内容是什么")
    assert not requests_product_overview("启蒙数学课程产品课时")


def test_renewal_communication_can_use_style_without_factual_rag() -> None:
    assert requests_communication_guidance("续报期家长一直不回复，怎么温和沟通")
    assert requests_style_only_guidance("续报期家长一直不回复，怎么温和沟通")
    assert not requests_style_only_guidance("家长问当前续报优惠，应该怎么回复")
