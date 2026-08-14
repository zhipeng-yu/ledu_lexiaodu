# Chat Screenshot Vision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one encrypted chat screenshot to a consultant message and let the existing Doubao advisor flow use it for clarification or reply advice.

**Architecture:** Restore only the useful encrypted-file pattern from the deleted attachment code as a focused `ScreenshotStore`. Extend the current repository, context package, model payload, chat window, controller, and runtime in place; every model request carries at most one `high`-detail image and there is no OCR, image slicing, or derived transcript.

**Tech Stack:** Python 3.11, PySide6, SQLite, `cryptography` AES-GCM, OpenAI-compatible Ark Chat Completions/Responses APIs, pytest.

## Global Constraints

- Only the file picker is supported; one message accepts one PNG, JPG, JPEG, or WebP image.
- The original image is encrypted locally, restored after restart, reusable on retry, and removed with its conversation.
- Send image bytes as Base64 over HTTPS to the existing `ARK_MODEL` with detail fixed to `high`.
- Use at most one image per model request: the request-bound image first, otherwise the newest selected-context image; retry always uses the original request image.
- Keep the current company-document selection, unified knowledge retrieval, strict response schema, consultant role, and teaching-role boundaries intact.
- Do not add OCR, local vision, image slicing, paste/capture, multi-image messages, TOS, Ark Files API, image knowledge-base upload, derived transcripts, new model configuration, or new dependencies.
- Use only synthetic or deidentified screenshots for live verification.
- Keep changes surgical and update `HANDOFF.md` instead of appending stale history.

---

## File Map

- Create `src/lexiaodu/screenshot_store.py`: per-image envelope encryption, atomic files, scoped reads, and verified deletion.
- Modify `src/lexiaodu/chat_repository.py`: `ScreenshotAttachment` metadata and focused CRUD/rollback methods.
- Modify `src/lexiaodu/chat_context.py`: select at most one context image and carry its original bytes.
- Modify `src/lexiaodu/advisor_assistant.py`: build Ark multimodal payloads and add screenshot role rules.
- Modify `src/lexiaodu/chat_window.py`: one-file draft, preview/remove controls, screenshot timeline thumbnail, and image-send signal.
- Modify `src/lexiaodu/chat_controller.py`: persist image messages, reuse images on retry, render history, and delete image files before conversations.
- Modify `src/lexiaodu/app.py`: construct one screenshot store at `database_path.parent / "chat-images"` and inject it.
- Modify `README.md`, `docs/MANUAL_TEST_CHECKLIST.md`, and `HANDOFF.md`: document the exact feature, privacy boundary, and verified state.
- Create `tests/test_screenshot_store.py`; extend the existing repository, context, assistant, shell, controller, and app tests.

---

### Task 1: Encrypted Screenshot Persistence

**Files:**
- Create: `src/lexiaodu/screenshot_store.py`
- Create: `tests/test_screenshot_store.py`
- Modify: `src/lexiaodu/chat_repository.py:29-167,254-557`
- Modify: `tests/test_chat_repository.py:1-165`

**Interfaces:**
- Consumes: `DataCipher.encrypt(bytes) -> bytes`, `DataCipher.decrypt(bytes) -> bytes`, existing conversation/message IDs.
- Produces: `ScreenshotAttachment`, `ScreenshotPayload`, `ScreenshotStore.save(conversation_id, message_id, data, mime_type, width, height)`, `ScreenshotStore.load_for_message(conversation_id, message_id)`, `ScreenshotStore.remove_for_conversation(conversation_id)`, and `ConversationRepository.delete_pending_user_request(conversation_id, request_id)`.

- [ ] **Step 1: Write failing encrypted lifecycle and rollback tests**

Create `tests/test_screenshot_store.py` with focused byte-level fixtures; do not involve Qt:

```python
from pathlib import Path

import pytest

from lexiaodu.chat_repository import ConversationRepository
from lexiaodu.local_crypto import DataCipher
from lexiaodu.screenshot_store import ScreenshotCorrupt, ScreenshotStore


PNG_SENTINEL = b"\x89PNG\r\n\x1a\nPRIVATE-CHAT-SENTINEL"


def test_screenshot_is_encrypted_scoped_restart_safe_and_deleted(tmp_path: Path):
    cipher = DataCipher(b"s" * 32)
    database = tmp_path / "chat.sqlite3"
    repository = ConversationRepository(database, cipher)
    first = repository.create_conversation("first")
    second = repository.create_conversation("second")
    message = repository.append_user_message(
        first.id, "聊天截图", request_id="request-1", kind="image"
    )
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)

    attachment = store.save(
        first.id, message.id, PNG_SENTINEL, "image/png", 1080, 12000
    )

    assert attachment.encrypted_path.suffix == ".bin"
    assert PNG_SENTINEL not in attachment.encrypted_path.read_bytes()
    assert store.load_for_message(first.id, message.id).data == PNG_SENTINEL
    assert store.load_for_message(second.id, message.id) is None

    reopened = ConversationRepository(database, cipher)
    reopened_store = ScreenshotStore(tmp_path / "chat-images", reopened, cipher)
    assert reopened_store.load_for_message(first.id, message.id).height == 12000

    reopened_store.remove_for_conversation(first.id)
    reopened.delete_conversation(first.id)
    assert not attachment.encrypted_path.exists()


def test_tampered_screenshot_fails_authentication(tmp_path: Path):
    cipher = DataCipher(b"t" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    conversation = repository.create_conversation("tamper")
    message = repository.append_user_message(
        conversation.id, "聊天截图", request_id="request", kind="image"
    )
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    attachment = store.save(
        conversation.id, message.id, PNG_SENTINEL, "image/png", 10, 20
    )
    attachment.encrypted_path.write_bytes(
        attachment.encrypted_path.read_bytes()[:-1] + b"x"
    )

    with pytest.raises(ScreenshotCorrupt, match="截图无法解密"):
        store.load_for_message(conversation.id, message.id)
```

Extend `tests/test_chat_repository.py` to assert reopening preserves the new `screenshot_attachments` table while the existing migration still removes only legacy `attachments`, `corrected_ocr_texts`, and `kind='screenshot'` rows. Add a rollback test for `delete_pending_user_request(conversation_id, request_id)` that deletes only a pending/failed user request with no assistant reply.

- [ ] **Step 2: Run the focused tests and confirm the expected failure**

Run:

```powershell
.\.venv\python.exe -B -m pytest tests/test_screenshot_store.py tests/test_chat_repository.py -q
```

Expected: FAIL during collection because `lexiaodu.screenshot_store` and `ScreenshotAttachment` do not exist.

- [ ] **Step 3: Add the minimal repository schema and methods**

Add to `chat_repository.py`:

```python
@dataclass(frozen=True, slots=True)
class ScreenshotAttachment:
    id: str
    conversation_id: str
    message_id: str
    encrypted_path: Path
    encrypted_data_key: bytes
    mime_type: str
    width: int
    height: int
    created_at: datetime
```

Create `screenshot_attachments` after `messages`:

```sql
CREATE TABLE IF NOT EXISTS screenshot_attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    message_id TEXT NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
    encrypted_path TEXT NOT NULL UNIQUE,
    encrypted_data_key BLOB NOT NULL,
    mime_type TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
```

Do not add this table to `_remove_legacy_content`. Add exact methods:

```python
def save_screenshot_attachment(
    self,
    conversation_id: str,
    message_id: str,
    attachment_id: str,
    encrypted_path: Path,
    encrypted_data_key: bytes,
    mime_type: str,
    width: int,
    height: int,
) -> ScreenshotAttachment:
    now = self._clock()
    attachment = ScreenshotAttachment(
        attachment_id, conversation_id, message_id, encrypted_path,
        encrypted_data_key, mime_type, width, height, now,
    )
    with self._connect() as connection:
        self._require_conversation(connection, conversation_id)
        owner = connection.execute(
            "SELECT role FROM messages WHERE id = ? AND conversation_id = ?",
            (message_id, conversation_id),
        ).fetchone()
        if owner is None or owner["role"] != "user":
            raise KeyError(message_id)
        connection.execute(
            """
            INSERT INTO screenshot_attachments(
                id, conversation_id, message_id, encrypted_path,
                encrypted_data_key, mime_type, width, height, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attachment.id, attachment.conversation_id, attachment.message_id,
                str(attachment.encrypted_path), attachment.encrypted_data_key,
                attachment.mime_type, attachment.width, attachment.height,
                attachment.created_at.isoformat(),
            ),
        )
    return attachment

def get_screenshot_for_message(
    self, conversation_id: str, message_id: str
) -> ScreenshotAttachment | None:
    with self._connect() as connection:
        self._require_conversation(connection, conversation_id)
        row = connection.execute(
            """
            SELECT * FROM screenshot_attachments
            WHERE conversation_id = ? AND message_id = ?
            """,
            (conversation_id, message_id),
        ).fetchone()
    return self._screenshot(row) if row is not None else None

def list_screenshots(
    self, conversation_id: str
) -> tuple[ScreenshotAttachment, ...]:
    with self._connect() as connection:
        self._require_conversation(connection, conversation_id)
        rows = connection.execute(
            """
            SELECT * FROM screenshot_attachments
            WHERE conversation_id = ? ORDER BY created_at, id
            """,
            (conversation_id,),
        ).fetchall()
    return tuple(self._screenshot(row) for row in rows)

def delete_pending_user_request(
    self, conversation_id: str, request_id: str
) -> None:
    with self._connect() as connection:
        self._require_conversation(connection, conversation_id)
        row = self._request_row(connection, conversation_id, request_id)
        reply = connection.execute(
            """
            SELECT 1 FROM messages
            WHERE conversation_id = ? AND in_reply_to_request_id = ?
            """,
            (conversation_id, request_id),
        ).fetchone()
        if row["processing_status"] == "completed" or reply is not None:
            raise ValueError("已完成请求不能回滚")
        connection.execute("DELETE FROM messages WHERE id = ?", (row["id"],))

def _screenshot(self, row: sqlite3.Row) -> ScreenshotAttachment:
    return ScreenshotAttachment(
        id=row["id"],
        conversation_id=row["conversation_id"],
        message_id=row["message_id"],
        encrypted_path=Path(row["encrypted_path"]),
        encrypted_data_key=bytes(row["encrypted_data_key"]),
        mime_type=row["mime_type"],
        width=int(row["width"]),
        height=int(row["height"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
```

`save_screenshot_attachment` must verify the message belongs to the same live conversation and has `role='user'`. `delete_pending_user_request` must reject completed requests or requests with an assistant reply.

- [ ] **Step 4: Implement the focused store by reusing the old envelope pattern**

Create `screenshot_store.py` with no OCR or cleanup queue:

```python
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .chat_repository import ConversationRepository, ScreenshotAttachment
from .local_crypto import DataCipher

_VERSION = b"\x01"


class ScreenshotCorrupt(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScreenshotPayload:
    data: bytes
    mime_type: str
    width: int
    height: int


class ScreenshotStore:
    def __init__(
        self,
        root: str | Path,
        repository: ConversationRepository,
        cipher: DataCipher,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._repository = repository
        self._cipher = cipher

    def save(
        self,
        conversation_id: str,
        message_id: str,
        data: bytes,
        mime_type: str,
        width: int,
        height: int,
    ) -> ScreenshotAttachment:
        if not data or mime_type not in {
            "image/png", "image/jpeg", "image/webp"
        } or width < 1 or height < 1:
            raise ValueError("截图数据无效")
        attachment_id = uuid4().hex
        path = self._root / f"{attachment_id}.bin"
        data_key = os.urandom(32)
        nonce = os.urandom(12)
        payload = _VERSION + nonce + AESGCM(data_key).encrypt(
            nonce, data, _VERSION
        )
        self._atomic_write(path, payload)
        try:
            return self._repository.save_screenshot_attachment(
                conversation_id, message_id, attachment_id, path,
                self._cipher.encrypt(data_key), mime_type, width, height,
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def load_for_message(
        self, conversation_id: str, message_id: str
    ) -> ScreenshotPayload | None:
        attachment = self._repository.get_screenshot_for_message(
            conversation_id, message_id
        )
        if attachment is None:
            return None
        payload = attachment.encrypted_path.read_bytes()
        if len(payload) < 14 or payload[:1] != _VERSION:
            raise ScreenshotCorrupt("截图无法解密")
        try:
            data = AESGCM(self._cipher.decrypt(attachment.encrypted_data_key)).decrypt(
                payload[1:13], payload[13:], _VERSION
            )
        except (InvalidTag, ValueError) as exc:
            raise ScreenshotCorrupt("截图无法解密") from exc
        return ScreenshotPayload(
            data, attachment.mime_type, attachment.width, attachment.height
        )

    def remove_for_conversation(self, conversation_id: str) -> None:
        root = self._root.resolve()
        for attachment in self._repository.list_screenshots(conversation_id):
            path = attachment.encrypted_path.resolve()
            if path.parent != root:
                raise ScreenshotCorrupt("截图路径无效")
            path.unlink(missing_ok=True)

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self._root, prefix=f".{path.stem}.",
                suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
```

Keep annotations explicit in the implementation; the abbreviated bodies above define behavior, not permission to introduce a generic attachment base class.

- [ ] **Step 5: Run focused persistence tests**

Run:

```powershell
.\.venv\python.exe -B -m pytest tests/test_screenshot_store.py tests/test_chat_repository.py tests/test_local_crypto.py -q
```

Expected: PASS. Inspect `tmp_path/chat-images` assertions to confirm no PNG/JPEG sentinel or plaintext data key is present.

- [ ] **Step 6: Commit the persistence slice**

```powershell
git add -- src/lexiaodu/screenshot_store.py src/lexiaodu/chat_repository.py tests/test_screenshot_store.py tests/test_chat_repository.py
git commit -m "feat: store encrypted chat screenshots"
```

---

### Task 2: One-Image Context and Doubao Payload

**Files:**
- Modify: `src/lexiaodu/chat_context.py:1-51`
- Modify: `src/lexiaodu/advisor_assistant.py:1-221,325-362`
- Modify: `tests/test_chat_context.py:1-57`
- Modify: `tests/test_advisor_assistant.py:1-740`

**Interfaces:**
- Consumes: `ScreenshotStore.load_for_message(conversation_id, message_id) -> ScreenshotPayload | None` from Task 1.
- Produces: `ContextImage`, `ContextPackage.image`, `ContextBuilder.build(conversation_id, request_message_id=None)`, Chat Completions `image_url`, and Responses `input_image` payloads.

- [ ] **Step 1: Write failing context-selection tests**

Extend `tests/test_chat_context.py`:

```python
def test_builder_uses_request_image_then_latest_context_image(tmp_path):
    cipher = DataCipher(b"i" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    conversation = repository.create_conversation("images")
    first = repository.append_user_message(
        conversation.id, "第一张", request_id="first", kind="image"
    )
    store.save(conversation.id, first.id, b"FIRST", "image/png", 10, 100)
    text = repository.append_user_message(
        conversation.id, "继续分析", request_id="text"
    )
    builder = ContextBuilder(repository, store, character_budget=1000)
    assert builder.build(
        conversation.id, request_message_id=first.id
    ).image.data == b"FIRST"
    assert builder.build(
        conversation.id, request_message_id=text.id
    ).image.data == b"FIRST"

    second = repository.append_user_message(
        conversation.id, "第二张", request_id="second", kind="image"
    )
    store.save(conversation.id, second.id, b"SECOND", "image/png", 10, 200)
    latest_text = repository.append_user_message(
        conversation.id, "继续第二张", request_id="latest-text"
    )
    assert builder.build(
        conversation.id, request_message_id=latest_text.id
    ).image.data == b"SECOND"
```

Also assert no image crosses conversations and an image on a message removed by the character budget is not selected for an ordinary text request.

- [ ] **Step 2: Write failing multimodal request tests**

Extend the existing fake-client tests in `tests/test_advisor_assistant.py` and construct:

```python
context = ContextPackage(
    messages=(),
    context_version=1,
    image=ContextImage("image/png", b"LONG-SCREENSHOT"),
)
```

Assert the no-knowledge Chat Completions user content contains exactly one item of each type:

```python
assert content[0] == {"type": "text", "text": ""}
assert content[1]["type"] == "image_url"
assert content[1]["image_url"]["detail"] == "high"
assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
```

For a selected knowledge document, assert the Responses request contains one `input_text` and one:

```python
{
    "type": "input_image",
    "image_url": "data:image/png;base64,TE9ORy1TQ1JFRU5TSE9U",
    "detail": "high",
}
```

Assert the document-routing call also receives the image, and plain-text contexts retain their current string payloads.

- [ ] **Step 3: Run the tests and confirm they fail for missing image support**

```powershell
.\.venv\python.exe -B -m pytest tests/test_chat_context.py tests/test_advisor_assistant.py -q
```

Expected: FAIL because `ContextImage`, the store dependency, and multimodal payloads are absent.

- [ ] **Step 4: Implement one-image context selection**

Add to `chat_context.py`:

```python
from .screenshot_store import ScreenshotPayload, ScreenshotStore


@dataclass(frozen=True, slots=True)
class ContextImage:
    mime_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ContextPackage:
    messages: tuple[Message, ...]
    context_version: int
    image: ContextImage | None = None
```

Change construction to:

```python
class ContextBuilder:
    def __init__(
        self,
        repository: ConversationRepository,
        screenshot_store: ScreenshotStore,
        *,
        character_budget: int,
    ) -> None:
        if character_budget < 1:
            raise ValueError("character_budget 必须是正整数")
        self._repository = repository
        self._screenshot_store = screenshot_store
        self._character_budget = character_budget

    def build(
        self,
        conversation_id: str,
        *,
        request_message_id: str | None = None,
    ) -> ContextPackage:
        conversation = self._repository.get_conversation(conversation_id)
        messages = self._repository.list_messages(conversation_id)
        selected: list[Message] = []
        used = 0
        for message in reversed(messages):
            label = _ROLE_LABELS.get(message.role, message.role)
            length = len(label) + 1 + len(message.body) + (1 if selected else 0)
            if selected and used + length > self._character_budget:
                break
            selected.append(message)
            used += length
        selected.reverse()

        payload: ScreenshotPayload | None = None
        if request_message_id is not None:
            payload = self._screenshot_store.load_for_message(
                conversation_id, request_message_id
            )
        if payload is None:
            for message in reversed(selected):
                payload = self._screenshot_store.load_for_message(
                    conversation_id, message.id
                )
                if payload is not None:
                    break
        image = (
            ContextImage(payload.mime_type, payload.data)
            if payload is not None else None
        )
        return ContextPackage(tuple(selected), conversation.context_version, image)
```

Do not count image bytes as text characters and do not select more than one image.

- [ ] **Step 5: Implement minimal Ark payload helpers and prompt rules**

Use `base64.b64encode` from the standard library. Preserve string content for text-only calls; only image calls use content arrays:

```python
def _chat_user_content(context: ContextPackage, text: str) -> str | list[dict[str, Any]]:
    if context.image is None:
        return text
    data = base64.b64encode(context.image.data).decode("ascii")
    return [
        {"type": "text", "text": text},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{context.image.mime_type};base64,{data}",
                "detail": "high",
            },
        },
    ]
```

Call this helper from `_select_documents` and `_respond_with_chat`. Add the equivalent `input_image` item to `_respond_with_knowledge_documents` only when `context.image` exists.

Append these exact behavior rules to `_SYSTEM_PROMPT` without changing unrelated wording:

```text
聊天截图可能来自个人聊天或群聊。结合昵称、气泡方向和上下文判断参与者身份；
无法确定顾问、家长或其他成员身份时，不得猜测，只向顾问追问一个最关键的身份问题，
且不要生成家长话术。截图中的聊天案例不能作为公司政策、课程、价格或承诺的事实来源。
```

When a multimodal call raises, wrap it as:

```python
raise AdvisorAssistantError(
    "豆包截图分析失败，请检查网络并确认 ARK_MODEL 支持图片理解"
) from exc
```

Keep the existing generic error for text-only requests.

- [ ] **Step 6: Run model/context regression tests**

```powershell
.\.venv\python.exe -B -m pytest tests/test_chat_context.py tests/test_advisor_assistant.py tests/test_office_documents.py -q
```

Expected: PASS; plain text document routing and strict response rendering remain unchanged.

- [ ] **Step 7: Commit the multimodal core**

```powershell
git add -- src/lexiaodu/chat_context.py src/lexiaodu/advisor_assistant.py tests/test_chat_context.py tests/test_advisor_assistant.py
git commit -m "feat: send chat screenshots to doubao"
```

---

### Task 3: Single-Image Composer and Timeline

**Files:**
- Modify: `src/lexiaodu/chat_window.py:1-522`
- Modify: `tests/test_chat_shell.py:1-88`

**Interfaces:**
- Consumes: native `QFileDialog`, `QImageReader`, `QImage`, and `QPixmap`; no new package.
- Produces: `ScreenshotDraft(data, mime_type, width, height)`, `send_image_requested(str, object)`, and `ChatTurnView.image`.

- [ ] **Step 1: Write failing composer and timeline tests**

Extend `tests/test_chat_shell.py` with an in-memory image and monkeypatched file dialog:

```python
def test_single_screenshot_draft_can_send_without_text(tmp_path, monkeypatch):
    _application()
    path = tmp_path / "long.png"
    image = QImage(20, 400, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    assert image.save(str(path), "PNG")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *_args, **_kwargs: (str(path), "PNG (*.png)"),
    )
    window = ChatMainWindow()
    window.set_conversations((ChatConversationView("c1", "截图"),))
    window.select_conversation("c1")
    sent = []
    window.send_image_requested.connect(
        lambda text, draft: sent.append((text, draft))
    )

    window.findChild(QPushButton, "selectScreenshot").click()
    assert window.submit_composer()

    assert sent[0][0] == ""
    assert sent[0][1].height == 400
    assert window.findChild(QLabel, "screenshotDraft").isHidden()
```

Add tests that remove/replace the draft, reject an invalid file without emitting, keep Enter text-only behavior, and render a `ChatTurnView` thumbnail. Continue asserting `captureScreenshot` and `pasteScreenshot` do not exist.

- [ ] **Step 2: Run the shell tests and confirm the missing widget/signal failure**

```powershell
.\.venv\python.exe -B -m pytest tests/test_chat_shell.py -q
```

Expected: FAIL because `send_image_requested`, `selectScreenshot`, and screenshot preview data are absent.

- [ ] **Step 3: Implement the one-file draft with native Qt**

Add:

```python
@dataclass(frozen=True, slots=True)
class ScreenshotDraft:
    data: bytes
    mime_type: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ChatTurnView:
    id: str
    role: str
    text: str
    request_id: str | None = None
    status: str = "complete"
    kind: str = "message"
    image: QImage | None = None
```

Add `send_image_requested = Signal(str, object)`. In the composer actions, add only `selectScreenshot`, a hidden `screenshotDraft` preview row, and `removeScreenshot`. Do not add capture or paste actions.

`_choose_screenshot` must:

1. call `QFileDialog.getOpenFileName` with `图片 (*.png *.jpg *.jpeg *.webp)`;
2. require an allowed suffix;
3. read non-empty bytes;
4. use `QImageReader.imageFormat(path)` and `QImage.fromData(data)` to require a supported, decodable image;
5. store only bytes, MIME type, width, and height in `ScreenshotDraft`;
6. show a scaled thumbnail without storing the source path or filename.

Change `submit_composer` minimally:

```python
text = self._composer.toPlainText().strip()
if self._active_conversation_id is None or (not text and self._screenshot_draft is None):
    return False
if self._screenshot_draft is None:
    self.send_requested.emit(text)
else:
    self.send_image_requested.emit(text, self._screenshot_draft)
self._composer.clear()
self._clear_screenshot_draft()
return True
```

In `_TimelineTurn`, display `turn.image` as a width-bounded thumbnail above the text. Do not add an image viewer or attachment menu.

- [ ] **Step 4: Run shell and font-scaling tests**

```powershell
.\.venv\python.exe -B -m pytest tests/test_chat_shell.py tests/test_font_scaling.py -q
```

Expected: PASS with the new controls present and all removed legacy controls still absent.

- [ ] **Step 5: Commit the window slice**

```powershell
git add -- src/lexiaodu/chat_window.py tests/test_chat_shell.py
git commit -m "feat: add single screenshot composer"
```

---

### Task 4: Controller and Runtime Wiring

**Files:**
- Modify: `src/lexiaodu/chat_controller.py:1-263`
- Modify: `src/lexiaodu/app.py:1-220`
- Modify: `tests/test_chat_controller.py:1-414`
- Modify: `tests/test_app.py:1-315`

**Interfaces:**
- Consumes: `ScreenshotDraft`, `ScreenshotStore`, and `ContextBuilder.build(conversation_id, request_message_id=None)` from Tasks 1-3.
- Produces: persistent image send/retry/delete orchestration and runtime injection.

- [ ] **Step 1: Write failing controller persistence, retry, and deletion tests**

Extend `FakeWindow` with `send_image_requested = Signal(str, object)`. Add a test using a real repository/store and `ManualExecutor`:

```python
def test_image_is_persisted_before_assistant_and_retry_reuses_it(tmp_path):
    application()
    cipher = DataCipher(b"c" * 32)
    repository = ConversationRepository(tmp_path / "chat.sqlite3", cipher)
    store = ScreenshotStore(tmp_path / "chat-images", repository, cipher)
    conversation = repository.create_conversation("image")
    window = FakeWindow()
    assistant = RecordingAssistant(repository, [RuntimeError("offline"), "OK"])
    executor = ManualExecutor()
    ChatController(
        window, repository,
        ContextBuilder(repository, store, character_budget=10_000),
        store, assistant, executor,
    )
    window.select(conversation.id)
    draft = ScreenshotDraft(b"PNG-DATA", "image/png", 20, 400)

    window.send_image_requested.emit("", draft)
    request = repository.list_messages(conversation.id)[0]
    assert store.load_for_message(conversation.id, request.id).data == b"PNG-DATA"
    executor.run_next()
    window.retry_requested.emit(request.request_id)
    executor.run_next()

    assert [call[0].image.data for call in assistant.calls] == [
        b"PNG-DATA", b"PNG-DATA"
    ]
```

Add tests that:

- a store save error deletes the pending user message and does not dispatch;
- selecting another conversation during work does not leak the screenshot;
- conversation deletion removes its image and leaves another conversation's image;
- a deletion error leaves the conversation visible;
- history reconstruction supplies a thumbnail for an image message and tolerates a corrupt image with an explicit unavailable marker.

- [ ] **Step 2: Write failing runtime-construction test**

Extend `test_build_chat_runtime_shows_chat_window_with_single_assistant_worker` to assert:

```python
assert runtime.controller._screenshot_store._root == tmp_path / "chat-images"
assert runtime.context_builder._screenshot_store is runtime.controller._screenshot_store
```

Expected behavior uses the database parent; no new configuration setting is introduced.

- [ ] **Step 3: Run focused tests and confirm constructor/signal failures**

```powershell
.\.venv\python.exe -B -m pytest tests/test_chat_controller.py tests/test_app.py -q
```

Expected: FAIL because the controller and runtime do not accept a screenshot store.

- [ ] **Step 4: Implement focused controller orchestration**

Change the constructor to:

```python
def __init__(
    self,
    window,
    repository,
    context_builder,
    screenshot_store,
    assistant,
    assistant_executor,
):
```

Connect `window.send_image_requested` to:

```python
@Slot(str, object)
def send_image_message(self, text: str, draft: ScreenshotDraft) -> None:
    conversation_id = self._window.active_conversation_id
    if conversation_id is None or self._shutting_down:
        return
    request_id = uuid4().hex
    message = self._repository.append_user_message(
        conversation_id,
        text.strip() or "聊天截图",
        request_id=request_id,
        kind="image",
    )
    try:
        self._screenshot_store.save(
            conversation_id, message.id, draft.data, draft.mime_type,
            draft.width, draft.height,
        )
    except Exception:
        self._repository.delete_pending_user_request(conversation_id, request_id)
        QMessageBox.warning(self._window, "截图发送失败", "截图未能安全保存")
        return
    self._show_if_active(conversation_id)
    self._dispatch_request(conversation_id, request_id, message.body)
```

In `_dispatch_request`, build with the actual request owner:

```python
context = self._context_builder.build(
    conversation_id, request_message_id=request.message_id
)
```

In `show_conversation`, load each message's optional screenshot, decode it with `QImage.fromData`, and pass it through `ChatTurnView.image`. If bytes are missing/corrupt, keep the text turn and append `（截图无法读取）`; do not crash the conversation.

Before repository deletion:

```python
try:
    self._screenshot_store.remove_for_conversation(conversation_id)
except (OSError, ScreenshotCorrupt):
    QMessageBox.warning(self._window, "删除失败", "截图文件未能删除，会话已保留")
    return
self._repository.delete_conversation(conversation_id)
```

- [ ] **Step 5: Wire one store into the application runtime**

In `build_chat_runtime`:

```python
cipher = DataCipher.open(settings.chat.database_path.with_suffix(".key"))
repository = ConversationRepository(settings.chat.database_path, cipher)
screenshot_store = ScreenshotStore(
    settings.chat.database_path.parent / "chat-images",
    repository,
    cipher,
)
context_builder = ContextBuilder(
    repository,
    screenshot_store,
    character_budget=settings.chat.context_character_budget,
)
controller = ChatController(
    window,
    repository,
    context_builder,
    screenshot_store,
    assistant,
    assistant_executor,
)
```

Do not add a configuration field or second executor.

- [ ] **Step 6: Run controller/runtime regressions**

```powershell
.\.venv\python.exe -B -m pytest tests/test_chat_controller.py tests/test_chat_shell.py tests/test_app.py tests/test_chat_context.py -q
```

Expected: PASS; requests remain idempotent, background results stay with their owner conversation, and shutdown still closes the single worker.

- [ ] **Step 7: Commit the integrated chat flow**

```powershell
git add -- src/lexiaodu/chat_controller.py src/lexiaodu/app.py tests/test_chat_controller.py tests/test_app.py
git commit -m "feat: integrate screenshot chat flow"
```

---

### Task 5: Documentation, Full Verification, and Handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/MANUAL_TEST_CHECKLIST.md`
- Modify: `HANDOFF.md`
- Review only: `.env.example`, `pyproject.toml`

**Interfaces:**
- Consumes: completed screenshot feature from Tasks 1-4.
- Produces: current privacy/configuration instructions, reproducible manual checks, verified clean repository state, and final GitHub `main` update.

- [ ] **Step 1: Run the narrow complete feature suite**

```powershell
.\.venv\python.exe -B -m pytest tests/test_screenshot_store.py tests/test_chat_repository.py tests/test_chat_context.py tests/test_advisor_assistant.py tests/test_chat_shell.py tests/test_chat_controller.py tests/test_app.py -q
```

Expected: PASS. If any failure occurs, use `systematic-debugging` before changing implementation.

- [ ] **Step 2: Update user and privacy documentation**

Add to `README.md`:

- choose one PNG/JPG/JPEG/WebP from the composer;
- screenshots are encrypted under `data/chat-images`, sent to Ark as Base64, and removed with the conversation;
- long screenshots use `high` detail without local slicing;
- `ARK_MODEL` must support image understanding;
- no OCR, paste, multi-image, TOS, Files API, or image knowledge-base upload;
- only deidentified images may be used for testing.

Add manual cases to `docs/MANUAL_TEST_CHECKLIST.md` for personal long chat, three-person group chat, ambiguous identity, restart, retry, deletion, invalid/corrupt file, and a text-only regression. Do not include real parent data or screenshots in the repository.

Update `HANDOFF.md` to mark implementation state and list only commands actually run and unresolved live-Ark acceptance. Remove the “waiting for written spec review” line.

- [ ] **Step 3: Confirm dependencies and secrets did not expand**

Run:

```powershell
git diff -- pyproject.toml .env.example
git status --short
git ls-files data artifacts
```

Expected: no dependency or environment-variable changes; no screenshot, database, key, or generated artifact is tracked.

- [ ] **Step 4: Run the full automated suite**

```powershell
.\.venv\python.exe -B -m pytest -q
```

Expected: PASS. Record the actual count in the final response, but keep stale counts out of `HANDOFF.md`.

- [ ] **Step 5: Perform proportional UI and Ark acceptance**

Launch:

```powershell
.\.venv\python.exe -m lexiaodu
```

Using only synthetic or deidentified images, verify one personal long screenshot, one group long screenshot with at least three participants, and one ambiguous-identity group screenshot. Confirm the first two are readable in `high` mode and the last produces exactly one identity question without parent-ready copy. If a live Ark credential or safe image is unavailable, do not fabricate success; record the exact unverified cases in `HANDOFF.md` and the final response.

- [ ] **Step 6: Inspect the exact final diff and run completion verification**

```powershell
git diff --check
git status --short
git diff --stat
git diff
```

Verify every changed line maps to the approved feature, no source filename/private text appears, and no OCR/slicing abstraction or new dependency was added. Invoke `verification-before-completion` before claiming success.

- [ ] **Step 7: Commit documentation and push `main`**

```powershell
git add -- README.md docs/MANUAL_TEST_CHECKLIST.md HANDOFF.md
git commit -m "docs: document screenshot vision workflow"
git push origin main
```

If a normal push is rejected or the branch is no longer safely aligned with `origin/main`, stop and report the exact reason; never force-push.
