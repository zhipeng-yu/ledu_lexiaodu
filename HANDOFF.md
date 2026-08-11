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

- 项目内 `company_documents/` 已在确认独立备份、云端清单和无本地副本运行结果后删除；不要为应用运行重新创建或回填该目录。
- 公司原文件另有可恢复的独立备份。以后由管理员从该备份直接本地上传方舟知识库，不再把 TOS 作为本项目的导入流程。
- TOS 桶由用户自行处理；后续代码任务不得操作、删除或假设该桶存在。
- 云端文档必须处于解析成功状态，且文件名保留支持的扩展名，才会进入候选列表。
- 方舟知识库控制台仍支持多种导入方式，但本项目已明确选择“本地上传”。
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

`.env`、`data/` 和独立原文件备份均包含本机或公司数据，不得提交或输出其中的真实内容。项目内 `company_documents/` 当前不存在。不要删除 `data/chat.key`，否则既有加密聊天记录无法读取。

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
- 本次故障涉及的两份文档仍可由 Ark `GetDoc` 和目录接口读取，状态均为 `process_status=0`：
  - `26一升二年级数学 夏秋产品说明.docx`：`office_1ae9f22bb69842308c6527c3a12e5ed5`
  - `小学2026夏秋【美化版大纲】.xlsx`：`office_d777424fe7794a179bb6abf478b292b4`
- 对上述两个 `doc_id` 的单独检索分别返回 10 条和 4 条结果，因此目标文档缺失、解析未完成和检索无结果均已排除；旧通用读取失败对应方舟调用异常 `1000029`。
- 合并检索后首次真实会话在检索完成后复现另一独立故障：最终 Responses API 在客户端 30 秒默认超时下抛出 `APITimeoutError -> ReadTimeout -> TimeoutError`。纯 Office 文档回答现对该次请求使用 120 秒超时；包含 PDF 的请求行为不变。
- 修复后的真实乐小读会话精确选中上述两个 `doc_id`，只发起一次合并检索，返回 20 条结果（18 条正文非空）；用户请求与助手回复均保存为 `completed`，回复为 544 个字符且包含两份来源文件名。
- 当前全量自动化测试为 54 项通过。
- 方舟控制台的知识问答能够依据当前知识库回答二年级数学课程问题。
- 运营决策：以后从独立备份直接本地上传知识库；TOS 桶由用户自行处理，不纳入乐小读代码或交接任务。

## 7. 下一任务的新窗口提示词

```text
请先完整阅读项目根目录 README.md 和 HANDOFF.md，并检查 git status、main 与 origin/main 是否一致。

唯一任务：检查并完成乐小读代码侧“彻底不依赖 TOS 和项目内原文档副本，管理员以后从独立备份直接本地上传方舟知识库”的必要收尾。先核对当前代码、配置、测试和方舟官方正式接口，再决定是否确有代码需要修改；如果当前运行时代码已经满足，不要为了产生改动而重构。

已确认事实：
- 项目内 company_documents/ 已删除，且已有独立可恢复备份；不要重建或回填该目录。
- PDF、DOCX、PPTX、XLSX 已全部改为从方舟知识库 list_docs 发现，按云端 doc_id 自动选择并通过一次 search_knowledge 合并检索。
- 应用不使用方舟 Files API，不上传、更新或删除知识库文档。
- TOS 桶由用户自行处理；本任务不得查看、修改或删除 TOS 桶及其中对象。
- 以后由管理员从独立备份直接在方舟控制台本地上传文档。
- VOLC_ACCESSKEY 和 VOLC_SECRETKEY 是方舟知识库 API 的 AK/SK，仍然需要；不要因为名称含 VOLC 就误删。
- 纯 Office 最终 Responses 请求已有 120 秒超时处理；包含 PDF 的行为保持当前实现。

严格范围：
- 只处理与 TOS/本地副本依赖直接相关的必要代码、配置、测试和当前文档残留。
- 不增加上传按钮，不让应用自动上传文档。
- 不做本地 OCR、正文提取、文本切段或知识库重建。
- 不恢复旧 Files API、附件、截图、反馈、旧风险模块或旧知识导入功能。
- 不删除或改写聊天数据、data/chat.key、.env、独立备份、云端知识库文档或 TOS 数据。
- 保持多文档单次 search_knowledge，避免 1000029 QPS 限流。
- 保留现有真实故障区分：目录读取、解析状态、检索空结果、方舟调用异常和 Responses 超时不能混为一类。

成功标准：
1. 运行时代码与正式配置不依赖 TOS bucket/endpoint/client，也不扫描、创建或要求 company_documents/。
2. 四种文档在本地无副本、无 TOS 应用配置时仍可从知识库自动选择并回答。
3. VOLC_ACCESSKEY/VOLC_SECRETKEY 继续仅用于知识库 API 鉴权。
4. 用 TDD 做实际行为变化；先跑聚焦测试，再跑与风险相称的完整测试和 git diff --check。
5. 更新 README.md 和 HANDOFF.md，只保留当前事实，不写过程流水账。
6. 完成后提交 main、推送 GitHub，并确认 HEAD、origin/main 与远端 main 一致。
```

## 8. 完成检查

- 改动严格对应当前任务，没有恢复旧功能或顺手重构无关代码。
- PDF、DOCX、PPTX、XLSX 保持统一的只读知识库流程，除非用户明确改变范围。
- 未删除或改写公司文档、聊天数据、密钥及云端知识库文档。
- 运行与风险相匹配的最小测试；完成前至少执行 `git diff --check`。
- 更新 `README.md` 和本文件中的当前状态，删除已经失效的描述，不追加过程流水账。
- 提交 `main`，推送 GitHub，并确认 `HEAD` 与 `origin/main` 一致。

历史批次、旧 OCR/本地知识库和已删除功能的详细记录不再保留在当前交接中；需要追溯时查阅 Git 历史。
