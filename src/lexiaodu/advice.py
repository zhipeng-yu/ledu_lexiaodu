from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from lexiaodu.generator import GenerationRequest, Generator
from lexiaodu.knowledge import KnowledgeBase, KnowledgeType, SearchResult
from lexiaodu.knowledge_semantics import (
    requests_internal_information,
    requests_private_information,
    requests_style_only_guidance,
    requires_live_system_lookup,
)
from lexiaodu.risk import DeterministicRiskRules, RiskAssessment


@dataclass(frozen=True, slots=True)
class AdviceSuggestion:
    suggestion_id: str
    concern_summary: str
    wechat_reply: str
    facts: tuple[SearchResult, ...]
    risk: RiskAssessment


class AdviceService:
    """Retrieve first, then generate and apply local risk rules."""

    def __init__(
        self,
        knowledge: KnowledgeBase,
        generator: Generator,
        risk_rules: DeterministicRiskRules | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._generator = generator
        self._risk_rules = risk_rules or DeterministicRiskRules()

    def create(self, transcript: str) -> AdviceSuggestion:
        if not transcript.strip():
            raise ValueError("对话内容不能为空")
        search_advice = getattr(
            self._knowledge, "search_advice_policy", None
        )
        system_lookup = requires_live_system_lookup(transcript)
        internal_lookup = requests_internal_information(transcript)
        private_lookup = requests_private_information(transcript)
        style_only = requests_style_only_guidance(transcript)
        policy_results = (
            ()
            if system_lookup or internal_lookup or private_lookup or style_only
            else tuple(
                search_advice(transcript)
                if callable(search_advice)
                else self._knowledge.search(transcript, KnowledgeType.POLICY)
            )
        )
        style_results = (
            ()
            if internal_lookup or private_lookup
            else tuple(
                self._knowledge.search(transcript, KnowledgeType.STYLE_CASE)
            )
        )
        draft = self._generator.generate(
            GenerationRequest(
                transcript=transcript,
                policy_results=policy_results,
                style_results=style_results,
                requires_system_lookup=system_lookup,
            )
        )
        risk = self._risk_rules.assess(
            transcript,
            draft.wechat_reply,
            has_policy_evidence=bool(policy_results),
        )
        return AdviceSuggestion(
            suggestion_id=uuid4().hex,
            concern_summary=draft.concern_summary,
            wechat_reply=draft.wechat_reply,
            facts=policy_results,
            risk=risk,
        )
