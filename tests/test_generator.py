import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lexiaodu.advice import AdviceService
from lexiaodu.generator import (
    GenerationError,
    GenerationRequest,
    OpenAICompatibleGenerator,
    SimulatedGenerator,
    build_openai_messages,
)
from lexiaodu.knowledge import KnowledgeBase, KnowledgeType, SearchResult
from lexiaodu.risk import RiskLevel


CUSTOMER_SERVICE_PHRASES = (
    "您好",
    "理解您的顾虑",
    "根据规定",
    "我方",
    "请耐心等待",
    "不能保证",
    "不能承诺",
    "无法保障",
    "没有检索到依据",
    "转人工核实",
)


def _reply_paragraphs(reply: str) -> list[str]:
    return [
        paragraph.strip()
        for paragraph in reply.splitlines()
        if paragraph.strip()
    ]


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
    assert "请假制度.txt" not in draft.wechat_reply
    assert 2 <= len(_reply_paragraphs(draft.wechat_reply)) <= 3
    assert draft.wechat_reply.count("家长") == 1
    assert not any(
        phrase in draft.wechat_reply for phrase in CUSTOMER_SERVICE_PHRASES
    )


def test_simulated_generator_handles_missing_policy_without_customer_service_copy(
) -> None:
    draft = SimulatedGenerator().generate(
        GenerationRequest(
            transcript="这个班下周几点开课？",
            policy_results=(),
            style_results=(),
        )
    )

    assert _reply_paragraphs(draft.wechat_reply) == [
        "家长，这个我先帮您确认一下哈。",
        "我把具体安排问清楚后就回复您，您不用自己来回找。",
    ]
    assert not any(
        phrase in draft.wechat_reply for phrase in CUSTOMER_SERVICE_PHRASES
    )


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


@pytest.mark.parametrize(
    "question",
    [
        "报名后 App 为什么没有显示课程？",
        "现在这个班还有名额吗？",
        "我的订单付款状态成功了吗？",
    ],
)
def test_live_business_status_never_uses_rag_facts(question: str) -> None:
    policy = _result(KnowledgeType.POLICY, "旧记录.txt", "订单已经付款成功。")

    class FakeKnowledge:
        def search(
            self, query: str, knowledge_type: KnowledgeType
        ) -> list[SearchResult]:
            return [policy]

    suggestion = AdviceService(
        FakeKnowledge(),  # type: ignore[arg-type]
        SimulatedGenerator(),
    ).create(question)

    assert suggestion.facts == ()
    assert "查询实际业务系统" in suggestion.concern_summary
    assert "订单已经付款成功" not in suggestion.wechat_reply
    assert "系统里核对" in suggestion.wechat_reply


def test_internal_operations_query_never_uses_rag_facts() -> None:
    policy = _result(
        KnowledgeType.POLICY,
        "内部资料.txt",
        "内部续报目标和负责人排期。",
    )

    class FakeKnowledge:
        def search(
            self, query: str, knowledge_type: KnowledgeType
        ) -> list[SearchResult]:
            return [policy]

    suggestion = AdviceService(
        FakeKnowledge(),  # type: ignore[arg-type]
        SimulatedGenerator(),
    ).create("这个项目的内部续报目标、负责人和排期是什么？")

    assert suggestion.facts == ()
    assert "内部续报目标" not in suggestion.wechat_reply


def test_openai_messages_separate_policy_facts_from_style_examples() -> None:
    policy = _result(KnowledgeType.POLICY, "课程规则.txt", "每周六上课。")
    style = _result(
        KnowledgeType.STYLE_CASE,
        "顾问话术.txt",
        "家长，这个我帮您看一下哈～",
    )

    messages = build_openai_messages(
        GenerationRequest("周几上课？", (policy,), (style,))
    )

    assert [message["role"] for message in messages] == ["system", "user"]
    system_prompt = messages[0]["content"]
    assert "style_results 只用于参考表达方式" in system_prompt
    assert "组织成 2 到 3 段短消息" in system_prompt
    assert "不得猜测监护人性别" in system_prompt
    assert "例如出现‘乐乐妈妈’就以‘乐乐妈妈，’开头" in system_prompt
    assert "全篇统一使用‘您’" in system_prompt
    assert "‘性价比高’" in system_prompt
    assert "主动推进的动作也必须有事实依据" in system_prompt
    assert "不得补充‘免费’‘预约入口’或‘发送链接’" in system_prompt
    payload = json.loads(messages[1]["content"])
    assert set(payload) == {
        "transcript",
        "policy_results",
        "style_results",
        "requires_system_lookup",
    }
    assert payload["requires_system_lookup"] is False
    assert payload["policy_results"] == [
        {
            "document": "课程规则.txt",
            "locator": "办理规则",
            "evidence": "每周六上课。",
        }
    ]
    assert payload["style_results"] == [
        {
            "document": "顾问话术.txt",
            "locator": "办理规则",
            "example": "家长，这个我帮您看一下哈～",
        }
    ]


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
                                '"wechat_reply":"家长，这个我帮您看一下哈。\\n'
                                '我确认好后回复您。"}'
                            )
                        )
                    )
                ]
            )

    completions = Completions()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    generator = OpenAICompatibleGenerator(
        client,
        "doubao-model",
        max_tokens=512,
        extra_body={"thinking": {"type": "disabled"}},
    )
    draft = generator.generate(
        GenerationRequest("请假怎么办", (policy,), ())
    )

    assert draft.concern_summary == "家长关注请假"
    assert draft.wechat_reply == "家长，这个我帮您看一下哈。\n我确认好后回复您。"
    assert completions.arguments["model"] == "doubao-model"
    assert completions.arguments["response_format"] == {
        "type": "json_object"
    }
    assert completions.arguments["max_tokens"] == 512
    assert completions.arguments["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    user_payload = json.loads(completions.arguments["messages"][1]["content"])
    assert user_payload["policy_results"][0]["evidence"] == "需要提前申请。"
    assert user_payload["policy_results"][0]["document"] == "制度.txt"
    assert user_payload["style_results"] == []


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


def test_openai_compatible_generator_rejects_invalid_token_limit() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        OpenAICompatibleGenerator(object(), "model", max_tokens=0)
