# Original Document AI Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Doubao the primary multi-turn advisor while grounding every company-specific statement in one to three unchanged, approved source files with enforceable locators, local risk checks, and human-controlled reply generation.

**Architecture:** A structured `AdvisorPlanner` reads the current conversation context and decides whether to discuss, ask one question, or offer reply preparation. When the advisor confirms generation, a metadata-only `DocumentRouter` chooses approved current files, an Ark gateway uploads or reuses unchanged file hashes through the transport proven by the capability plan, and a structured generator returns linked reply segments and claims. A local validator removes ungrounded company segments, applies deterministic risk rules, and persists the result before the chat window renders a human-editable reply card and source drawer.

**Tech Stack:** Python 3.11, PySide6 6.x, SQLite, existing OpenAI SDK 2.x or the verified Ark transport, pytest 8.x, JSON structured outputs

## Global Constraints

- Start only after the independent chat/context plan passes and the capability report marks the target format and transport `GO`.
- Enable production original-document behavior only through `LEXIAODU_ADVISOR_MODE=original_documents`; retain `simulated` as the default until the staged acceptance task passes.
- Never call local OCR, Office/XML extraction, PDF text extraction, chunking, or knowledge import on company source files in this path.
- Hash files and inspect file-level metadata only. Upload the exact bytes whose SHA-256 was cataloged.
- Default every catalog entry to upload denied. The ordinary chat UI cannot grant upload permission or change document authority/version.
- Select at most three current documents. Medium/low confidence requires advisor confirmation or one focused question.
- Treat consultant examples as style/strategy only. They can never satisfy a company fact citation.
- Require every company reply segment to reference a validated claim with document ID, current hash, and page/slide/section locator.
- Remove invalid company segments before constructing copyable text. Never rely on warning text beside an ungrounded copyable claim.
- Do not expose chain-of-thought. Persist only the bounded planner fields defined below.
- Do not answer live seats, orders, payment, attendance, or app state from documents.
- Never auto-send to parents. Formal reply cards require explicit advisor confirmation and remain editable.
- Use the project-local `.venv` for every Python command.

---

## File Structure

- Modify `src/lexiaodu/config.py`, `config/app.toml`, `.env.example`, and `tests/test_config.py` for catalog, Ark, and feature-gate settings.
- Create `src/lexiaodu/document_catalog.py` and `tests/test_document_catalog.py` for file metadata, permissions, versions, hashes, Ark mappings, and audit events.
- Create `scripts/manage_document_catalog.py` and `tests/test_document_catalog_cli.py` for administrator-only registration/refresh/report commands.
- Create `src/lexiaodu/advisor_model.py` and `tests/test_advisor_model.py` for planner and structured model contracts.
- Create `src/lexiaodu/document_router.py` and `tests/test_document_router.py` for deterministic candidate scoring and confirmation branches.
- Create `src/lexiaodu/ark_gateway.py` and `tests/test_ark_gateway.py` for unchanged upload/reuse/retry/audit using the single verified transport.
- Create `src/lexiaodu/advisor_service.py` and `tests/test_advisor_service.py` for planning, generation, evidence validation, and risk orchestration.
- Modify `src/lexiaodu/chat_controller.py`, `src/lexiaodu/chat_window.py`, and their tests for discussion turns, document confirmation, formal generation, source drawer, and regeneration.
- Modify `src/lexiaodu/app.py`, `tests/test_app.py`, `README.md`, and `docs/MANUAL_TEST_CHECKLIST.md` for mode wiring and staged acceptance.

### Task 1: Document Catalog Settings and Metadata-Only Store

**Files:**
- Modify: `src/lexiaodu/config.py`
- Modify: `config/app.toml`
- Modify: `tests/test_config.py`
- Create: `src/lexiaodu/document_catalog.py`
- Create: `tests/test_document_catalog.py`

**Interfaces:**
- Produces `DocumentSettings(catalog_path, allowed_roots, maximum_candidates=3)`.
- Produces immutable `DocumentRecord` and `ArkFileMapping` records.
- Produces `DocumentCatalog.register`, `refresh`, `list_current`, `get_current`, `save_mapping`, `invalidate_mapping`, and `record_audit`.

- [ ] **Step 1: Write failing settings, permission, version, and hash tests**

Use temporary PDF/DOCX/PPTX byte fixtures that are never parsed. Assert paths outside allowed roots, unsupported extensions, symlink escapes, duplicate current versions, and default upload denial are rejected. Modify one byte after registration and assert `refresh` changes the hash, marks the old Ark mapping stale, and never reads document text.

```python
def test_changed_file_invalidates_uploaded_mapping(tmp_path, catalog):
    path = write_fake_source(tmp_path / "approved" / "course.pdf", b"v1")
    record = catalog.register(path, metadata(), allow_upload=True)
    catalog.save_mapping(record.id, record.sha256, "ark-file-1")
    path.write_bytes(b"v2")
    changed = catalog.refresh(record.id)
    assert changed.sha256 != record.sha256
    assert catalog.get_reusable_mapping(changed.id, changed.sha256) is None
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_document_catalog.py tests/test_config.py -q`

Expected: collection fails because the document catalog does not exist.

- [ ] **Step 3: Add document settings**

Add one catalog database path and one or more absolute allowed roots. Configuration must reject an empty root list and `maximum_candidates` outside 1–3. Do not commit real company paths; keep them in an ignored local config override or environment value documented in README.

- [ ] **Step 4: Implement encrypted catalog records**

Use the chat `DataCipher` for absolute paths, display names, labels, and Ark file IDs. Keep hashes, sizes, timestamps, status, format, authority rank, and audit event type queryable. A current document is one with `version_status='current'`, upload permission true, an allowed role, a file still under an approved root, and a matching on-disk hash.

```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    encrypted_path BLOB NOT NULL,
    encrypted_display_name BLOB NOT NULL,
    format TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    modified_ns INTEGER NOT NULL,
    version_status TEXT NOT NULL,
    authority_rank INTEGER NOT NULL,
    allow_upload INTEGER NOT NULL DEFAULT 0,
    encrypted_metadata BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

- [ ] **Step 5: Run GREEN and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_document_catalog.py tests/test_config.py -q`

```powershell
git add -- src/lexiaodu/config.py config/app.toml tests/test_config.py src/lexiaodu/document_catalog.py tests/test_document_catalog.py
git commit -m "feat: catalog approved original documents"
```

### Task 2: Administrator Catalog Command

**Files:**
- Create: `scripts/manage_document_catalog.py`
- Create: `tests/test_document_catalog_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing CLI safety tests**

Cover `register`, `refresh`, `retire`, and `report`. Require explicit `--allow-upload` for upload permission, reject paths outside allowed roots, refuse a second current version with the same business identity, and ensure report output contains document IDs/display labels but no absolute paths or Ark file IDs.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_document_catalog_cli.py -q`

- [ ] **Step 3: Implement the minimal command**

Registration requires format, business category, version label, authority rank, allowed advisor role, and an explicit current/draft state. This command is not linked from the ordinary chat UI. Document that Windows file ACLs and deployment ownership must restrict who can run it on managed machines.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_document_catalog_cli.py tests/test_document_catalog.py -q`

```powershell
git add -- scripts/manage_document_catalog.py tests/test_document_catalog_cli.py README.md
git commit -m "feat: add controlled document catalog administration"
```

### Task 3: Structured Advisor Planner and Natural Discussion Contract

**Files:**
- Create: `src/lexiaodu/advisor_model.py`
- Create: `tests/test_advisor_model.py`

**Interfaces:**
- Produces `PlannerAction` values `DISCUSS`, `ASK_ONE`, and `OFFER_REPLY`.
- Produces `AdvisorPlan(surface_question, real_concern, stage, objective, action, assistant_message, company_fact_needs, routing_target)`.
- Produces `AdvisorModel.plan(context_package, request_id)`, `summarize(messages, covered_range, context_version)`, and `generate_reply(request, file_handles, request_id)` protocols plus simulated and OpenAI-compatible implementations.

- [ ] **Step 1: Write failing schema and prompt-boundary tests**

Assert the planner returns one bounded action, asks no more than one question for `ASK_ONE`, and never returns hidden reasoning fields. Verify company fact needs are a list of types such as course/price/teacher/policy, not alleged facts. Verify the request labels consultant examples as non-factual style references and company documents as the only company-fact source.

```python
assert set(plan.to_dict()) == {
    "surface_question", "real_concern", "stage", "objective", "action",
    "assistant_message", "company_fact_needs", "routing_target"
}
assert "chain_of_thought" not in raw_request
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_advisor_model.py -q`

- [ ] **Step 3: Implement strict response parsing**

Use the same injected-client pattern as `OpenAICompatibleGenerator`. Request JSON, reject unknown/missing fields, cap each string/list, and map invalid responses to `AdvisorModelError`. Planner instructions must allow general educational judgment but forbid invented company facts, autonomous reply-card creation, and direct parent sending.

- [ ] **Step 4: Implement ordinary-turn and long-context behavior**

`DISCUSS` and `ASK_ONE` return a normal assistant chat message. `OFFER_REPLY` returns a normal message plus a UI capability flag; it does not call document routing or create a formal card. An explicit user phrase such as “帮我整理回复” is normalized by the controller into the same generate action as the button.

Implement the `ContextSummarizer` protocol from the chat/context plan with the same injected client. It receives only messages from one explicit conversation, returns a bounded factual summary with covered message IDs/version, and never invents company facts. Add tests proving a summary from conversation A cannot be saved or used for conversation B and that an invalidated context version is rejected.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_advisor_model.py tests/test_generator.py -q`

```powershell
git add -- src/lexiaodu/advisor_model.py tests/test_advisor_model.py
git commit -m "feat: add structured AI advisor planner"
```

### Task 4: Deterministic Metadata-Only Document Router

**Files:**
- Create: `src/lexiaodu/document_router.py`
- Create: `tests/test_document_router.py`

**Interfaces:**
- Produces `RoutingConfidence(HIGH, MEDIUM, LOW, NONE)`, `DocumentCandidate`, and `RoutingDecision`.
- Produces `DocumentRouter.route(conversation_id, routing_target, fact_needs, advisor_role)`.
- Accepts an optional `LegacyRoutingSignal` protocol that returns document IDs/scores only.

- [ ] **Step 1: Write failing ranking and branch tests**

Cover exact grade/subject/category matches, newer current versions, authority rank, denied roles, denied upload, stale hashes, candidate cap, legacy weak signal, ambiguous ties, and no result. Assert a strong match yields at most three `HIGH` candidates; close scores yield `MEDIUM`; missing key grade/subject yields one clarifying question or `NONE`, not arbitrary documents.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_document_router.py -q`

- [ ] **Step 3: Implement transparent scoring**

Use normalized metadata tokens only. Suggested deterministic score components: exact business category +40, subject +25, grade/stage +20, current version +10, authority rank up to +10, optional legacy document signal up to +10. Reject rather than penalize permission, role, non-current version, missing file, or hash mismatch. Return a localized list of matched metadata as the reason; never return document contents.

- [ ] **Step 4: Implement confidence thresholds and confirmation state**

Use fixtures to set initial thresholds: high when top score is at least 75 and exceeds the fourth/next viable candidate by 15; medium when top score is at least 55; otherwise low/none. Persist candidate IDs, hashes, scores, reasons, and advisor confirmation under the current conversation/generation request. Do not persist selections globally as parent preferences.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_document_router.py tests/test_document_catalog.py -q`

```powershell
git add -- src/lexiaodu/document_router.py tests/test_document_router.py
git commit -m "feat: route advisor questions to original files"
```

### Task 5: Verified Ark Original File Gateway

**Files:**
- Create: `src/lexiaodu/ark_gateway.py`
- Create: `tests/test_ark_gateway.py`
- Modify: `.env.example`

**Interfaces:**
- Produces `OriginalFileHandle(document_id, sha256, provider_file_id)`.
- Produces `ArkOriginalFileGateway.prepare(conversation_id, generation_id, document_ids, advisor_role)`.
- Wraps only the format-to-transport mappings named `GO` in `docs/ark-original-file-capability-report.md`.

- [ ] **Step 1: Write failing permission, byte-identity, reuse, and retry tests**

Use a fake verified transport. Assert the gateway rechecks allowed root, role, upload permission, current version, and SHA-256 immediately before upload. Assert matching hash reuses the existing mapping, changed hash invalidates it, one transient failure retries once, permanent/auth errors do not retry, and audit rows contain IDs/hashes/times/status but no message text or document contents.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_ark_gateway.py -q`

- [ ] **Step 3: Implement the gateway around the proven format mapping**

Select the transport by cataloged format using the exact `GO` mapping from the capability report. Open the original path in binary mode only inside that transport call. Do not import `pypdf`, `knowledge_import`, or `ocr`. Use a stable idempotency key from generation ID plus document hash. Cache only successful file mappings for the same hash and verified endpoint/model scope.

```python
idempotency_key = hashlib.sha256(
    f"{generation_id}:{record.sha256}".encode("ascii")
).hexdigest()
```

Retry exactly once for the transient categories approved in the capability report. Map unsupported format to a visible document-confirmation error; never fall back to local extracted text.

- [ ] **Step 4: Run import-boundary and focused tests**

Add an AST/import test that fails if `ark_gateway.py` imports local extraction/OCR modules. Run:

`.\.venv\python.exe -B -m pytest tests/test_ark_gateway.py tests/test_ark_probe.py -q`

- [ ] **Step 5: Commit**

```powershell
git add -- src/lexiaodu/ark_gateway.py tests/test_ark_gateway.py .env.example
git commit -m "feat: add verified Ark original file gateway"
```

### Task 6: Structured Reply Segments and Local Evidence Validator

**Files:**
- Create: `src/lexiaodu/advisor_service.py`
- Create: `tests/test_advisor_service.py`
- Modify: `src/lexiaodu/advisor_model.py`
- Modify: `tests/test_advisor_model.py`

**Interfaces:**
- Produces `CompanyClaim(claim_id, text, document_id, document_hash, locator, evidence_excerpt)`.
- Produces internal `ReplySegment(kind, text, claim_id=None)` and public `AdvisorReply(concern_summary, strategy_summary, wechat_reply, company_claims, general_judgments, needs_confirmation, follow_up_question, risk)`.
- Produces `AdvisorService.discuss` and `AdvisorService.generate_reply`.

- [ ] **Step 1: Write failing evidence-removal tests**

Return a fake response with one grounded company segment, one claim referencing an unselected document, one blank locator, one general judgment, and one live-system claim. Assert only the grounded company segment and general segment appear in `wechat_reply`; removed claims appear in `needs_confirmation`; live-system content is blocked; the final risk result reflects available valid evidence.

```python
reply = service.generate_reply(request)
assert "每期 18 次" in reply.wechat_reply
assert "当前还有 2 个名额" not in reply.wechat_reply
assert any("业务系统" in item for item in reply.needs_confirmation)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_advisor_service.py -q`

- [ ] **Step 3: Extend the model contract with linked segments**

Require structured `reply_segments` in the provider response even though the UI exposes the flattened `wechat_reply`. A `company` segment must name one `claim_id`; a `general` segment must not. This link is required so local code can remove unsupported wording deterministically.

- [ ] **Step 4: Implement orchestration and validation**

For discussion, build current context and save the bounded `AdvisorPlan` plus assistant message. For formal generation, require explicit confirmation, a persisted routing decision, confirmed document IDs, prepared file handles, and a structured provider response. Validate selected/current document ID and hash, non-empty locator/evidence, claim-to-segment link, current-version precedence, and live-system restrictions before flattening segments. Then reuse `DeterministicRiskRules` with valid company evidence status.

- [ ] **Step 5: Test conflicts and regeneration**

Add cases for conflicting current documents, authority/version ordering, unresolved conflict, changing selected documents, invalid JSON, and a second generated version. Assert a new generation never reuses claims from the old document set and never overwrites the old record.

- [ ] **Step 6: Run focused tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_advisor_service.py tests/test_advisor_model.py tests/test_risk.py -q`

```powershell
git add -- src/lexiaodu/advisor_service.py tests/test_advisor_service.py src/lexiaodu/advisor_model.py tests/test_advisor_model.py
git commit -m "feat: validate grounded advisor reply segments"
```

### Task 7: Chat UI Integration and Human Review

**Files:**
- Modify: `src/lexiaodu/chat_window.py`
- Modify: `src/lexiaodu/chat_controller.py`
- Modify: `tests/test_chat_window.py`
- Modify: `tests/test_chat_controller.py`

- [ ] **Step 1: Write failing multi-turn UI tests**

Cover: ordinary discussion appears as a normal turn; one focused question can be answered in the same thread; `OFFER_REPLY` shows a generate action but no card; high-confidence routing shows brief tool events and continues; medium confidence shows document candidates with confirm/remove/add; generation starts only after confirmation; source drawer shows display name/version/locator; changing documents creates a new reply version; high risk keeps copy gated.

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_chat_window.py tests/test_chat_controller.py -q`

- [ ] **Step 3: Add document confirmation and source drawer view models**

Pass document IDs through item data, not labels. Show only authorized display names, version, metadata match reason, and confidence. Do not show absolute paths, provider IDs, prompts, or raw provider payloads.

- [ ] **Step 4: Add explicit formal generation flow**

The controller persists `generation_requested`, routing decision, confirmation, gateway status, validated result, and risk in order. Each asynchronous callback carries conversation ID plus generation ID. If the advisor switches threads, persist completion but do not render it into the wrong timeline.

- [ ] **Step 5: Preserve edit/copy/feedback behavior**

Render validated flattened text in an editable card, references and confirmations in the drawer, and keep deterministic copy confirmation for high risk. Save each edited final version without changing the immutable initial validated draft.

- [ ] **Step 6: Run UI regression and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_chat_window.py tests/test_chat_controller.py tests/test_chat.py tests/test_workflow.py -q`

```powershell
git add -- src/lexiaodu/chat_window.py src/lexiaodu/chat_controller.py tests/test_chat_window.py tests/test_chat_controller.py
git commit -m "feat: integrate document-grounded advisor chat"
```

### Task 8: Mode Wiring, End-to-End Isolation, and Staged Gate

**Files:**
- Modify: `src/lexiaodu/app.py`
- Modify: `tests/test_app.py`
- Create: `tests/test_original_document_advisor_acceptance.py`
- Modify: `README.md`
- Modify: `docs/MANUAL_TEST_CHECKLIST.md`

- [ ] **Step 1: Write failing application wiring tests**

Assert `simulated` starts without Ark settings. Assert `original_documents` requires HTTPS base URL, API key, model/endpoint, an approved catalog, and a `GO` capability decision for every enabled format. Invalid or `NO_GO` configuration fails before any window uploads a file.

- [ ] **Step 2: Add an end-to-end fake-gateway acceptance test**

Create two similar conversations with different confirmed facts and document selections. Complete discuss → offer → confirm → upload/reuse → validate → edit → copy. Assert context, selected documents, claims, citations, reply versions, and audit events remain isolated by conversation/generation ID. Change a source hash and assert the next generation uploads anew and cannot cite the old hash.

- [ ] **Step 3: Run acceptance tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_app.py tests/test_original_document_advisor_acceptance.py -q`

- [ ] **Step 4: Wire production mode without changing the default**

Build the planner, catalog, router, verified gateway, advisor service, and controller dependencies only when `LEXIAODU_ADVISOR_MODE=original_documents`. Keep `simulated` default until manual and offline evaluation gates pass. Do not instantiate the legacy local RAG `AdviceService` in the new original-document runtime.

- [ ] **Step 5: Run the full automated suite**

Run: `.\.venv\python.exe -B -m pytest -q`

Run: `.\.venv\python.exe -m pip check`

Expected: full suite passes with no real network calls.

- [ ] **Step 6: Run controlled live acceptance**

On the named test Windows account, use only approved sample documents and fictitious conversations. Verify natural multi-turn discussion, one-question behavior, document confirmation, exact citations, invalid-claim removal, version change, upload reuse, one retry, source drawer, risk gate, restart recovery, and legacy rollback. Record latency and any provider-side file retention.

- [ ] **Step 7: Commit code and recorded manual result**

```powershell
git status --short
git add -- src/lexiaodu/app.py tests/test_app.py tests/test_original_document_advisor_acceptance.py README.md docs/MANUAL_TEST_CHECKLIST.md
git commit -m "feat: gate the original document advisor runtime"
```

- [ ] **Step 8: Hold the default switch for the evaluation plan**

Do not change `LEXIAODU_ADVISOR_MODE` default to production in this plan. The learning/evaluation rollout plan owns the A/B baseline, safety gate, pilot approval, and final default switch.
