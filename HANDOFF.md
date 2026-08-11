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
- 正式运行配置不读取 `TOS_BUCKET`、`TOS_ENDPOINT`，不构造 TOS 客户端，也不扫描、创建或要求 `company_documents/`。
- `VOLC_ACCESSKEY`、`VOLC_SECRETKEY` 只传给 `VikingKnowledgeBaseService`，用于知识库 API 的 AK/SK 鉴权。

## 7. 后续维护边界

- PDF、DOCX、PPTX、XLSX 继续使用统一的只读知识库流程；多文档保持单次 `search_knowledge`。
- 不为应用增加 TOS 或项目内原文档副本依赖，不恢复 Files API 上传、本地 OCR、正文提取、文本切段或知识库重建。
- 不操作 TOS 桶、独立备份、云端知识库文档、聊天数据、`.env` 或 `data/chat.key`。
- 排障时继续区分目录读取、解析状态、检索空结果、方舟调用异常和 Responses 超时。
- 历史批次、旧 OCR/本地知识库和已删除功能的详细记录需要追溯时查阅 Git 历史。
