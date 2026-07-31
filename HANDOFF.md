# 乐小读 Day 4 顾问建议工作台交接

更新时间：2026-07-31

## 当前基线

- 当前分支：`main`。
- Day 4 开发起点：`151f707`（`feat: optimize OCR and add AI question workspace`）。
- 已确认该起点包含 Day 3 提交 `0509edf`（`feat: implement Day 3 local knowledge retrieval`）。
- Day 4 将 Day 3 的本地检索接入截图 OCR 和手动问题工作流，形成可使用的建议闭环。

## 本轮完成范围

### 真实检索驱动的生成流程

- `AdviceService` 对每次对话分别执行 `policy` 和 `style_case` 真实检索，再调用 Generator；生成器不能绕过检索流程。
- 默认 `SimulatedGenerator` 不需要 API。检索到制度依据时，顾虑摘要和微信短回复会使用排名第一的真实文档、定位和证据；没有制度依据时只建议转人工核实，不编造事实。
- 建议卡的事实依据直接绑定 `SearchResult`，不接受生成器或未来模型自行返回引用。
- 手动问题和 OCR 校正对话使用同一条后台生成链路，生成期间不阻塞 Qt 主线程。
- 知识索引缺失或检索失败时，工作台和悬浮工具条都会显示明确错误状态。

### 可替换 Generator 与豆包兼容准备

- `Generator` 是厂商无关的 Protocol，统一输入 `GenerationRequest`，输出 `SuggestionDraft`。
- `OpenAICompatibleGenerator` 接受注入的 client 和 model，调用 `client.chat.completions.create(...)` 并要求 JSON 对象响应。
- 当前计划接入豆包时，只需在应用装配层提供配置好 base URL、密钥和模型的 OpenAI 兼容 client。
- 更换其他 OpenAI 兼容服务不影响检索、风险、反馈和 UI；非兼容协议可新增 Generator 适配器。
- 当前仓库仍不要求真实 API，不安装厂商 SDK，不读取或提交 API Key。

### 完整顾问建议工作台

- 每条结构化建议包含：
  - 顾虑摘要；
  - 可直接编辑的微信短回复；
  - 带文档名和章节/页码的事实依据；
  - 风险等级及逐条风险提示；
  - 明确的转人工状态。
- 工作台保留底部输入区、Enter 发送、Shift+Enter 换行、多轮记录和关闭后重新打开的进程内历史。
- 悬浮工具条“AI 问答”继续打开工作台；截图 OCR 校正确认后也会自动打开同一个工作台。
- 保留 `append_ai_response(text)` 作为旧纯文本调用的兼容入口。

### 确定性风险与复制门控

- 风险判断完全由本地 `DeterministicRiskRules` 执行，不采信生成模型给出的风险等级。
- 高风险规则：退款/投诉/法律争议、人身安全/健康、隐私/个人信息、体罚/欺凌等儿童保护事件。
- 没有 `policy` 权威依据时固定判为高风险并要求转人工。
- 费用、合同、请假、补课、转班及保证性表述等命中中风险并建议人工复核。
- 其他有制度依据且未命中规则的建议为低风险。
- 高风险卡片的复制按钮默认禁用；顾问勾选“已阅读风险提示”后才可一键复制当前编辑内容。

### 隐私安全反馈

- 顾问可选择“有用”或“无用”，并从与选择匹配的枚举原因中提交反馈。
- `FeedbackStore` 将反馈写入独立 SQLite 数据库，字段仅有建议 ID、有用状态、枚举原因和时间戳。
- 反馈表没有聊天、家长问题、OCR 对话或生成回复正文字段。
- 默认反馈路径：`data/feedback.sqlite3`，由 `[feedback].database_path` 配置。

## 主要接口

- `AdviceService.create(transcript)`：真实检索、生成、事实绑定和风险判断的同步核心服务。
- `Generator.generate(request)`：可替换生成器边界。
- `SimulatedGenerator`：默认的本地确定性实现。
- `OpenAICompatibleGenerator(client, model)`：豆包等 OpenAI 兼容服务适配器。
- `DeterministicRiskRules.assess(...)`：确定性风险和转人工判断。
- `AiChatDialog.append_suggestion(suggestion)`：追加完整结构化建议卡。
- `FeedbackStore.save(submission)`：只持久化结构化反馈元数据。
- `CaptureController.transcript_ready`、`ai_question_submitted` 和 `append_ai_response`：继续兼容 Day 3 接口。

## 主要文件

- `src/lexiaodu/advice.py`：检索、生成、风险编排及结构化建议。
- `src/lexiaodu/generator.py`：Generator Protocol、本地模拟实现和 OpenAI 兼容适配器。
- `src/lexiaodu/risk.py`：确定性风险规则与转人工状态。
- `src/lexiaodu/feedback.py`：隐私安全的反馈数据模型和 SQLite 存储。
- `src/lexiaodu/chat.py`：完整建议卡、编辑、复制门控和反馈交互。
- `src/lexiaodu/workflow.py`：手动问题/OCR 到建议工作台的后台链路。
- `src/lexiaodu/app.py`：默认本地服务装配。
- `tests/test_generator.py`、`tests/test_risk.py`、`tests/test_feedback.py`：Day 4 核心逻辑测试。
- `tests/test_chat.py`、`tests/test_workflow.py`：工作台和悬浮工具端到端交互回归。

## 验证命令

默认 `artifacts/pytest` 在当前机器存在既有 Windows ACL 异常，因此使用新的项目内 basetemp 路径运行测试：

```powershell
.\.venv\python.exe -m pytest -q --basetemp=artifacts\pytest-day4-final
.\.venv\python.exe -m compileall -q src tests
.\.venv\python.exe -m pip check
git diff --check
```

Day 4 最终结果：

- 完整测试：59 tests passed。
- Python 编译检查：通过。
- 依赖一致性：`No broken requirements found`。
- 差异空白检查：通过；仅有 Git 的 LF/CRLF 工作区提示。
- 离屏工作台渲染检查：结构化建议卡、高风险确认、反馈区和固定输入区布局完整；当前离屏平台未加载中文字体，但 Unicode 文案由自动化测试验证。

## 已知边界与后续工作

- 豆包真实 client、base URL、模型和密钥尚未装配；当前只完成可替换接口和 OpenAI 兼容适配器。
- 风险规则是保守的确定性关键词规则；新业务风险类型需要显式补规则和测试。
- 本地知识内容变化后仍需主动执行 `--rebuild-knowledge`。
- 扫描型 PDF 知识导入仍不包含 OCR。
- 聊天和建议历史仅驻留当前进程；只有结构化反馈会持久化。
