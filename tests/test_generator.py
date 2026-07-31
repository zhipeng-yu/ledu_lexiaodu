from pathlib import Path
from types import SimpleNamespace

import pytest

from lexiaodu.advice import AdviceService
from lexiaodu.generator import (
    GenerationError,
    GenerationRequest,
    OpenAICompatibleGenerator,
    SimulatedGenerator,
)
from lexiaodu.knowledge import KnowledgeBase, KnowledgeType, SearchResult
from lexiaodu.risk import RiskLevel


def _result(
    knowledge_type: KnowledgeType,
    document: str,
    evidence: str,
) -> SearchResult:
    return SearchResult(
        knowledge_type=knowledge_type,
        document_name=document,
        locator="办理规则",
        evidence=evidence,
        score=3.5,
    )


def test_simulated_generator_uses_retrieved_policy_content() -> None:
    policy = _result(
        KnowledgeType.POLICY,
        "请假制度.txt",
        "请假须由监护人提前提交申请。",
    )
    draft = SimulatedGenerator().generate(
        GenerationRequest(
            transcript="孩子明天请假怎么办？",
            policy_results=(policy,),
            style_results=(),
        )
    )

    assert "请假制度.txt" in draft.concern_summary
    assert policy.evidence.rstrip("。") in draft.wechat_reply
    assert "请假制度.txt" in draft.wechat_reply


def test_simulated_generator_end_to_end_uses_real_knowledge_search(
    tmp_path: Path,
) -> None:
    root = tmp_path / "knowledge"
    policy = root / "policy"
    style = root / "style_case"
    policy.mkdir(parents=True)
    style.mkdir()
    (policy / "请假制度.txt").write_text(
        "# 申请流程\n请假须由监护人提前提交星印申请。",
        encoding="utf-8",
    )
    knowledge = KnowledgeBase(root, tmp_path / "knowledge.sqlite3")
    knowledge.rebuild()

    suggestion = AdviceService(
        knowledge,
        SimulatedGenerator(),
    ).create("家长想了解星印请假申请")

    assert suggestion.facts
    assert suggestion.facts[0].document_name == "请假制度.txt"
    assert "星印申请" in suggestion.wechat_reply


def test_advice_service_retrieves_both_types_before_generation() -> None:
    policy = _result(KnowledgeType.POLICY, "制度.txt", "监护人提交申请。")
    style = _result(KnowledgeType.STYLE_CASE, "案例.txt", "先表示理解。")

    class FakeKnowledge:
        def __init__(self) -> None:
            self.calls: list[tuple[str, KnowledgeType]] = []

        def search(
            self,
            query: str,
            knowledge_type: KnowledgeType,
        ) -> list[SearchResult]:
            self.calls.append((query, knowledge_type))
            return [policy] if knowledge_type is KnowledgeType.POLICY else [style]

    class SpyGenerator:
        request: GenerationRequest | None = None

        def generate(self, request: GenerationRequest):
            self.request = request
            return SimulatedGenerator().generate(request)

    knowledge = FakeKnowledge()
    generator = SpyGenerator()
    suggestion = AdviceService(knowledge, generator).create("家长：如何请假")

    assert knowledge.calls == [
        ("家长：如何请假", KnowledgeType.POLICY),
        ("家长：如何请假", KnowledgeType.STYLE_CASE),
    ]
    assert generator.request is not None
    assert generator.request.policy_results == (policy,)
    assert generator.request.style_results == (style,)
    assert suggestion.facts == (policy,)
    assert suggestion.risk.level is not RiskLevel.HIGH


def test_openai_compatible_generator_uses_injected_client_and_model() -> None:
    policy = _result(KnowledgeType.POLICY, "制度.txt", "需要提前申请。")

    class Completions:
        def __init__(self) -> None:
            self.arguments = {}

        def create(self, **kwargs):
            self.arguments = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"concern_summary":"家长关注请假",'
                                '"wechat_reply":"您好，我来协助核实。"}'
                            )
                        )
                    )
                ]
            )

    completions = Completions()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    generator = OpenAICompatibleGenerator(client, "doubao-model")
    draft = generator.generate(
        GenerationRequest("请假怎么办", (policy,), ())
    )

    assert draft.concern_summary == "家长关注请假"
    assert draft.wechat_reply == "您好，我来协助核实。"
    assert completions.arguments["model"] == "doubao-model"
    assert completions.arguments["response_format"] == {
        "type": "json_object"
    }
    user_message = completions.arguments["messages"][1]["content"]
    assert "需要提前申请" in user_message
    assert "制度.txt" in user_message


def test_openai_compatible_generator_rejects_unstructured_response() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="not json"))
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: response)
        )
    )

    with pytest.raises(GenerationError, match="无效"):
        OpenAICompatibleGenerator(client, "model").generate(
            GenerationRequest("问题", (), ())
        )
