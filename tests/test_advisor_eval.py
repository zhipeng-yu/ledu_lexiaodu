from __future__ import annotations

import json
import re
from pathlib import Path

from lexiaodu.knowledge_semantics import (
    requests_internal_information,
    requests_national_tianjin_compatibility,
    requests_out_of_scope_region,
    requests_private_information,
    requires_live_system_lookup,
)


EVAL_PATH = Path(__file__).parent / "fixtures" / "anonymized_advisor_eval.json"


def test_anonymized_advisor_eval_covers_required_scenarios_without_identifiers() -> None:
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))

    assert len(cases) == 27
    assert {case["id"] for case in cases} == {
        "class_s_vs_aplus",
        "summer_autumn_continuity",
        "lesson_count",
        "tianjin_textbook",
        "grade_subject_content",
        "online_replay_device",
        "teachers_and_method",
        "enrollment_payment_refund",
        "active_campaign",
        "expired_campaign",
        "table_image_only",
        "similar_content_different_goal",
        "national_tianjin_scope",
        "internal_information_block",
        "internal_teaching_execution_block",
        "renewal_communication_style",
        "private_teacher_contact_block",
        "private_student_case_block",
        "live_app_order_status",
        "tianjin_textbook_specific",
        "reviewed_teacher_specific",
        "lesson_count_specific",
        "class_choice_specific",
        "refund_specific",
        "other_region_induction",
        "reviewed_humanities_teacher",
        "teacher_year_version_conflict",
    }
    rendered = json.dumps(cases, ensure_ascii=False)
    assert "http://" not in rendered and "https://" not in rendered
    assert not re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", rendered)
    for case in cases:
        assert case["question"].strip()
        assert case["expected_points"]
        assert isinstance(case["must_ask"], list)
        assert case["forbidden"]
        assert requires_live_system_lookup(case["question"]) is bool(
            case["requires_system_lookup"]
        )
    internal_cases = [
        case
        for case in cases
        if case["id"]
        in {"internal_information_block", "internal_teaching_execution_block"}
    ]
    assert all(
        requests_internal_information(case["question"])
        for case in internal_cases
    )
    no_fact_cases = [
        case for case in cases if case.get("requires_no_facts", False)
    ]
    assert {case["id"] for case in no_fact_cases} == {
        "internal_teaching_execution_block",
        "renewal_communication_style",
        "private_teacher_contact_block",
        "private_student_case_block",
    }
    private_cases = [
        case for case in no_fact_cases if case["origin"] == "privacy_acceptance"
    ]
    assert all(
        requests_private_information(case["question"])
        for case in private_cases
    )
    national = next(
        case for case in cases if case["id"] == "national_tianjin_scope"
    )
    assert requests_national_tianjin_compatibility(national["question"])
    other_region = next(
        case for case in cases if case["id"] == "other_region_induction"
    )
    assert requests_out_of_scope_region(other_region["question"])
