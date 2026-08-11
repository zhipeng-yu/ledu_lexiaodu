# 乐小读

乐小读是面向公司顾问的独立 AI 对话应用。顾问描述家长顾虑后，豆包结合当前会话自行分析；需要公司资料时，系统会从方舟知识库中自动选择相关文件，不需要顾问手动上传，也不依赖本地原文档副本。

## 当前工作流程

1. 管理员将 PDF、DOCX、PPTX、XLSX 公司原文档导入方舟非结构化知识库，并等待解析成功。
2. 启动乐小读并新建或选择一个会话。
3. 顾问直接描述家长顾虑或追问问题。
4. 应用读取知识库中已解析完成的四类文档，豆包根据当前会话和云端文件名自动选择最多三份相关原文档。
5. 应用把选中文档的 `doc_id` 合并为一次方舟检索，并将检索证据交给豆包回答。

每个会话拥有独立上下文。AI 可以自行判断、追问和组织表达，但公司事实必须以原文档为依据。

## 当前支持范围

- 独立聊天窗口，以及会话的新建、选择、搜索、重命名和删除。
- 按会话保存上下文，明确区分“顾问”和“乐小读”。
- 本地加密保存会话与消息。
- 从方舟知识库自动发现已解析的 `PDF`、`DOCX`、`PPTX`、`XLSX` 原文档。
- 自动选择最多三份相关文件。
- 通过方舟知识库读取并使用 PDF、DOCX、PPTX、XLSX 的正文、表格和幻灯片内容。
- 无公司资料依据时明确提示待核实，不编造公司事实。
- 对课程名额、订单、付款和 App 显示等实时信息，要求查询业务系统。
- 对退款、投诉、法律、安全、健康、隐私和儿童保护事项，提示人工核实。

项目已经删除本地知识库、OCR、截图、附件、文本切段、回复卡、反馈收集和旧风险模块。

## 启动

当前电脑在项目根目录执行：

```powershell
.\.venv\python.exe -m lexiaodu
```

也可以指定配置文件：

```powershell
.\.venv\python.exe -m lexiaodu --config config\app.toml
```

## 方舟配置

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

在本机 `.env` 中填写：

```dotenv
LEXIAODU_GENERATOR=doubao
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=填写方舟模型名称
ARK_API_KEY=填写方舟模型推理APIKey
VOLC_ACCESSKEY=填写火山引擎AccessKey
VOLC_SECRETKEY=填写火山引擎SecretKey
VOLC_REGION=cn-beijing
ARK_KB_COLLECTION=填写非结构化知识库名称
ARK_KB_PROJECT=default
ARK_KB_HOST=api-knowledgebase.mlp.cn-beijing.volces.com
```

`.env` 已被 Git 忽略，不要提交、打印或发送真实密钥。

如只想检查聊天界面，可临时设置：

```dotenv
LEXIAODU_GENERATOR=simulated
```

模拟模式不会读取公司资料，也不会生成正式业务回答。

文档链路需要在华北区域开通方舟知识库，并完成一次人工导入：

1. 在方舟控制台进入“数据管理 → 知识库”，创建“非结构化数据”知识库；默认切片规则即可，记录知识库名称。
2. 将 PDF、DOCX、PPTX、XLSX 原文件直接上传知识库，或先上传到华北（北京）的私有 TOS 再选择“TOS 导入”；文件较多时官方建议使用 TOS 批量导入。
3. 等待每份文档处理成功，并在“切片详情”或“知识检索”中抽查解析和召回结果。
4. 创建具有该知识库读取和检索权限的访问密钥，把 AK/SK 只写入本机 `.env`。

知识库目前仅支持华北区域，并会产生知识库用量费用；使用 TOS 时还会产生 TOS 用量费用。应用只列出并检索知识库，不上传、更新或删除云端文档。文件更新时，请在控制台重新上传并导入，确保知识库中只保留一个有效版本。

方舟正式说明：[文档知识问答核心流程](https://www.volcengine.com/docs/82379/1261883?lang=zh)、[知识库插件功能说明](https://www.volcengine.com/docs/82379/1528458?lang=zh)。

## 维护公司原文档

公司原文档统一由管理员在方舟知识库中维护。文件名应清晰描述内容，因为豆包会参考云端文件名选择文档。应用只把 `process_status=0` 且扩展名为 PDF、DOCX、PPTX、XLSX 的文档作为候选，并使用方舟返回的 `doc_id` 在一次请求中限定所有选中文档的检索范围。

本地 `company_documents/` 即使存在也不会被应用扫描、读取或删除；它已被 Git 忽略，不会进入代码提交。应用运行不要求该目录或其中的文档副本存在。

当前文件能力：

- `PDF`、`DOCX`、`PPTX`、`XLSX`：人工导入方舟知识库并长期保留，应用从云端目录自动选择并按 `doc_id` 检索，官方解析结果会参与豆包回答。

本地不会对这些文件执行 OCR、正文提取或文本切段。

## 数据与隐私

- 聊天数据库：`data/chat.sqlite3`
- 本地加密密钥：`data/chat.key`
- 公司原文档及方舟解析结果：由管理员在方舟知识库中长期维护；按需使用私有 TOS 作为导入来源。
- 既有本地 `company_documents/` 内容不参与运行，应用不会读取、修改或删除。
- 应用对知识库只读，不上传、更新或删除 PDF 或 Office 文档。
- 应用不会直接向家长发送消息，最终内容由顾问确认和使用。

不要删除 `data/chat.key`，否则既有加密聊天记录将无法读取。

## 开发环境

项目要求 Python 3.11。安装核心依赖和测试依赖：

```powershell
.\.venv\python.exe -m pip install -e ".[dev]"
```

运行测试：

```powershell
.\.venv\python.exe -m pytest -q
```

## 尚未完成

- PDF、Office 文件名、页码和章节引用的真实环境稳定性验收。
- 脱敏并经人工审核的优秀顾问样例学习闭环。
- 与业务系统连接，以查询名额、订单、付款等实时状态。

项目当前状态和后续交接信息见 [HANDOFF.md](HANDOFF.md)。
