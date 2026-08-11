# 乐小读项目交接

更新时间：2026-08-11

## 1. 交接入口

- 项目目录：`E:\Project\ledu_project\lexiaodu`
- 仓库：`https://github.com/zhipeng-yu/ledu_lexiaodu.git`
- 分支：`main`
- 最新提交以 `git log -1` 为准；开始工作前确认本地 `main` 与 `origin/main` 一致。
- 新任务先完整阅读根目录 `README.md` 和本文件。

## 2. 当前产品状态

乐小读是面向公司顾问的独立 AI 会话应用。会话及消息按会话隔离并在本地加密保存。顾问直接提问，AI 自动选择最多三份相关公司原文档；界面没有手动上传入口。

### PDF

1. 从本地 `company_documents/` 发现并选择 PDF。
2. 按原始字节临时上传方舟 Files API。
3. 通过 Responses API 参与回答。
4. 回答完成后尝试删除方舟临时文件。

### DOCX、PPTX、XLSX

1. 从本地 `company_documents/` 发现候选文件并让 AI 选择。
2. 按本地文件名在方舟知识库查找同名且解析完成的文档。
3. 使用新版 `search_knowledge`，按 `doc_id` 限定检索范围。
4. 检索内容连同原文件名进入豆包回答。

Office 原文件及解析结果长期保存在方舟知识库。应用运行时只读知识库，不上传或删除 Office 云端文档，也不再需要 `TOS_BUCKET`、`TOS_ENDPOINT`。

### 明确不包含

- 顾问端手动上传按钮。
- 本地 OCR、Office/PDF 正文提取、文本切段或本地知识库重建。
- 已删除的截图、附件、回复卡、反馈、旧风险模块和旧知识导入入口。

## 3. 云端与本地文件现状

- 当前本地 Office 文件仍有作用：文件名和相对路径用于候选发现、AI 路由及云端同名匹配。现在直接删除本地 Office 文件，会导致对应云端文档不再被选中。
- 当前 PDF 完全依赖本地原文件，不能删除。
- 方舟知识库控制台支持本地上传、TOS 导入和公开链接导入。本地上传不强制使用 TOS；文件很多时官方建议使用 TOS 批量导入。
- 方舟官方依据：
  - `https://www.volcengine.com/docs/82379/1261883?lang=zh`
  - `https://www.volcengine.com/docs/82379/1528458?lang=zh`

## 4. 启动与配置

启动：

```powershell
.\.venv\python.exe -m lexiaodu
```

正式模式主要环境变量：

```dotenv
LEXIAODU_GENERATOR=doubao
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=模型名称
ARK_API_KEY=模型推理APIKey
VOLC_ACCESSKEY=火山引擎AccessKey
VOLC_SECRETKEY=火山引擎SecretKey
VOLC_REGION=cn-beijing
ARK_KB_COLLECTION=知识库名称
ARK_KB_PROJECT=default
ARK_KB_HOST=api-knowledgebase.mlp.cn-beijing.volces.com
```

`.env`、`company_documents/`、`data/` 均包含本机或公司数据，不得提交或输出其中的真实内容。不要删除 `data/chat.key`，否则既有加密聊天记录无法读取。

## 5. 关键代码

- `src/lexiaodu/app.py`：启动、豆包与方舟知识库配置。
- `src/lexiaodu/advisor_assistant.py`：本地文档发现、AI 文件选择、PDF 流程及最终回答。
- `src/lexiaodu/office_documents.py`：Office 同名匹配、状态检查、限定 `doc_id` 的知识检索。
- `src/lexiaodu/chat_controller.py`：会话交互与异步回答。
- `src/lexiaodu/chat_repository.py`：加密会话和消息存储。
- `src/lexiaodu/chat_context.py`：单会话上下文构建与裁剪。
- `src/lexiaodu/chat_window.py`：桌面聊天界面。
- `tests/test_office_documents.py`、`tests/test_advisor_assistant.py`、`tests/test_app.py`：Office 与运行时主要验证。

## 6. 已验证事实

- Office 长期知识库读取实现基线：`e82f309 feat: read persistent Office documents from Ark`。
- 基线全量测试：52 项通过。
- 方舟 API 能列出以下两份同名文档，状态均为 `process_status=0`：
  - `26一升二年级数学 夏秋产品说明.docx`：`office_1ae9f22bb69842308c6527c3a12e5ed5`
  - `小学2026夏秋【美化版大纲】.xlsx`：`office_d777424fe7794a179bb6abf478b292b4`
- 直接调用 `ArkOfficeDocumentReader.retrieve()` 检索上述两份文件曾成功返回 3995 个字符，包含 DOCX 表格内容。
- 方舟控制台的知识问答能够依据当前知识库回答二年级数学课程问题。

## 7. 已知问题

### 7.1 云端缺少同名文件

本地文件 `26夏秋小学数学产品说明-26.4.docx` 曾被 AI 选中，但当时云端知识库没有同名文档，因此应用明确提示“未找到同名 Office 原文档”。这与下面的异常不是同一问题。

### 7.2 云端文档正常但应用仍偶发通用失败

上述两份 `process_status=0` 的文档在乐小读实际会话中仍出现过：

`方舟读取 Office 原文档失败：《26一升二年级数学 夏秋产品说明.docx、小学2026夏秋【美化版大纲】.xlsx》`

当前代码把非 `OfficeDocumentError` 异常统一包装成通用提示，聊天记录没有保存底层异常类型、错误码或具体失败阶段，因此已有截图不能还原精确原因。

## 8. 待办任务提示词

### 任务一：Office 改为只依赖云端文档

> 请先完整阅读项目根目录 `README.md` 和 `HANDOFF.md`。唯一任务：公司 Office 文档全部导入方舟知识库后，使乐小读在本地没有 DOCX、PPTX、XLSX 副本时，仍能从方舟知识库自动选择相关文档并参与回答。保持 PDF 流程不变；不增加上传按钮；不做本地 OCR、正文提取、切段或知识库重建；不恢复旧功能；不删除本地文件、聊天数据或云端文档。先核对当前代码和方舟正式接口，再实施、做必要验证、更新 `README.md` 与 `HANDOFF.md`，提交 `main` 并推送 GitHub。

### 任务二：定位并修复云端文档读取失败

> 请先完整阅读项目根目录 `README.md` 和 `HANDOFF.md`。唯一任务：查清并修复“方舟知识库中文档同名、存在且 `process_status=0`，控制台知识问答正常，但乐小读实际会话仍显示 Office 读取失败”的问题。必须基于乐小读实际调用链取得证据，区分文档缺失、解析未完成、检索无结果和方舟调用异常；不猜测原因；不改动或删除公司文件和云端文档；不改变 PDF 流程；只做必要的小范围验证。完成后使用第 6 节两份文档进行一次乐小读真实会话验证，更新 `README.md` 与 `HANDOFF.md`，提交 `main` 并推送 GitHub。

## 9. 完成检查

- 改动严格对应当前任务，没有恢复旧功能或顺手重构无关代码。
- PDF 流程保持不变，除非用户明确改变范围。
- 未删除或改写公司文档、聊天数据、密钥及云端知识库文档。
- 运行与风险相匹配的最小测试；完成前至少执行 `git diff --check`。
- 更新 `README.md` 和本文件中的当前状态，删除已经失效的描述，不追加过程流水账。
- 提交 `main`，推送 GitHub，并确认 `HEAD` 与 `origin/main` 一致。

历史批次、旧 OCR/本地知识库和已删除功能的详细记录不再保留在当前交接中；需要追溯时查阅 Git 历史。
