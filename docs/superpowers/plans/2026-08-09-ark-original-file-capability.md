# Ark Original File Capability Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an evidence-backed, format-by-format go/no-go decision for sending unchanged PDF, DOCX, PPTX, and XLSX source files through the enabled Volcano Ark account and model endpoint before any production advisor path depends on it.

**Architecture:** Build an offline-tested probe harness around a narrow transport protocol, then bind that protocol to the exact Ark file or document-knowledge endpoint confirmed by the current official documentation and test account. The live probe hashes every local input before and after use, asks locator-specific questions against a controlled corpus, records machine-readable results without document contents, and generates a redacted compatibility report. This plan ends at the capability gate and does not modify the production answer flow.

**Tech Stack:** Python 3.11, existing OpenAI Python SDK 2.x or the official Ark SDK/HTTP route confirmed during the task, pytest 8.x, SHA-256, JSON/Markdown reports

## Global Constraints

- Start only after the company supplies or approves non-production PDF, DOCX, PPTX, and XLSX samples and a test Ark account/model with file capability.
- Never use real parent chats, student records, employee directories, production prices, or secrets in the probe corpus.
- Do not extract, OCR, convert, rewrite, unzip, or chunk source documents locally. The probe may read bytes only to hash and upload them.
- Do not infer API payloads from memory. Before implementing the live transport, record the current official URL, endpoint, SDK method, supported formats, size limits, retention/deletion behavior, and account permission in the report.
- Keep `ARK_API_KEY` only in ignored local environment configuration. Never print it or serialize request headers.
- Store private samples and raw service responses only under ignored `artifacts/ark-original-file-probe/`; commit only schemas, scripts, tests, and redacted aggregate results approved for source control.
- Treat PDF, DOCX, PPTX, and XLSX independently. One supported format does not authorize another.
- Do not silently convert legacy `.doc` or `.ppt`; leave them unsupported unless the verified Ark endpoint explicitly accepts them unchanged.
- A file-format result is `GO` only when upload/read, locator quality, reuse, timeout, deletion/retention, and privacy checks all pass.
- Use the project-local `.venv` for every Python command.

---

## File Structure

- Create `src/lexiaodu/ark_probe.py` for probe records, hashing, result validation, and report aggregation.
- Create `scripts/verify_ark_original_files.py` for the live command entry point.
- Create `tests/test_ark_probe.py` for offline transport and report tests.
- Create `docs/ark-original-file-capability-report.md` as the redacted decision record.
- Modify `.env.example` only if the verified endpoint needs additional non-secret identifiers.
- Modify `README.md` to document the probe command and its non-production data boundary.

### Task 1: Controlled Corpus Manifest and Offline Probe Contract

**Files:**
- Create: `src/lexiaodu/ark_probe.py`
- Create: `tests/test_ark_probe.py`
- Create: `docs/ark-original-file-capability-report.md`

**Interfaces:**
- Produces `ProbeCase`, `ProbeAnswer`, `ProbeResult`, `FormatDecision`, and `ProbeReport` immutable records.
- Produces an `OriginalFileProbeTransport` protocol with `upload(path, sha256)`, `ask(file_id, question)`, and `delete(file_id)`.
- Produces `run_probe(cases, transport, clock, timeout_seconds)` without importing knowledge extraction or OCR modules.

- [ ] **Step 1: Define the private manifest format**

The ignored file `artifacts/ark-original-file-probe/manifest.json` must use this schema. Each format needs at least one text locator, one table locator, one embedded-image locator, and—where the format can contain it—one scanned-image locator.

```json
{
  "schema_version": 1,
  "cases": [
    {
      "case_id": "pdf-text-01",
      "relative_path": "inputs/sample-text.pdf",
      "format": "pdf",
      "question": "虚构项目 A 的课次数是多少？",
      "expected_answer": "18",
      "expected_locator": "第 3 页",
      "content_kind": "text"
    }
  ]
}
```

The sample itself must contain obvious fictitious markers and an approval note outside the document. Do not commit the manifest or inputs.

- [ ] **Step 2: Write failing offline tests**

Use a fake transport to assert: the local SHA-256 is passed to upload; the same unchanged file hash is observed after the run; answers missing the expected locator fail; file deletion runs in `finally`; raw answers are absent from the committed report model; and a transport timeout marks only that case failed.

```python
def test_probe_rejects_answer_without_locator(tmp_path):
    case = make_case(tmp_path, expected_answer="18", expected_locator="第 3 页")
    transport = FakeTransport(answer="课次数是 18", locator="")
    result = run_probe((case,), transport, fixed_clock, timeout_seconds=30)
    assert result.cases[0].answer_correct
    assert not result.cases[0].locator_correct
    assert result.formats["pdf"].decision == "NO_GO"
```

- [ ] **Step 3: Run tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_ark_probe.py -q`

Expected: collection fails because `lexiaodu.ark_probe` does not exist.

- [ ] **Step 4: Implement the probe core**

Validate extensions against the manifest, stream SHA-256 without reading document text, call upload/ask/delete through the protocol, and compare normalized expected answers and locators. Record file ID only as a one-way hash in report output. Store case ID, format, content kind, timings, booleans, error category, pre/post hash equality, and cleanup status; omit questions, answers, document names, paths, file IDs, and document contents from committed aggregates.

- [ ] **Step 5: Seed the report decision table**

Create the report with `NOT_RUN` rows for PDF, DOCX, PPTX, and XLSX plus sections for official API evidence, account permissions, retention/deletion, sample approval, per-format metrics, observed limitations, and signed decision. `NOT_RUN` must be visibly different from `NO_GO` and `GO`.

- [ ] **Step 6: Run GREEN and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_ark_probe.py -q`

```powershell
git add -- src/lexiaodu/ark_probe.py tests/test_ark_probe.py docs/ark-original-file-capability-report.md
git commit -m "test: add Ark original file capability harness"
```

### Task 2: Confirm the Current Official Transport Before Coding It

**Files:**
- Modify: `docs/ark-original-file-capability-report.md`

- [ ] **Step 1: Record primary-source API facts**

Open the current official Volcano Ark File API and document-knowledge workflow pages linked from the approved design. Record the page titles, canonical URLs, access date, last-updated dates, supported unchanged formats, maximum size/page limits, upload purpose, inference endpoint, file reuse semantics, retention, deletion API, and whether locators are returned natively or must be requested in structured model output.

- [ ] **Step 2: Verify the enabled account and model**

In the non-production Ark account, confirm the exact region, base URL, endpoint/model ID, file or knowledge-base permission, and whether uploaded files can be deleted. Record identifiers only when they are non-secret; never record credentials.

- [ ] **Step 3: Choose exactly one transport per target format**

For each of PDF, DOCX, PPTX, and XLSX, choose the direct File API only if the current endpoint accepts that format unchanged and can attach it to inference. Otherwise choose the official document-knowledge upload/query path for that format. Record the chosen and rejected paths and reasons. If neither path satisfies unchanged upload, locators, and deletion/retention requirements, set that format to `NO_GO` and stop its production integration. Prefer one shared transport where capability is equal, but do not reject a supported format merely because another verified Ark transport is required.

- [ ] **Step 4: Review the evidence checkpoint**

Have the technical owner and data/privacy owner confirm the report facts. This checkpoint is not satisfied by a successful HTTP status alone.

```powershell
git add -- docs/ark-original-file-capability-report.md
git commit -m "docs: record verified Ark file transport"
```

### Task 3: Live Transport Adapter and Secret-Safe CLI

**Files:**
- Create: `scripts/verify_ark_original_files.py`
- Modify: `src/lexiaodu/ark_probe.py`
- Modify: `tests/test_ark_probe.py`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Write failing adapter-boundary tests**

Patch the verified SDK client or HTTP session. Assert the adapter opens the exact original path in binary mode, passes no locally derived text, uses the documented purpose/input block, applies a bounded request timeout, sends a request ID, retries one transient `429/5xx` once, does not retry validation/authentication errors, and invokes the documented delete operation.

- [ ] **Step 2: Run the adapter tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_ark_probe.py -q`

Expected: the new adapter tests fail because the verified live adapter is not implemented.

- [ ] **Step 3: Implement only transports recorded in Task 2**

Name each class for its chosen mechanism, for example `ArkFileApiProbeTransport` or `ArkDocumentKnowledgeProbeTransport`; implement both only when Task 2 assigns at least one `GO` candidate format to each. Select the adapter from the manifest format. Keep SDK-specific request construction inside those classes. Validate response structure and return only file ID, answer, locator, and timings to the probe core. Map errors to stable categories: `auth`, `permission`, `unsupported_format`, `size_limit`, `timeout`, `rate_limit`, `service`, `invalid_response`, and `cleanup`.

- [ ] **Step 4: Implement CLI preflight and redacted output**

The command requires `--sample-root`, `--manifest`, and `--report-json`. It must refuse paths outside `--sample-root`, reject symlinks escaping the root, reject unlisted extensions, require HTTPS, and show a final aggregate without answers or paths.

```powershell
.\.venv\python.exe -B scripts\verify_ark_original_files.py `
  --sample-root artifacts\ark-original-file-probe\inputs `
  --manifest artifacts\ark-original-file-probe\manifest.json `
  --report-json artifacts\ark-original-file-probe\result.json
```

- [ ] **Step 5: Run offline tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_ark_probe.py tests/test_app.py -q`

```powershell
git add -- scripts/verify_ark_original_files.py src/lexiaodu/ark_probe.py tests/test_ark_probe.py .env.example README.md
git commit -m "feat: add secret-safe Ark file probe"
```

### Task 4: Execute the Live Compatibility Matrix

**Files:**
- Private inputs/results: `artifacts/ark-original-file-probe/` (ignored)
- Modify approved aggregates only: `docs/ark-original-file-capability-report.md`

- [ ] **Step 1: Validate the approved corpus before upload**

Have the data owner verify that every sample is fictitious or explicitly cleared for the test account. Record approval role/date in the report. Confirm the command's preflight lists only the expected case IDs and formats, not contents.

- [ ] **Step 2: Run each case twice**

The first run measures upload plus first query. The second run must reuse the returned service-side file mapping where the verified endpoint allows it. Measure upload time, first-answer time, reuse-answer time, answer correctness, locator correctness, post-run hash equality, and cleanup success.

- [ ] **Step 3: Exercise failure paths**

Include one unsupported extension, one oversize/declared-limit preflight case without uploading private content, one simulated timeout, one invalid file ID, and one transient retry. Confirm errors are actionable and no fallback local extraction occurs.

- [ ] **Step 4: Inspect provider-side state**

After deletion, verify through the documented API or console that files/knowledge entries are deleted or retained according to the recorded policy. If deletion cannot be independently observed, mark cleanup/retention as unresolved rather than passed.

- [ ] **Step 5: Update only redacted aggregates**

Copy aggregate metrics and error categories into the report. Do not commit `result.json`, sample names, questions, answers, locators containing business content, provider file IDs, or screenshots.

### Task 5: Format-by-Format Go/No-Go Gate

**Files:**
- Modify: `docs/ark-original-file-capability-report.md`

- [ ] **Step 1: Apply the hard decision rules**

For each format, require all of the following for `GO`:

- unchanged pre/post SHA-256 for every case;
- upload and query succeed for text, table, and image-bearing cases;
- required answer accuracy is 100% on the small controlled corpus;
- exact page/slide/section locator accuracy is at least 95%;
- service-side reuse works or a documented non-reuse lifecycle is acceptable;
- bounded timeout and one-retry behavior are verified;
- retention and deletion behavior is documented and approved;
- no secret or document content appears in committed/logged artifacts.

Any missing privacy approval, unsupported unchanged upload, unverifiable locator, or unresolved cleanup produces `NO_GO`, not a warning-only `GO`.

- [ ] **Step 2: State the production consequences**

List the allowed extensions, selected transport, model/endpoint constraints, maximum limits, expected locator type, and unsupported-format user message. Explicitly state that production integration may begin only for formats marked `GO`.

- [ ] **Step 3: Obtain owner sign-off and commit the redacted report**

The technical owner signs behavior; the business document owner signs sample representativeness; the privacy/data owner signs upload and retention. If approvals cannot be committed, record approved roles and internal decision reference without personal data.

```powershell
git status --short
git add -- docs/ark-original-file-capability-report.md
git commit -m "docs: decide Ark original file compatibility"
```

- [ ] **Step 4: Stop on NO_GO**

Do not begin the production gateway tasks for a `NO_GO` format. Return to product design for a supported cloud-side ingestion route or an explicit business decision; never add a hidden local conversion or OCR fallback.
