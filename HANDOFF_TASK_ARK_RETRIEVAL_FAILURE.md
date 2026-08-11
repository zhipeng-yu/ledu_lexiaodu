# 新任务交接：云端文档存在但乐小读仍报 Office 读取失败

更新时间：2026-08-11

## 本任务要处理的问题

方舟知识库文档已经处理完成，方舟控制台内置的“知识问答”可以正常回答，但乐小读仍可能显示：

`方舟读取 Office 原文档失败：《26一升二年级数学 夏秋产品说明.docx、小学2026夏秋【美化版大纲】.xlsx》，因此本次不能依据该文档回答公司事实。`

本交接只记录复现事实、已有证据和验收边界，不包含解决方案或技术实现建议。

## 必须区分的两类失败

### A. 云端文档确实不存在

另一次失败明确显示：

`方舟知识库中未找到同名 Office 原文档《26夏秋小学数学产品说明-26.4.docx》`

该文件当时存在于本地 `company_documents/`，但不在方舟知识库文档列表中。用户计划后续把本地文件全部导入云端。本任务不要把这类明确缺失与下面的异常混为一谈。

### B. 云端文档存在且处理完成，仍出现通用失败

方舟控制台和只读 API 查询均确认以下文档存在：

- `小学2026夏秋【美化版大纲】.xlsx`
  - `doc_id`: `office_d777424fe7794a179bb6abf478b292b4`
  - `status`: `{"process_status": 0}`
- `26一升二年级数学 夏秋产品说明.docx`
  - `doc_id`: `office_1ae9f22bb69842308c6527c3a12e5ed5`
  - `status`: `{"process_status": 0}`

方舟控制台的知识问答能依据知识库回答二年级数学课程大纲问题。

## 已完成的只读验证

- 使用当前 `.env` 和当前 `main` 代码调用 `collection.list_docs(project="default")`，成功返回 3 份文档，以上两份名称、`doc_id` 和处理状态正常。
- 使用 `ArkOfficeDocumentReader.retrieve()` 对以上两份本地同名文件执行查询 `二年级数学课程大纲`，调用成功。
- 成功结果长度为 3995 个字符，包含 DOCX 表格解析内容。
- 因此已确认：这两份文件不是因为缺失、文件名不匹配、未解析完成或固定权限配置错误而必然失败。

## 当前错误信息局限

- `src/lexiaodu/office_documents.py` 对未被识别为 `OfficeDocumentError` 的异常统一包装为：
  - `方舟读取 Office 原文档失败：《文件名》`
- 发生失败时，原始异常只保留在 Python 异常链中，没有写入界面消息或持久日志。
- 截图和聊天数据库中只保存了包装后的通用提示，无法从已有记录还原第一次失败的具体异常类型、错误码和请求阶段。

## 当前相关代码

- `src/lexiaodu/advisor_assistant.py`
  - 本地文档发现与 AI 文件选择。
  - 调用 Office reader，并把 `OfficeDocumentError` 转换为顾问可见提示。
- `src/lexiaodu/office_documents.py`
  - `list_docs` 同名匹配。
  - 检查 `process_status`。
  - 通过 `search_knowledge` 按 `doc_id` 检索。
  - 通用异常包装。
- `src/lexiaodu/app.py`
  - 方舟知识库服务、项目和集合的运行时配置。
- `tests/test_office_documents.py`
- `tests/test_advisor_assistant.py`

## 当前仓库状态

- 项目目录：`E:\Project\ledu_project\lexiaodu`
- 分支：`main`
- 当前已推送提交：`e82f309cb798d3aaa669ac1ff6535dfca5c760e9`
- 提交说明：`feat: read persistent Office documents from Ark`
- 该提交全量测试：52 项通过。
- 用户已明确将此问题拆成独立新任务；本次交接未修改相关功能代码。

## 新任务验收边界

- 复现对象必须是方舟知识库中同名、存在且处理完成的文档。
- 必须区分文档缺失、解析未完成、知识检索无结果和方舟调用异常，不得继续把不同失败统一当作“文件不存在”。
- 结论必须基于乐小读实际调用链的证据，不能只以方舟网页知识问答成功或失败代替应用侧验证。
- 修复后应由乐小读对上述两份已处理完成文档完成一次实际回答验证。
- 不上传、删除或改写用户的公司原文档和方舟知识库文档。

