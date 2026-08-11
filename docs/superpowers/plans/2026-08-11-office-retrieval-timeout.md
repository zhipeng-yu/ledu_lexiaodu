# Office Retrieval Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Office-only real conversations by allowing final Responses generation up to 120 seconds while preserving the current PDF request behavior.

**Architecture:** Retain the single combined Ark knowledge search already present on `main`. Make the final answer request aware of selected document suffixes and add a per-request timeout only for an Office-only selection.

**Tech Stack:** Python 3.11, OpenAI Python SDK 2.x, pytest.

## Global Constraints

- Do not upload, delete, overwrite, or rewrite local or cloud company documents.
- Do not change the current PDF flow.
- Do not add local OCR, extraction, segmentation, knowledge rebuilding, manual upload controls, or deleted legacy features.
- Use only the two verified documents for the real conversation check.

---

### Task 1: Protect Office-only timeout behavior

**Files:**
- Modify: `tests/test_advisor_assistant.py`
- Modify: `src/lexiaodu/advisor_assistant.py`

**Interfaces:**
- Consumes: `tuple[KnowledgeDocument, ...]` selected by `_select_documents`.
- Produces: `_respond_with_knowledge_documents(context, documents, *, knowledge_evidence)`; Office-only calls pass `timeout=120.0`, calls containing PDF omit `timeout`.

- [x] **Step 1: Write the failing Office-only timeout test**

Add a test using real `OpenAIConversationAssistant` behavior with `FakeKnowledgeReader`, `RoutingCompletions`, and `FakeResponses`. Select DOCX and XLSX documents and assert the captured Responses request has literal `timeout == 120.0`. In the existing mixed PDF/Office test, assert `"timeout" not in responses.options`.

- [x] **Step 2: Run the focused test to verify RED**

Run: `.\.venv\python.exe -m pytest tests/test_advisor_assistant.py -q`

Expected: the Office-only assertion fails because the current request has no `timeout` option.

- [x] **Step 3: Implement the minimal timeout branch**

Pass `selected` into `_respond_with_knowledge_documents`. Build the existing Responses options once, add `timeout=120.0` only when every selected suffix belongs to `{'.docx', '.pptx', '.xlsx'}`, and call `responses.create` once.

- [x] **Step 4: Verify GREEN**

Run: `.\.venv\python.exe -m pytest tests/test_advisor_assistant.py -q`

Expected: all assistant tests pass.

### Task 2: Verify and document the fix

**Files:**
- Modify: `README.md`
- Modify: `HANDOFF.md`

**Interfaces:**
- Consumes: the two target names and IDs already recorded in project history.
- Produces: current operational documentation with the resolved cause and validation evidence.

- [x] **Step 1: Run the full automated suite**

Run: `.\.venv\python.exe -m pytest -q`

Expected: all tests pass.

- [x] **Step 2: Run one real Lexiaodu conversation**

Use a temporary encrypted repository and the real `ChatController`, `ContextBuilder`, assistant, Ark reader, and Responses API. Ask one question that explicitly names both verified Office documents. Verify both targets have status 0, one combined knowledge search returns non-empty points, the request completes, and the saved answer names both sources. Do not print document evidence or answer text.

- [x] **Step 3: Update operational documentation**

Record the QPS root cause, combined-query fix, final-generation timeout evidence, Office-only timeout behavior, and real validation result. Keep PDF behavior described as the current baseline and remove no unrelated history.

- [ ] **Step 4: Final verification and publish**

Run `.\.venv\python.exe -m pytest -q`, `git diff --check`, inspect `git status` and the scoped diff, commit only the task files on `main`, run `git push`, and verify `HEAD` equals `origin/main`.
