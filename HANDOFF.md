# 乐小读项目交接

更新时间：2026-08-14

## 当前架构

乐小读是面向公司顾问的 PySide6 独立聊天应用。每个会话独立、在本机加密保存；豆包负责判断是否需要公司资料、向顾问追问或给出回复建议，最终内容由顾问确认后自行发送给家长。

知识链路只读方舟知识库中解析成功的 PDF、DOCX、PPTX 和 XLSX。豆包最多选择三份云端文档，所有选中的 `doc_id` 必须放在同一次 `search_knowledge` 请求中。公司事实只能来自检索证据；实时名额、订单、付款和 App 状态仍需查询业务系统。

关键代码：

- `advisor_assistant.py`：文档路由、知识证据、角色提示、结构化回答和截图 Base64 请求。
- `office_documents.py`：云端文档发现、状态过滤和统一知识检索。
- `chat_repository.py`、`chat_context.py`、`chat_controller.py`、`chat_window.py`、`screenshot_store.py`：加密会话、上下文、单图发送、异步请求和界面。
- `app.py`：运行时装配。

## 有效约束

- 当前用户是公司顾问，家长是服务对象；顾问不是授课老师、班主任或课堂管理者。
- 信息不足时向顾问追问；信息充分时输出“给顾问的建议”和“可直接发给家长”。
- 一条消息最多选择一张 PNG/JPG/JPEG/WebP；截图加密存于 `data/chat-images`，以 `high` 细节的 Base64 HTTPS 请求发送到支持图片理解的 `ARK_MODEL`。
- 不支持 OCR、粘贴、多图、本地切片、TOS、方舟 Files API 或图片知识库上传。
- 不操作或输出公司原文档、独立备份、云端知识库内容、真实聊天数据、`.env` 或 `data/chat.key`。
- 删除 `data/chat.key` 会导致既有加密会话无法读取。
- 知识检索链路当前正常；截图任务不得顺带重构文档发现、选择、统一检索或超时策略。

## 当前已验证状态

- 单图截图的选择、加密保存、重启恢复、删除、上下文传递和时间线缩略图已完成；长图使用 `high` 细节，不做本地切片。
- 自动化验证实际运行：`$env:PYTHONPATH=(Resolve-Path -LiteralPath 'src').Path; & 'E:\Project\ledu_project\lexiaodu\.venv\python.exe' -B -m pytest tests/test_screenshot_store.py tests/test_chat_repository.py tests/test_chat_context.py tests/test_advisor_assistant.py tests/test_chat_shell.py tests/test_chat_controller.py tests/test_app.py -q`。
- 自动化验证实际运行：`$env:PYTHONPATH=(Resolve-Path -LiteralPath 'src').Path; & 'E:\Project\ledu_project\lexiaodu\.venv\python.exe' -B -m pytest -q`；在 `LEXIAODU_GENERATOR=simulated` 和 `QT_QPA_PLATFORM=offscreen` 下启动 `python -m lexiaodu` 的进程保持运行。

## 仍未解决

- 未配置可用的 `ARK_API_KEY` 和 `ARK_MODEL`，因此尚未进行真实方舟 UI 验收：个人长截图、至少三人群聊长截图，以及身份不明群聊截图。前两项需确认 `high` 细节可读；最后一项需确认只出现一个身份问题且无家长话术。
