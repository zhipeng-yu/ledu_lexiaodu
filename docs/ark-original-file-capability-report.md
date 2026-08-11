# 方舟原文档能力结论

更新时间：2026-08-11。

| 格式 | 当前路径 | 结论 |
|---|---|---|
| PDF | 方舟知识库 | 管理员本地上传后，由应用按云端 `doc_id` 只读检索 |
| DOCX | 方舟知识库 | 管理员本地上传后，由应用按云端 `doc_id` 只读检索 |
| PPTX | 方舟知识库 | 管理员本地上传后，由应用按云端 `doc_id` 只读检索 |
| XLSX | 方舟知识库 | 管理员本地上传后，由应用按云端 `doc_id` 只读检索 |

应用通过 `list_docs` 发现已解析文档，并在一次 `search_knowledge` 请求中合并所选 `doc_id`。运行时不使用方舟 Files API、TOS 客户端或项目内原文档副本，也不上传、更新或删除知识库文档。`VOLC_ACCESSKEY` 和 `VOLC_SECRETKEY` 仅用于知识库 API 鉴权。

官方依据：[文档知识问答核心流程](https://www.volcengine.com/docs/82379/1261883?lang=zh)、[知识库插件功能说明](https://www.volcengine.com/docs/82379/1528458?lang=zh)。
