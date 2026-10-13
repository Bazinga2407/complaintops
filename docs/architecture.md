# Architecture decisions

## Why a modular monolith

ComplaintOps starts with three runnable processes: the web frontend, FastAPI backend, and scheduled ingestion worker. Classifier, RAG, and agent code are separate backend modules, but they share one deployable API while the product is small. This keeps local development understandable and leaves clear seams for extracting services if scale requires it.

## Stage-by-stage flow

1. **Ingest history:** The worker imports published narratives from the official CFPB archive.
   Balanced mode deterministically samples product, issue, year, and narrative-length strata before
   converting them into the historical evidence model. The live API remains a metadata refresh.
2. **Create active case:** An employee can enter a complaint received through another channel or promote a selected CFPB complaint into the demonstration queue. Active work lives in `cases`, not in the historical corpus.
3. **Authenticate and authorize:** In production, an OpenID Connect provider verifies identity. ComplaintOps activates only pre-invited emails and loads the user's current operator, reviewer, or admin role from PostgreSQL on every request.
4. **Protect data:** Common SSNs, email addresses, phone numbers, and account-number patterns are redacted before a manually entered narrative is stored.
5. **Classify:** The selected mock or live provider predicts product, issue, routing team, priority, confidence, and escalation flags.
6. **Retrieve complaints:** Vector similarity finds historical narratives, constrained by product filters where useful.
7. **Retrieve policies:** A second search finds relevant chunks from versioned operating policies.
8. **Apply guardrails:** Deterministic code requires both evidence collections, grounds citation IDs in retrieved rows, bounds tool results, and enforces human review.
9. **Agent:** A tool-capable language model calls the controlled searches and rule functions, then returns a structured recommendation with citations.
10. **Human review:** A reviewer or administrator approves, edits, or rejects the recommendation. Every action is linked to the authenticated user. Pending, Approved, and Rejected refer to recommendation review, not complaint resolution.
11. **Evaluate:** The report measures observed review outcomes, dual-collection citation coverage,
    latency, and estimated cost. Eight hand-labeled synthetic cases measure deterministic mock
    routing. The retrieval benchmark measures precision, hit rate, reciprocal rank, and graded
    nDCG. A deterministic exporter creates diverse candidate packs for larger human-reviewed sets.
    Synthetic cases can be run through the live agent only by explicit opt-in.

## Two RAG collections

Both collections are in one PostgreSQL database:

- `complaint_embeddings` points to `complaints` and represents historical case narratives.
- `policy_chunks` points to `policy_documents` and represents versioned operational guidance.

Keeping them separate prevents unlike evidence from competing in one vector index and lets the agent cite each source type clearly.

## Trust boundary

The language model never connects directly to PostgreSQL. The backend exposes narrowly scoped tools, validates their inputs, executes queries, and validates the model's final structured output. Recommendations require human approval before an operational action is committed. This follows the OpenAI Responses API custom-function pattern: https://developers.openai.com/api/docs/guides/function-calling

## CFPB API compatibility

The importer uses the normal paginated search response, which is JSON by default. It does not set the API's `format=json` export option because CFPB retired JSON exports in July 2026. Pagination uses the documented `frm` parameter.
