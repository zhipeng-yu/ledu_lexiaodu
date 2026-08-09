# Independent Chat and Local Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the floating-toolbar-first experience with a restart-safe, thread-isolated chat workspace that supports encrypted local history, screenshot/OCR attachments, compacted same-thread context, and retryable simulated assistant turns.

**Architecture:** Add an encrypted SQLite conversation repository and encrypted attachment store below a new `ChatMainWindow`. Reuse the current selection, capture, OCR, correction, reply-card, risk, and font-scaling behaviors through smaller controllers. A `ContextBuilder` always scopes reads by conversation ID and assembles confirmed facts, a regenerable summary, recent turns, and relevant older turns. Startup defaults to the new shell while retaining the legacy toolbar behind an explicit rollback environment value.

**Tech Stack:** Python 3.11, PySide6 6.x, SQLite, Windows DPAPI, AES-256-GCM via `cryptography`, pytest 8.x, Qt offscreen tests

## Global Constraints

- Complete this plan before starting the production original-document advisor plan.
- Keep the current knowledge databases, knowledge import pipeline, `AdviceService`, and legacy floating toolbar intact.
- Default startup to the independent chat window only after its focused and integration tests pass; `LEXIAODU_UI_MODE=legacy` remains the rollback path.
- Persist every user message before starting assistant work. Never retry automatically after application restart.
- Require `conversation_id` on every message, summary, fact, attachment, document-usage, and generation read/write API.
- Store message text, titles, summaries, facts, OCR corrections, reply drafts, and model metadata as encrypted blobs; do not create a plaintext FTS index.
- Encrypt each attachment with a random data key; protect the local master key for the current Windows user with DPAPI.
- Never upload screenshot bytes in this plan. Only corrected OCR text may later enter a model context package.
- Make a deleted conversation invisible and hard-delete its messages, facts, summaries, generations, attachment metadata, and corrected OCR text in one database transaction; clean encrypted attachment files through an idempotent cleanup queue.
- Use the project-local `.venv` for every Python command. Do not install into the system interpreter.

---

## File Structure

- Modify `pyproject.toml` to add the single encryption dependency.
- Modify `src/lexiaodu/config.py` and `config/app.toml` for local chat paths and context limits.
- Create `src/lexiaodu/local_crypto.py` for DPAPI-backed envelope encryption.
- Create `src/lexiaodu/conversations.py` for models, schema, encryption, persistence, search, retry state, and deletion.
- Create `src/lexiaodu/attachments.py` for encrypted image files and cleanup.
- Create `src/lexiaodu/context.py` for strictly same-thread context assembly and summary invalidation.
- Create `src/lexiaodu/chat_window.py` for the independent sidebar/chat/composer/drawer shell.
- Create `src/lexiaodu/chat_controller.py` for UI persistence, background assistant work, retries, and screenshot/OCR attachment flow.
- Modify `src/lexiaodu/app.py` to build the new shell by default and preserve the legacy entry behind a feature flag.
- Modify `src/lexiaodu/chat.py` only to extract/reuse the formal `_SuggestionCard`; do not restyle unrelated legacy widgets.
- Add focused tests in `tests/test_local_crypto.py`, `tests/test_conversations.py`, `tests/test_attachments.py`, `tests/test_context.py`, `tests/test_chat_window.py`, and `tests/test_chat_controller.py`.
- Modify `tests/test_app.py`, `README.md`, and `docs/MANUAL_TEST_CHECKLIST.md` for startup and recovery behavior.

### Task 1: Local Encryption and Chat Settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/lexiaodu/config.py`
- Modify: `config/app.toml`
- Create: `src/lexiaodu/local_crypto.py`
- Create: `tests/test_local_crypto.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces `ChatSettings(database_path, attachment_dir, recent_message_limit, related_message_limit, context_character_budget)`.
- Produces `DataCipher.open(key_path, key_protector=None)` and authenticated `encrypt(bytes) -> bytes` / `decrypt(bytes) -> bytes`.
- Produces `WindowsDpapiKeyProtector.protect(bytes) -> bytes` and `unprotect(bytes) -> bytes`.

- [ ] **Step 1: Write failing encryption and configuration tests**

Use an injected in-memory key protector in unit tests so encryption behavior is deterministic and does not depend on the test runner's Windows profile. Verify that plaintext sentinels do not occur in the key file or ciphertext, tampering raises `DecryptionError`, reopening with the same protected key decrypts existing data, and the default chat paths are under `data/`.

```python
class RecordingTestProtector:
    def __init__(self) -> None:
        self.last_plaintext: bytes | None = None

    def protect(self, value: bytes) -> bytes:
        self.last_plaintext = value
        return b"test-envelope:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        assert value.startswith(b"test-envelope:")
        return value.removeprefix(b"test-envelope:")[::-1]


def test_cipher_reopens_without_writing_plaintext_key(tmp_path):
    key_path = tmp_path / "chat.key"
    protector = RecordingTestProtector()
    first = DataCipher.open(key_path, protector)
    encrypted = first.encrypt("虚构家长-13900000000".encode())
    second = DataCipher.open(key_path, protector)
    assert second.decrypt(encrypted).decode() == "虚构家长-13900000000"
    assert b"13900000000" not in encrypted
    assert protector.last_plaintext is not None
    assert protector.last_plaintext not in key_path.read_bytes()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_local_crypto.py tests/test_config.py -q`

Expected: collection fails because `lexiaodu.local_crypto` and `ChatSettings` do not exist.

- [ ] **Step 3: Add and install the dependency in the project environment**

Add `"cryptography>=45,<47"` to project dependencies, then refresh only the project-local editable environment:

`.\.venv\python.exe -m pip install -e ".[dev]"`

Use AES-GCM with a fresh 12-byte nonce per value and prefix a one-byte storage version. `DataCipher.open` creates the parent directory, generates one 32-byte master key if absent, protects it before an atomic key-file replace, and never exposes it through logging or exceptions.

```python
_FORMAT_VERSION = b"\x01"

def encrypt(self, value: bytes) -> bytes:
    nonce = os.urandom(12)
    return _FORMAT_VERSION + nonce + self._aes.encrypt(
        nonce, value, _FORMAT_VERSION
    )

def decrypt(self, value: bytes) -> bytes:
    if len(value) < 14 or value[:1] != _FORMAT_VERSION:
        raise DecryptionError("不支持或已损坏的本地加密数据")
    try:
        return self._aes.decrypt(value[1:13], value[13:], _FORMAT_VERSION)
    except InvalidTag as exc:
        raise DecryptionError("本地加密数据校验失败") from exc
```

Implement DPAPI with `CryptProtectData`/`CryptUnprotectData`, `CRYPTPROTECT_UI_FORBIDDEN`, current-user scope, and `LocalFree` cleanup. Reject non-Windows startup with a clear `LocalEncryptionUnavailable` error instead of silently writing plaintext.

- [ ] **Step 4: Load and validate chat settings**

Add this configuration without changing existing keys:

```toml
[chat]
database_path = "data/chat.sqlite3"
attachment_dir = "data/chat-attachments"
recent_message_limit = 12
related_message_limit = 4
context_character_budget = 18000
```

Validate non-empty paths and positive integer limits. Add assertions to `test_load_project_settings` and one invalid-zero test for `context_character_budget`.

- [ ] **Step 5: Run GREEN, dependency integrity, and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_local_crypto.py tests/test_config.py -q`

Run: `.\.venv\python.exe -m pip check`

Expected: all focused tests pass and pip reports no broken requirements.

```powershell
git add -- pyproject.toml src/lexiaodu/config.py config/app.toml src/lexiaodu/local_crypto.py tests/test_local_crypto.py tests/test_config.py
git commit -m "feat: add encrypted local chat storage settings"
```

### Task 2: Thread-Isolated Conversation Repository

**Files:**
- Create: `src/lexiaodu/conversations.py`
- Create: `tests/test_conversations.py`

**Interfaces:**
- Produces immutable `Conversation`, `Message`, `ConfirmedFact`, `ContextSummary`, and `PendingRequest` records.
- Produces `ConversationRepository(database_path, cipher, clock: Callable[[], datetime] = utc_now)`.
- Every child-record method accepts `conversation_id` as its first business argument.

- [ ] **Step 1: Write repository lifecycle and isolation tests**

Cover create/list/rename/search, append-before-processing, request failure/retry, restart recovery, summary/fact persistence, and deletion. Use two conversations with identical keywords and assert every API returns only its requested thread. Inspect raw SQLite bytes for unique sentinels and assert none are plaintext.

```python
def test_messages_and_context_never_cross_conversations(repository):
    first = repository.create_conversation("一年级英语")
    second = repository.create_conversation("一年级英语")
    first_message = repository.append_user_message(
        first.id, "家长担心跟不上", request_id="req-1"
    )
    repository.append_user_message(
        second.id, "家长担心跟不上", request_id="req-2"
    )
    assert repository.list_messages(first.id) == (first_message,)
    assert all(
        message.conversation_id == first.id
        for message in repository.list_messages(first.id)
    )
```

Assert `request_id` is unique and an assistant result has a unique `in_reply_to_request_id`, so retrying the same request cannot append a duplicate assistant turn.

- [ ] **Step 2: Run repository tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_conversations.py -q`

Expected: collection fails because `lexiaodu.conversations` does not exist.

- [ ] **Step 3: Implement the schema and encrypted mapping**

Use foreign keys, WAL mode, and `PRAGMA secure_delete=ON`. Store searchable timestamps/status/type fields in plaintext, but encrypt all business content and model metadata. Use one transaction for each public mutation.

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    encrypted_title BLOB NOT NULL,
    status TEXT NOT NULL,
    context_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    encrypted_body BLOB NOT NULL,
    request_id TEXT UNIQUE,
    in_reply_to_request_id TEXT UNIQUE,
    processing_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

Add `confirmed_facts`, `context_summaries`, and `cleanup_jobs` with the same conversation foreign key. `search_conversations(query)` loads non-deleted rows, decrypts in the current process, and performs a casefolded title/message match without persisting matches.

- [ ] **Step 4: Implement safe deletion and retry state**

`delete_conversation(conversation_id)` first copies random encrypted attachment paths into cleanup jobs, then hard-deletes messages, facts, summaries, generations, document usages, attachment metadata, and corrected OCR text. It scrubs the encrypted title and leaves only an invisible tombstone plus cleanup jobs in the same transaction, so a file-cleanup failure cannot make the conversation reappear. The later learning plan handles its separate database through an idempotent cleanup job. `list_retryable_requests(conversation_id)` returns failed/interrupted requests only; on repository initialization, convert `processing` to `interrupted`, never start work.

- [ ] **Step 5: Run focused tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_conversations.py -q`

Expected: lifecycle, encryption, restart, request idempotency, and isolation tests all pass.

```powershell
git add -- src/lexiaodu/conversations.py tests/test_conversations.py
git commit -m "feat: persist isolated encrypted conversations"
```

### Task 3: Encrypted Screenshot Attachments and OCR Correction

**Files:**
- Create: `src/lexiaodu/attachments.py`
- Create: `tests/test_attachments.py`
- Modify: `src/lexiaodu/editor.py`
- Modify: `tests/test_editor.py`

**Interfaces:**
- Produces `AttachmentStore(root, repository, cipher)` with `save_image`, `load_image`, `save_corrected_text`, `list_for_conversation`, and `run_cleanup_jobs`.
- Adds an editor result signal or result object that returns corrected transcript text to the owning chat draft without triggering advice generation.

- [ ] **Step 1: Write failing encrypted-file lifecycle tests**

Create a small in-memory `QImage`, store it in conversation A, and assert conversation B cannot load it. Assert the disk file has a random attachment ID, no `.png/.jpg` suffix, and does not contain the source PNG signature or a sentinel embedded in OCR text. Reopen the store, load the same image, delete the conversation, run cleanup twice, and assert the file remains absent without error.

- [ ] **Step 2: Run the tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_attachments.py tests/test_editor.py -q`

Expected: attachment tests fail because the store does not exist; existing editor tests remain green.

- [ ] **Step 3: Implement per-attachment envelope encryption and metadata storage**

Encode the `QImage` to PNG in memory. Generate a fresh 32-byte data key for that attachment, encrypt PNG bytes with AES-GCM, encrypt the data key through `DataCipher`, and store that encrypted data key in the attachment row. Write the versioned nonce+ciphertext atomically to `root / f"{uuid4().hex}.bin"`. Insert metadata only after the encrypted replace succeeds; if the insert fails, remove that newly created file. Load requires both attachment ID and conversation ID.

```python
def load_image(self, conversation_id: str, attachment_id: str) -> QImage:
    record = self._repository.get_attachment(conversation_id, attachment_id)
    data_key = self._cipher.decrypt(record.encrypted_data_key)
    payload = record.encrypted_path.read_bytes()
    raw = decrypt_attachment_payload(data_key, payload)
    image = QImage.fromData(raw, b"PNG")
    if image.isNull():
        raise AttachmentCorrupt("附件无法解码")
    return image
```

Do not log paths alongside OCR text or message bodies.

- [ ] **Step 4: Decouple OCR correction from advice generation**

Keep existing `TranscriptEditor` behavior for legacy use, but add a neutral method returning the corrected transcript. The new chat controller owns when that text becomes a draft attachment; accepting the editor must not call `AdviceService`.

- [ ] **Step 5: Run focused tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_attachments.py tests/test_editor.py tests/test_ocr.py -q`

Expected: encrypted lifecycle, correction, and existing OCR tests pass.

```powershell
git add -- src/lexiaodu/attachments.py src/lexiaodu/editor.py tests/test_attachments.py tests/test_editor.py
git commit -m "feat: add encrypted chat screenshot attachments"
```

### Task 4: Same-Thread Context Builder and Summary Invalidation

**Files:**
- Create: `src/lexiaodu/context.py`
- Create: `tests/test_context.py`

**Interfaces:**
- Produces `ContextPackage(confirmed_facts, summary, recent_messages, related_messages, attachment_texts, context_version)`.
- Produces `ContextBuilder(repository, recent_limit, related_limit, character_budget).build(conversation_id, current_text)`.
- Produces `SummaryCoordinator` with an injected `ContextSummarizer` protocol; this plan uses a test fake and does not yet call the production model. The original-document advisor plan supplies the production implementation.

- [ ] **Step 1: Write failing budget, relevance, invalidation, and isolation tests**

Seed 30 messages in conversation A and similar messages in conversation B. Assert the package order is facts, valid summary, recent messages, relevant older messages, and current attachments; total text stays within the configured budget; no record from B appears. Edit or delete a message covered by the summary and assert the old summary is excluded immediately.

```python
package = builder.build(first.id, "现在主要担心英语开口")
assert package.context_version == repository.get_conversation(first.id).context_version
assert all(item.conversation_id == first.id for item in package.all_items())
assert "另一个家庭的哨兵" not in package.render_for_model()
```

- [ ] **Step 2: Run context tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_context.py -q`

Expected: collection fails because `lexiaodu.context` does not exist.

- [ ] **Step 3: Implement deterministic package assembly**

Select recent turns by message order. Score older same-thread turns using normalized token overlap with `current_text`; do not add a cross-thread vector index. Include a summary only when its recorded start/end message IDs still exist and its `context_version` equals the conversation version. Trim oldest related content before recent turns, facts, or current draft text.

- [ ] **Step 4: Implement summary versioning and failure fallback**

`SummaryCoordinator` saves a summary only after the injected summarizer returns successfully, recording covered IDs and version. On summarizer failure, retain original messages and let the builder fall back to the most recent content that fits. Editing/deleting covered messages increments `context_version`; summary generation can be retried later.

- [ ] **Step 5: Run focused tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_context.py tests/test_conversations.py -q`

Expected: all context, fallback, and cross-thread isolation tests pass.

```powershell
git add -- src/lexiaodu/context.py tests/test_context.py src/lexiaodu/conversations.py tests/test_conversations.py
git commit -m "feat: build restart-safe thread context"
```

### Task 5: Independent Chat Main Window

**Files:**
- Create: `src/lexiaodu/chat_window.py`
- Create: `tests/test_chat_window.py`
- Modify: `src/lexiaodu/chat.py`
- Modify: `tests/test_chat.py`

**Interfaces:**
- Produces `ChatMainWindow(QMainWindow)` signals for create/select/rename/delete/search/send/retry/capture/paste/generate-reply/open-drawer.
- Consumes plain view models; it does not query SQLite or call models directly.
- Reuses a public `SuggestionCard` extracted from the current private `_SuggestionCard` without changing its risk/copy behavior.

- [ ] **Step 1: Write failing shell interaction tests**

Use real Qt widgets offscreen. Assert the top-level widget is a `QMainWindow`, contains one conversation list, central message timeline, composer, screenshot action, send action, and hidden right drawer. Verify selecting two conversations replaces visible turns instead of merging them. Verify Enter sends, Shift+Enter inserts a line break, retry emits the original request ID, and formal reply cards appear only when explicitly appended.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_chat_window.py tests/test_chat.py -q`

Expected: new tests fail because `ChatMainWindow` does not exist; legacy chat tests remain green.

- [ ] **Step 3: Implement the smallest chat-first layout**

Build a three-region window with object names used by tests: `conversationSidebar`, `messageTimeline`, `chatComposer`, and `contextDrawer`. Use item data for conversation IDs; never infer identity from visible titles. Display tool activity as short timeline events such as “正在读取本地附件”, not prompts or chain-of-thought.

- [ ] **Step 4: Extract the existing reply card safely**

Rename `_SuggestionCard` to public `SuggestionCard` and keep an alias for legacy imports during migration. Preserve editable text, evidence list, risk confirmation, feedback emission, and copying of the edited value.

- [ ] **Step 5: Run UI tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_chat_window.py tests/test_chat.py tests/test_font_scaling.py -q`

Expected: new shell and existing chat/font behavior pass.

```powershell
git add -- src/lexiaodu/chat_window.py src/lexiaodu/chat.py tests/test_chat_window.py tests/test_chat.py
git commit -m "feat: add independent advisor chat window"
```

### Task 6: Persistence Controller, Screenshot Flow, and Retry Idempotency

**Files:**
- Create: `src/lexiaodu/chat_controller.py`
- Create: `tests/test_chat_controller.py`

**Interfaces:**
- Produces `ChatController(window, repository, attachments, context_builder, assistant, capture, ocr, selector_factory, editor_factory, assistant_executor, ocr_executor)`.
- Consumes an injected `ConversationAssistant.respond(context, request_id)` protocol; production document-aware behavior is added by a later plan.

- [ ] **Step 1: Write failing controller ordering tests**

Use fakes that record calls. Assert `append_user_message` completes before `assistant.respond`; failure sets the existing message to failed; retry uses the same request ID and cannot produce two assistant rows. Simulate application reconstruction and assert interrupted requests display as retryable but the fake assistant receives no call.

- [ ] **Step 2: Add screenshot draft tests**

Simulate select → in-memory capture → OCR → correction → attach. Assert the image and corrected text belong to the active conversation at capture start even if the sidebar selection changes while OCR runs. Assert original image bytes never reach the assistant fake; only the corrected text in `ContextPackage` does.

- [ ] **Step 3: Run controller tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_chat_controller.py -q`

Expected: collection fails because `ChatController` does not exist.

- [ ] **Step 4: Implement one-worker background orchestration**

Persist first, mark processing, build context, then submit to a single assistant executor. Carry `(conversation_id, request_id)` through every callback and discard UI delivery if the window has switched threads; still persist the completed assistant message to its owning thread. Use the existing single OCR worker pattern but keep it independent from assistant work.

- [ ] **Step 5: Run focused tests and commit**

Run: `.\.venv\python.exe -B -m pytest tests/test_chat_controller.py tests/test_workflow.py -q`

Expected: new controller and legacy workflow tests pass.

```powershell
git add -- src/lexiaodu/chat_controller.py tests/test_chat_controller.py
git commit -m "feat: orchestrate persistent chat and screenshot input"
```

### Task 7: Default Startup, Rollback Flag, and Recovery Acceptance

**Files:**
- Modify: `src/lexiaodu/app.py`
- Modify: `tests/test_app.py`
- Create: `tests/test_chat_recovery_acceptance.py`
- Modify: `README.md`
- Modify: `docs/MANUAL_TEST_CHECKLIST.md`

- [ ] **Step 1: Write failing startup mode tests**

Extract construction into `build_chat_runtime(settings, assistant)` and `build_legacy_runtime(settings, generator)` so tests do not enter `application.exec()`. Assert default mode constructs and shows `ChatMainWindow` with no `FloatingToolbar`; `LEXIAODU_UI_MODE=legacy` constructs the existing toolbar/controller; any other value returns configuration error 2.

- [ ] **Step 2: Write restart and deletion acceptance tests**

Run a complete fake session, dispose all runtime objects, reopen the same database/key/attachment directory, and assert messages, corrected attachment text, and reply card records restore. Delete the conversation, reconstruct again, and assert it and its attachment are absent. Include two similar conversations and a sentinel proving no cross-thread context.

- [ ] **Step 3: Run acceptance tests and verify RED**

Run: `.\.venv\python.exe -B -m pytest tests/test_app.py tests/test_chat_recovery_acceptance.py -q`

Expected: startup tests fail because the current app always constructs `FloatingToolbar`.

- [ ] **Step 4: Wire the new runtime and preserve legacy rollback**

Create the cipher, repository, attachment store, context builder, window, and controller only in chat mode. Keep runtime objects alive until `application.exec()` returns and shut down executors on `aboutToQuit`. The default simulated assistant should explain it is an offline demo and must not fabricate company facts.

- [ ] **Step 5: Update operator documentation**

Document local-history encryption, DPAPI recovery limitation, shared-Windows-account boundary, default chat startup, `LEXIAODU_UI_MODE=legacy`, screenshot-local-only behavior, and new manual cases for restart, thread isolation, deletion, damaged attachment, failed retry, and font scaling in the independent window.

- [ ] **Step 6: Run the full regression suite and commit**

Run: `.\.venv\python.exe -B -m pytest -q`

Run: `.\.venv\python.exe -m pip check`

Expected: the full suite passes; no secret, screenshot, chat sentinel, or generated `data/` file is tracked.

```powershell
git status --short
git add -- src/lexiaodu/app.py tests/test_app.py tests/test_chat_recovery_acceptance.py README.md docs/MANUAL_TEST_CHECKLIST.md
git commit -m "feat: launch persistent advisor chat by default"
```

### Task 8: Manual Windows Acceptance Gate

**Files:**
- Modify only the result cells in `docs/MANUAL_TEST_CHECKLIST.md` when the named test machine is available.

- [ ] **Step 1: Run on a non-production Windows test account**

Verify new chat, rename/search/delete, multi-turn history, restart recovery, screenshot select/paste/OCR/correction, damaged attachment handling, failed request retry, formal reply-card copy gate, and legacy rollback. Use only fabricated parent data.

- [ ] **Step 2: Inspect storage boundaries**

Search `data/chat.sqlite3`, `data/chat-attachments`, logs, and `artifacts` for the fabricated sentinel in raw bytes. Expected: no plaintext sentinel and no standalone image. Log out and use a different Windows account; expected: history is not decryptable through the application.

- [ ] **Step 3: Record the gate result**

Record machine, Windows account type, date, and failures in the checklist. Do not mark this plan complete if restart recovery, cross-thread isolation, plaintext storage, or deletion cleanup fails.
