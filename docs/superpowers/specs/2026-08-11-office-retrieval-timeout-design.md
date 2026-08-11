# Office Retrieval Failure Design

**Goal:** Make the two verified Office documents complete a real Lexiaodu conversation without changing the current PDF request behavior.

## Verified failure chain

- Both target documents are present in Ark with `process_status=0`.
- Direct `doc_id`-filtered searches return non-empty results, so this is not a missing-document, parsing, or empty-retrieval failure.
- The earlier implementation issued one `search_knowledge` request per selected document and a real call captured Ark error `1000029` on a later request. The current baseline already combines all selected `doc_id` values into one request, removing that QPS-triggering call pattern.
- A real `ChatController` conversation on the current baseline listed and selected both target documents, made one combined search, and received 20 points. It then failed in final answer generation with `APITimeoutError -> ReadTimeout -> TimeoutError` because the OpenAI client default is 30 seconds.

## Design

Keep the combined knowledge search unchanged. Pass the selected documents into the final knowledge-answer method. When every selected document has a DOCX, PPTX, or XLSX suffix, add `timeout=120.0` to that single `responses.create` call. If any selected document is a PDF, omit the per-request timeout so the current PDF behavior remains unchanged.

Do not change document discovery, routing, search limits, response retries, local files, cloud documents, or the knowledge-base contents.

## Error classification

The verification must report these conditions separately:

- Missing document: excluded by successful Ark `GetDoc` and catalog lookup for both target IDs.
- Parsing incomplete: excluded by `process_status=0` for both targets.
- Empty retrieval: excluded by non-empty filtered search results for both targets.
- Ark call failure: the historical reader failure was Ark `1000029`; the current post-retrieval failure is the separately observed Responses API timeout.

## Testing

- Add a failing assistant test proving an Office-only response receives `timeout=120.0`.
- Strengthen the mixed PDF/Office test to prove it receives no per-request timeout.
- Run the focused test red, implement the minimal branch, then run focused and full tests green.
- Run one real temporary Lexiaodu conversation using the two documents listed in `HANDOFF.md` section 6 and verify one combined search, a completed assistant message, and both source names in the answer.
