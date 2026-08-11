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

### PDF、DOCX、PPTX、XLSX

1. 通过方舟知识库 `list_docs` 获取已解析完成的四类云端文档，不扫描本地 `company_documents/`。
2. 将云端 `doc_id` 和文件名交给豆包，自动选择最多三份相关文档。
3. 使用新版 `search_knowledge`，把所有选中文档的 `doc_id` 放入同一次请求以限定检索范围，避免逐文档调用触发标准版 QPS 限制。
4. 将方舟解析和检索的内容连同原文件名交给 Responses API 生成最终回答。

四类原文件及解析结果长期保存在方舟知识库。应用运行时只读知识库，不上传、更新或删除云端文档，不使用方舟 Files API，也不需要本地原文档副本、`TOS_BUCKET` 或 `TOS_ENDPOINT`。

### 明确不包含

- 顾问端手动上传按钮。
- 本地 OCR、Office/PDF 正文提取、文本切段或本地知识库重建。
- 已删除的截图、附件、回复卡、反馈、旧风险模块和旧知识导入入口。

## 3. 云端与本地文件现状

- 本地 PDF、DOCX、PPTX、XLSX 已不参与候选发现、AI 路由或知识检索；现有本地文件不会被应用读取、修改或删除。
- 云端文档必须处于解析成功状态，且文件名保留支持的扩展名，才会进入候选列表。
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
- `src/lexiaodu/advisor_assistant.py`：云端文档选择、知识库证据与最终回答。
- `src/lexiaodu/office_documents.py`：四类云端文档发现、状态过滤及限定 `doc_id` 的知识检索。
- `src/lexiaodu/chat_controller.py`：会话交互与异步回答。
- `src/lexiaodu/chat_repository.py`：加密会话和消息存储。
- `src/lexiaodu/chat_context.py`：单会话上下文构建与裁剪。
- `src/lexiaodu/chat_window.py`：桌面聊天界面。
- `tests/test_office_documents.py`、`tests/test_advisor_assistant.py`、`tests/test_app.py`：云端文档与运行时主要验证。

## 6. 已验证事实

- Office 长期知识库读取实现基线：`e82f309 feat: read persistent Office documents from Ark`。
- 本次实现将 PDF 与 Office 统一为只读知识库路径；本地副本与方舟 Files API 已退出运行时文档流程。
- 2026-08-11 通过当前应用适配器只读列出 92 份已解析候选：PDF 9、DOCX 51、PPTX 7、XLSX 25。
- 同日使用每类一份文档执行一次多 `doc_id` 合并检索，成功返回 25190 个字符，四个来源文件名均出现在证据中。
- 逐文档连续检索曾在第二个请求复现方舟 `1000029` QPS 限流；合并为一次检索后真实调用通过。
- 当前全量自动化测试为 53 项通过。
- 方舟控制台的知识问答能够依据当前知识库回答二年级数学课程问题。

## 7. 完成检查

- 改动严格对应当前任务，没有恢复旧功能或顺手重构无关代码。
- PDF、DOCX、PPTX、XLSX 保持统一的只读知识库流程，除非用户明确改变范围。
- 未删除或改写公司文档、聊天数据、密钥及云端知识库文档。
- 运行与风险相匹配的最小测试；完成前至少执行 `git diff --check`。
- 更新 `README.md` 和本文件中的当前状态，删除已经失效的描述，不追加过程流水账。
- 提交 `main`，推送 GitHub，并确认 `HEAD` 与 `origin/main` 一致。

历史批次、旧 OCR/本地知识库和已删除功能的详细记录不再保留在当前交接中；需要追溯时查阅 Git 历史。
