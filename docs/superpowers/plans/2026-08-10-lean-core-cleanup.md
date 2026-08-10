# 乐小读精简核心版实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除旧知识库/OCR/截图附件/回复卡流程，把乐小读收敛为独立加密聊天、豆包自动选原文档和 PDF 原件直传的精简核心版。

**Architecture:** 默认启动只装配 `ChatMainWindow`、`ChatController`、`ConversationRepository`、`ContextBuilder` 和 `OpenAIConversationAssistant`。会话库只保留会话、消息和请求恢复；上下文按当前会话的时间顺序携带角色标签并按字符预算裁剪。旧功能通过数据库幂等迁移和本机精确目录清理移除。

**Tech Stack:** Python 3.11、PySide6、SQLite、cryptography/DPAPI、OpenAI 兼容方舟 API、pytest。

## Global Constraints

- 保留 `company_documents/` 中的公司原文档、`data/chat.sqlite3` 中的会话和消息以及 `data/chat.key`。
- 删除旧截图消息、附件/OCR/回复卡/反馈数据和对应代码，不恢复本地知识库流程。
- 默认运行路径不得导入 PaddleOCR、pypdf 或旧知识模块。
- 应用不直接给家长发送消息；公司事实无原文依据时必须说明待核实。
- 所有数据迁移必须可重复执行。

---

### Task 1: 收窄启动和依赖

**Files:**
- Modify: `src/lexiaodu/app.py`
- Modify: `src/lexiaodu/config.py`
- Modify: `config/app.toml`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Test: `tests/test_app.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `build_chat_runtime(settings: AppSettings, assistant: ConversationAssistant) -> ChatRuntime`，其中运行时不再包含附件或 OCR 服务。

- [ ] **Step 1: 写失败测试**

```python
def test_default_parser_has_no_legacy_knowledge_or_ocr_actions():
    help_text = build_parser().format_help()
    assert "knowledge" not in help_text.casefold()
    assert "ocr" not in help_text.casefold()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\python.exe -m pytest tests\test_app.py tests\test_config.py -q`
Expected: FAIL，因为旧知识命令和配置仍存在。

- [ ] **Step 3: 最小实现**

删除旧 CLI、旧生成器、知识导入和 OCR 装配；`AppSettings` 只保留应用和聊天设置；依赖只保留 `cryptography`、`openai`、`PySide6`、`python-dotenv`，开发依赖只保留 `pytest`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\python.exe -m pytest tests\test_app.py tests\test_config.py -q`
Expected: PASS。

### Task 2: 精简会话数据和上下文

**Files:**
- Modify: `src/lexiaodu/conversations.py`
- Modify: `src/lexiaodu/context.py`
- Delete: `src/lexiaodu/attachments.py`
- Modify: `tests/test_conversations.py`
- Modify: `tests/test_context.py`
- Modify: `tests/test_chat_recovery_acceptance.py`
- Delete: `tests/test_attachments.py`

**Interfaces:**
- Produces: `ContextPackage(messages: tuple[Message, ...], context_version: int)`。
- Produces: `ContextBuilder.build(conversation_id: str) -> ContextPackage`。

- [ ] **Step 1: 写失败测试**

```python
def test_context_keeps_roles_and_drops_oldest_messages_to_fit_budget():
    package = builder.build(conversation.id)
    assert "顾问：" in package.render_for_model()
    assert "乐小读：" in package.render_for_model()
    assert "另一个会话的标记" not in package.render_for_model()
```

另加迁移测试：旧 `kind='screenshot'` 消息和附件/回复卡表被删除，但普通会话消息保留。

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\python.exe -m pytest tests\test_conversations.py tests\test_context.py tests\test_chat_recovery_acceptance.py -q`
Expected: FAIL，因为当前上下文无角色且仍携带附件/回复卡。

- [ ] **Step 3: 最小实现**

保留会话、消息和请求状态；移除附件、摘要、确认事实、回复卡接口。初始化数据库时按子表到父表顺序删除旧表并删除 `kind='screenshot'` 消息。上下文从当前会话消息末尾向前选取，超预算时只丢最早消息。

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\python.exe -m pytest tests\test_conversations.py tests\test_context.py tests\test_chat_recovery_acceptance.py -q`
Expected: PASS。

### Task 3: 删除失效界面和旧业务模块

**Files:**
- Modify: `src/lexiaodu/chat_window.py`
- Modify: `src/lexiaodu/chat_controller.py`
- Modify: `src/lexiaodu/advisor_assistant.py`
- Delete: `src/lexiaodu/advice.py`
- Delete: `src/lexiaodu/chat.py`
- Delete: `src/lexiaodu/demo_data.py`
- Delete: `src/lexiaodu/document_catalog.py`
- Delete: `src/lexiaodu/document_router.py`
- Delete: `src/lexiaodu/domain.py`
- Delete: `src/lexiaodu/feedback.py`
- Delete: `src/lexiaodu/generator.py`
- Delete: `src/lexiaodu/knowledge.py`
- Delete: `src/lexiaodu/knowledge_import.py`
- Delete: `src/lexiaodu/knowledge_semantics.py`
- Delete: `src/lexiaodu/ocr.py`
- Delete: `src/lexiaodu/policy_upgrade.py`
- Delete: `src/lexiaodu/policy_upgrade_service.py`
- Delete: `src/lexiaodu/risk.py`
- Delete: 对应测试、`scripts/evaluate_advisor_knowledge.py`、`scripts/verify_day5_queries.py`

**Interfaces:**
- Consumes: `ContextPackage.render_for_model() -> str`。
- Produces: 只含有效聊天控件的 `ChatMainWindow`。

- [ ] **Step 1: 写失败测试**

```python
def test_window_contains_only_active_chat_actions():
    window = ChatMainWindow()
    assert window.windowTitle().startswith("乐小读")
    assert window.findChild(QPushButton, "generateReply") is None
    assert window.findChild(QPushButton, "openContextDrawer") is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\python.exe -m pytest tests\test_chat_window.py tests\test_chat_controller.py tests\test_advisor_assistant.py -q`
Expected: FAIL，因为失效按钮、抽屉和旧恢复逻辑仍存在。

- [ ] **Step 3: 最小实现**

删除失效信号、控件和模块；控制器仅管理会话与助手请求。系统提示加入公司事实来源、实时业务查询和高风险人工核实边界，并要求引用文件名。

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\python.exe -m pytest tests\test_chat_window.py tests\test_chat_controller.py tests\test_advisor_assistant.py -q`
Expected: PASS。

### Task 4: 清理本机产物、重建环境并交接

**Files:**
- Modify: `README.md`
- Modify: `HANDOFF.md`
- Delete: `artifacts/`
- Delete: `data/chat-attachments/`
- Delete: `data/feedback.sqlite3`
- Recreate: `.venv/`

**Interfaces:**
- Produces: 可通过 `.\.venv\python.exe -m lexiaodu` 启动的精简环境。

- [ ] **Step 1: 更新说明**

README 和 HANDOFF 只描述当前独立聊天、原文档目录、PDF 直传、Office 待接方舟知识库以及已删除旧流程。

- [ ] **Step 2: 精确清理数据**

停止当前乐小读进程；确认路径位于项目目录后删除旧附件、反馈库、生成产物和外层 pytest 临时目录，不删除 `company_documents/`、`chat.sqlite3`、`chat.key`。

- [ ] **Step 3: 重建虚拟环境**

使用 Python 3.11 新建干净 `.venv` 并安装 `-e .[dev]`，确保 Paddle/OCR/OpenCV/pypdf 不在依赖列表。

- [ ] **Step 4: 最终验证**

Run: `.\.venv\python.exe -m pytest -q`
Expected: 全部通过。

Run: `.\.venv\python.exe -m pip check`
Expected: `No broken requirements found.`

Run: `.\.venv\python.exe -m compileall -q src`
Expected: exit 0。

最后启动应用，确认进程保持运行，并把实际测试结果、环境体积和剩余 Office 接入限制写入 `HANDOFF.md`。
