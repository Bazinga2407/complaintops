# ComplaintOps

ComplaintOps is an AI-assisted operations platform built on the CFPB Consumer Complaint Database. It ingests real public complaints as historical evidence, accepts incoming cases from employees, retrieves similar complaints and relevant policy passages, and produces a cited recommendation for a human operator to approve, edit, or reject.

The project is designed as a portfolio piece for Forward Deployed Engineer roles: it combines a real customer problem, production-style data ingestion, APIs, retrieval, agent orchestration, human review, evaluation, and deployment.

## Current milestone

The current foundation includes:

- FastAPI backend with health and complaint endpoints
- separate active cases created manually or from selected CFPB complaints
- PostgreSQL schema with pgvector
- idempotent CFPB importer keyed by complaint ID
- separate vector collections for complaints and policies
- a React operations queue and internal new-case workflow
- sensitive-data redaction for manually entered narratives
- persisted agent analyses and approve/edit/reject review actions
- Pending, Approved, and Rejected operations queues, with edited recommendations and review history
- evaluation APIs and repeatable benchmarks for review outcomes, retrieval quality, latency, and cost
- a labeled, read-only retrieval benchmark with binary and graded relevance metrics, plus an
  opt-in live-agent runner
- invite-only OpenID Connect sign-in, database-backed users, three roles, CSRF protection, and rate limits
- a local hashed-password mode retained for private development previews
- a Docker image serving the UI and API from one origin
- a deterministic mock agent that costs nothing to run
- a live OpenAI Responses API agent with two controlled retrieval tools
- resumable complaint and policy embedding pipelines with cost caps
- grounded citations, structured output validation, and per-analysis cost tracking
- a versioned 25-chunk demonstration operating policy and automated tests
- deterministic balanced archive sampling across product, issue, year, and narrative length
- a benchmark-candidate exporter for building larger human-reviewed evaluation sets

The AI integration remains optional. Set `AGENT_PROVIDER=mock` for zero-cost local work or `AGENT_PROVIDER=openai` for the live tool-using agent. Both providers return the same validated recommendation contract.

## Architecture

```text
CFPB public API -> historical complaint corpus ----\
                                                    -> RAG + agent -> recommendation
Employee intake -> active case queue --------------/                    |
Operating policies -------------------------------/          approve/edit/reject
```

There is one PostgreSQL database. `complaints` contains the CFPB reference corpus, while `cases` contains active operational work. Historical complaints and policy documents have separate vector collections so retrieval can search each evidence type independently.

## Repository layout

```text
complaintops/
├── backend/             FastAPI API, importer, domain services, tests
├── frontend/            React + TypeScript operations UI
├── database/init/       PostgreSQL and pgvector schema
├── data/samples/        Small, safe development fixtures
├── policies/            Versioned operational policy documents
├── docs/                Architecture and project decisions
├── .github/workflows/   Automated backend and frontend checks
├── render.yaml          Render web-service Blueprint
├── compose.yaml         Local PostgreSQL service
└── .env.example         Configuration contract (no secrets)
```

## Accounts and cost

- CFPB: no account and no download fee. The published complaint data and API are public.
- PostgreSQL: no account for local development. It runs locally as open-source software.
- OpenAI: optional for mock mode; an API account and key are required for embeddings and live analysis.
- Deployment: a cloud host and managed PostgreSQL provider will require accounts later; free tiers may be sufficient for a demo.
- Identity: a production deployment needs an OpenID Connect provider. ComplaintOps stores roles and access status, never provider passwords.

## Local setup

Prerequisites: Python 3.11+, Node.js 20+, and Docker with the Compose plugin.

1. Copy `.env.example` to `.env`.
2. Start PostgreSQL: `docker compose up -d database`.
3. In `backend`, create a virtual environment and install the project: `python -m venv .venv`, then `.venv\\Scripts\\pip install -e ".[dev]"` on Windows.
4. Start the API from `backend`: `.venv\\Scripts\\uvicorn app.main:app --reload`.
5. In `frontend`, run `npm install` and `npm run dev`.
6. Open `http://localhost:5173`; API documentation is at `http://localhost:8000/docs`.

Import a balanced 10,000-narrative corpus from the CFPB's official narrative archives:

```powershell
cd backend
.venv\Scripts\python -m app.services.archive_ingestion `
  --archive-set balanced-history --max-records 10000 --sampling balanced
```

The archive importer downloads the bounded official ZIP, streams its CSV, keeps only records with
published narratives, and uses complaint-ID upserts, so rerunning it does not create duplicates.
The balanced-history set samples six official CFPB archive periods spanning 2011–2026.
Balanced mode makes two streaming passes per ZIP and deterministically samples across product,
issue, received year, and narrative-length strata. This gives the RAG corpus broader coverage than
taking the first rows from one monthly archive. Use the same seed to reproduce the selection.
The CFPB stopped publishing narratives in the live Consumer Complaint Database on August 14,
2026. The live API importer remains available for structured metadata refreshes, but the RAG
narrative corpus now comes from the Bureau's FOIA archive.

Inspect the local database and pgvector status:

```powershell
.venv\Scripts\python -m app.services.diagnostics
```

Embed any complaints and policies that do not yet have vectors. The operation is resumable and
stops before its configured cost cap:

```powershell
.venv\Scripts\python -m app.services.embeddings --limit 10000 --max-cost-usd 1.00
```

## Development without Docker

The pure transformation tests do not require a database:

```powershell
cd backend
python -m pytest
```

The API expects PostgreSQL because vector search is a core product capability. We do not substitute SQLite in production code and accidentally hide PostgreSQL-specific behavior.

Run the zero-cost authenticated workflow check against the local database:

```powershell
cd backend
.venv\Scripts\python -m app.services.smoke
```

The smoke runner creates a marked temporary case, verifies redaction, runs the mock agent against
both knowledge collections, approves the recommendation, confirms persistence, and removes the
temporary case. It never calls the OpenAI API.

## API-key setup

Put the key and provider selection only in the root `.env` file:

```text
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-5.6-luna
AGENT_PROVIDER=openai
```

`.env` is excluded from Git. Never put the key in frontend code, commit it, or paste it into the browser UI. The backend will use the Responses API with controlled function tools and validated structured output; the model will not receive direct database access.

## Data-use note

The historical CFPB narratives used here were published only when consumers opted in and after
the Bureau took steps to remove personal information. In August 2026, the CFPB ceased publishing
new narratives in the live database and moved previously published narratives to its FOIA archive.
ComplaintOps stores only fields exposed by those official public sources. The database is not
statistically representative of every consumer's experience, so the product presents
recommendations and evidence—not automated legal conclusions.

## Roadmap

1. Foundation, dual-source case intake, and CFPB ingestion — complete
2. Database runtime and a balanced 10,000-narrative CFPB backfill — pipeline complete; hosted
   expansion is an explicit operator-run data job
3. Complaint and versioned 25-chunk policy embedding pipelines — complete
4. Live tool-using agent with citations and deterministic guardrails — complete
5. Edit workflow and review history UI — complete
6. Observed metrics, eight-case mock routing baseline, 30-anchor/150-candidate graded benchmark,
   and nDCG reporting — complete; human auditing and a held-out 100-anchor expansion remain
7. Login, API protections, and Render + Neon deployment — complete
8. Authenticated create → redact → analyze → approve → persistence smoke workflow — complete

## Review states and evaluation

The operations queue defaults to Pending. Approving or editing a recommendation moves the
case to Approved; rejecting it moves the case to Rejected. These are **recommendation review
states**, not a claim that the consumer complaint has been resolved. Review decisions and
edited recommendations are stored in `review_actions` and available from
`GET /api/v1/cases/{case_id}/reviews`.

`GET /api/v1/evaluation/summary` reports measurable workflow signals from completed analyses:
review decisions, coverage of both evidence collections, latency, and estimated API cost. These
metrics remain API-only because the internal Evaluation screen was intentionally removed. Citation
coverage does not prove that retrieved material was relevant or that a recommendation was correct;
the small labeled benchmark below provides a diagnostic quality check rather than a production SLA.

`GET /api/v1/evaluation/mock-baseline` runs eight hand-labeled synthetic intake examples
through the deterministic mock router without an API call or database. It measures team and
priority routing only, and deliberately includes a portal-access example that exposes the
router's overly broad `cannot access` priority rule. The score is not a live-agent or RAG
quality score.

The default local development mode still uses a demo operator identity. A private packaged
preview can use the local password mode. Production uses invite-only OpenID Connect: the
identity provider handles sign-in and ComplaintOps enforces operator, reviewer, and admin roles.
See [deployment instructions](docs/deployment.md).
The [expanded retrieval check](docs/evaluation.md) covers 30 anchors and 150 candidates. Its
provisional model-assisted labels produce 86.0% complaint precision@5, 0.818 nDCG@5, and 86.7%
policy hit@3 with complete label coverage. Human review is still required before presenting these
as ground-truth RAG quality measurements. The two-case live-agent smoke benchmark achieved 100%
normalized team and priority accuracy with 100% dual-collection citation coverage at an estimated
cost of $0.00214; that sample is also too small for a broad accuracy claim.
