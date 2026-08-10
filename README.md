# 乐小读

乐小读是面向公司顾问的独立 AI 对话应用。顾问描述家长顾虑后，豆包结合当前会话自行分析；需要公司资料时，系统会从项目内的原文档中自动选择相关文件，不需要顾问手动上传。

## 当前工作流程

1. 将公司原文档放入项目根目录的 `company_documents/`。
2. 将 DOCX、PPTX、XLSX 原文件在火山引擎控制台上传到私有 TOS，并手动导入方舟知识库；云端文件名必须与本地文件名一致。
3. 启动乐小读并新建或选择一个会话。
4. 顾问直接描述家长顾虑或追问问题。
5. AI 根据当前会话和文件路径自动选择最多三份相关原文档。
6. 选中的 PDF 仍按原流程临时上传方舟；选中的 Office 文档直接检索已解析的云端知识库文档，不再运行时上传、解析或删除。

每个会话拥有独立上下文。AI 可以自行判断、追问和组织表达，但公司事实必须以原文档为依据。

## 当前支持范围

- 独立聊天窗口，以及会话的新建、选择、搜索、重命名和删除。
- 按会话保存上下文，明确区分“顾问”和“乐小读”。
- 本地加密保存会话与消息。
- 自动发现 `PDF`、`DOCX`、`PPTX`、`XLSX` 原文档。
- 自动选择最多三份相关文件。
- 直接读取并使用 PDF 原文件回答。
- 通过方舟知识库读取并使用 DOCX、PPTX、XLSX 的正文、表格和幻灯片内容。
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

Office 链路需要在华北区域开通 TOS 和方舟知识库，并完成一次人工导入：

1. 创建一个私有 TOS 存储桶，区域选择华北（北京），不要开启版本控制。
2. 在方舟控制台进入“数据管理 → 知识库”，创建“非结构化数据”知识库；默认切片规则即可，记录知识库名称。
3. 在 TOS 控制台上传 DOCX、PPTX、XLSX 原文件，再在知识库选择“导入文档 → TOS 导入”；保留原文件名并等待解析状态成功。
4. 创建具有该知识库读取和检索权限的访问密钥，把 AK/SK 只写入本机 `.env`。

知识库目前仅支持华北区域，并会产生知识库与 TOS 用量费用。应用只按同名文件查找和检索知识库，不上传、不删除云端 Office 文档。文件更新时，请在控制台重新上传并导入，确保知识库中只保留一个同名有效版本。

## 放入公司原文档

文件可直接放在 `company_documents/`，也可以按业务建立子目录，例如：

```text
company_documents/
├── 课程产品/
├── 教师介绍/
├── 服务规则/
└── 顾问优秀案例/
```

目录名和文件名应尽量清楚，因为 AI 会参考相对路径选择文件。`company_documents/` 已被 Git 忽略，公司原文档不会进入代码提交。

当前文件能力：

- `PDF`：已经可以按原始字节临时上传方舟并参与回答。
- `DOCX`、`PPTX`、`XLSX`：人工导入方舟知识库并长期保留，应用按同名文件直接检索，官方解析结果会参与豆包回答。

本地不会对这些文件执行 OCR、正文提取或文本切段。

## 数据与隐私

- 聊天数据库：`data/chat.sqlite3`
- 本地加密密钥：`data/chat.key`
- 公司原文档：`company_documents/`
- 选中的 PDF 只在回答期间临时上传方舟，回答结束后尝试删除临时文件。
- Office 原文件及方舟解析结果由管理员在私有 TOS 与知识库中长期维护；应用只读，不上传或删除。
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

- PDF 文件名、页码和章节引用的真实环境稳定性验收。
- 脱敏并经人工审核的优秀顾问样例学习闭环。
- 与业务系统连接，以查询名额、订单、付款等实时状态。

项目当前状态和后续交接信息见 [HANDOFF.md](HANDOFF.md)。
