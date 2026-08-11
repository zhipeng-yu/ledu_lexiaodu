# Cloud-only Company Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover, select, and use Ark knowledge-base PDF, DOCX, PPTX, and XLSX documents without local source copies.

**Architecture:** Replace local path discovery and PDF Files API uploads with a single read-only knowledge-base adapter. Route by cloud `doc_id`, retrieve all selected evidence in one `search_knowledge` request, and pass the rendered evidence to Doubao's existing final-response call.

**Tech Stack:** Python 3.11, OpenAI-compatible Ark client, Volcengine Viking Knowledge Base SDK, pytest.

## Global Constraints

- PDF, DOCX, PPTX, and XLSX use the same cloud-only runtime path.
- No manual upload UI, local OCR, body extraction, text chunking, or knowledge-base rebuilding.
- No upload, update, or deletion of local data or cloud documents.
- At most three source documents are selected.

---

### Task 1: Cloud document catalog and retrieval

**Files:**
- Modify: `src/lexiaodu/office_documents.py`
- Test: `tests/test_office_documents.py`

**Interfaces:**
- Produces: `KnowledgeDocument(doc_id: str, name: str)`.
- Produces: `ArkKnowledgeDocumentReader.list_documents() -> tuple[KnowledgeDocument, ...]`.
- Produces: `ArkKnowledgeDocumentReader.retrieve(query: str, documents: tuple[KnowledgeDocument, ...]) -> str`.

- [ ] **Step 1: Write failing cloud-catalog tests**

Add tests whose fake collection returns ready PDF/DOCX/PPTX/XLSX documents plus unsupported and unfinished entries. Assert that `list_documents()` returns only the four ready supported documents without any local files.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.\.venv\python.exe -m pytest tests\test_office_documents.py -q`

Expected: failure because `KnowledgeDocument`, `ArkKnowledgeDocumentReader`, and `list_documents` do not exist.

- [ ] **Step 3: Implement the minimal catalog**

Add the immutable cloud document value and list the collection with `project=self._project`. Normalize `status["process_status"]` when status is structured, accept only status `0`, validate names/IDs, filter the four supported suffixes, and sort by case-folded name and ID.

- [ ] **Step 4: Write and run the retrieval tests**

Assert that PDF and Office `KnowledgeDocument` values are searched together with this filter shape:

```python
{
    "doc_filter": {
        "op": "must",
        "field": "doc_id",
        "conds": ["pdf-id", "docx-id", "pptx-id", "xlsx-id"],
    }
}
```

Expected before implementation: failure because `retrieve` still accepts and checks local `Path` values.

- [ ] **Step 5: Implement minimal unified retrieval and verify GREEN**

Remove local file checks and retrieve the selected cloud document IDs in one request. Render source names and chunks, retain a specific empty-result error, then run:

`.\.venv\python.exe -m pytest tests\test_office_documents.py -q`

Expected: all tests in the file pass.

### Task 2: Cloud-only assistant routing

**Files:**
- Modify: `src/lexiaodu/advisor_assistant.py`
- Modify: `src/lexiaodu/app.py`
- Test: `tests/test_advisor_assistant.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `KnowledgeDocument` and `ArkKnowledgeDocumentReader` from Task 1.
- Produces: assistant routing JSON `{"document_ids": ["cloud-doc-id"]}`.

- [ ] **Step 1: Write failing assistant tests**

Provide a fake reader that lists a cloud PDF and DOCX, routes by their IDs, and returns knowledge evidence. Assert that the final response contains only `input_text`, both cloud names appear in routing/evidence, and the client has no Files API dependency.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.\.venv\python.exe -m pytest tests\test_advisor_assistant.py tests\test_app.py -q`

Expected: failures because the assistant still scans local paths and uploads selected PDFs.

- [ ] **Step 3: Implement minimal cloud routing**

Replace path discovery with `reader.list_documents()`, select by cloud ID, retrieve all selected formats through the same reader, remove the PDF upload/wait/delete code, and rename environment builder internals from Office-only to knowledge-document terminology.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.\.venv\python.exe -m pytest tests\test_advisor_assistant.py tests\test_app.py -q`

Expected: all focused tests pass.

### Task 3: Documentation and final verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `HANDOFF.md`

**Interfaces:**
- Consumes: verified cloud-only behavior from Tasks 1 and 2.
- Produces: operator instructions that require all four formats to be imported and parsed in Ark.

- [ ] **Step 1: Update operator documentation**

Describe the unified cloud workflow, remove local filename matching and PDF temporary-upload statements, and explain that the app is read-only while administrators maintain documents through the Ark console.

- [ ] **Step 2: Run full verification**

Run:

```powershell
.\.venv\python.exe -m pytest -q
git diff --check
```

Expected: all tests pass and `git diff --check` exits successfully.

- [ ] **Step 3: Perform a read-only live check when configured**

List supported ready cloud document counts by suffix and issue one combined, non-mutating retrieval through the application adapter without printing secrets or document contents. If PDF is not yet imported, record the required console action instead of mutating the knowledge base.

- [ ] **Step 4: Review and publish**

Inspect `git diff` and `git status`, stage only task files, commit on `main`, push `origin main`, and verify `HEAD` equals `origin/main`.
