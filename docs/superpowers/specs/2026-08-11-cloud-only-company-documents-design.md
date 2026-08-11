# Cloud-only company documents design

## Goal

After administrators import company PDF, DOCX, PPTX, and XLSX files into the configured Ark knowledge base, Le Xiaodu must discover, select, and use those documents without requiring local copies.

## Constraints

- Treat PDF, DOCX, PPTX, and XLSX identically at runtime.
- Keep the UI free of manual upload controls.
- Do not upload, update, or delete knowledge-base documents.
- Do not perform local OCR, body extraction, chunking, or knowledge-base rebuilding.
- Do not read, modify, or delete local company documents, chats, keys, or cloud documents.
- Preserve the existing maximum of three automatically selected source documents.

## Considered approaches

1. List ready cloud documents, let Doubao select up to three by document ID and name, then retrieve evidence with one `search_knowledge` call filtered by all selected `doc_id` values. This preserves the current explicit document-routing behavior and is the selected approach.
2. Search the entire knowledge base first and treat the top result documents as the selection. This is simpler, but changes the product behavior from explicit file selection to chunk-first retrieval.
3. Use the Responses API Knowledge Search tool. This requires a flagship knowledge base and broader model/tool configuration changes, so it is unnecessary for the current deployment.

## Architecture

`ArkKnowledgeDocumentReader` is the only document source. It calls the official collection `list_docs` method, keeps successfully processed documents whose names end in `.pdf`, `.docx`, `.pptx`, or `.xlsx`, and exposes immutable `KnowledgeDocument` values containing `doc_id` and `name`.

`OpenAIConversationAssistant` asks Doubao to choose at most three IDs from that cloud list. If documents are selected, the reader calls the official `search_knowledge` API once with all selected IDs in one `doc_filter`, renders the returned chunks with source names, and the assistant sends that evidence to the existing Responses API for the final answer. If no document is selected, the existing plain chat response remains unchanged. Combining IDs prevents the configured standard knowledge base from rejecting immediate per-document requests at its QPS limit.

No runtime code scans `company_documents`, opens source files, calls the Files API, waits for uploaded files, or deletes temporary files.

## Error handling

- Knowledge-base list failures become a source-list error and prevent an unsupported factual answer.
- Selected documents are validated for a supported suffix and non-empty cloud ID.
- Empty retrieval results identify the affected source document.
- Unexpected Ark exceptions retain their original exception as the cause while the user sees a concise knowledge-base failure.
- Documents not yet processed successfully are excluded from routing candidates.

## Verification

- Unit-test cloud discovery for all four formats without creating local files.
- Unit-test exclusion of unsupported and unfinished documents.
- Unit-test `doc_id`-filtered retrieval and rendered evidence for PDF and Office formats.
- Unit-test assistant routing by cloud ID and verify no Files API is present or called.
- Run the focused tests, then the full suite and `git diff --check`.
- If credentials are configured, perform a read-only live list/search check without printing document content or secrets.
