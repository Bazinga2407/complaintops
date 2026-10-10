# Deployment guide

ComplaintOps is a FastAPI application with a built React UI and a PostgreSQL database with the
`vector` extension. The included Dockerfile serves the UI and API from one origin. It does not
turn the app into a static-only site.

## Private local preview

The existing `compose.yaml` remains the normal development database. To exercise the packaged
single-operator app locally, first generate credentials from the `backend` folder:

```powershell
.venv\Scripts\python -m app.core.security
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Enter the generated password hash, random session secret, and an operator username in the root
`.env` as `OPERATOR_PASSWORD_HASH`, `SESSION_SECRET`, and `OPERATOR_USERNAME`. Never put the plain
password in that file. Start the preview from the project root:

```powershell
docker compose -f compose.yaml -f compose.preview.yaml up --build -d
```

Open `http://localhost:8002`. This preview binds only to `127.0.0.1`; it is not a public
deployment. The packaged app uses the same existing local database. Use `AGENT_PROVIDER=mock` for
zero-cost testing or `openai` only when you intend API spend.

## Production identity and access

Use `AUTH_MODE=oidc` for a public deployment. Create a web application in any standards-compliant
OpenID Connect provider (for example Auth0, Okta, Microsoft Entra ID, or Google Workspace) and
register this exact callback URL:

```text
https://your-exact-hostname/api/v1/auth/oidc/callback
```

Inject these values through the host's secret manager:

```text
AUTH_MODE=oidc
OIDC_ISSUER=https://your-provider.example
OIDC_CLIENT_ID=provider-client-id
OIDC_CLIENT_SECRET=provider-client-secret
OIDC_SCOPE=openid profile email
OIDC_ADMIN_EMAILS=your.email@company.com
SESSION_SECRET=a-random-value-of-at-least-32-characters
```

`OIDC_ADMIN_EMAILS` is only a bootstrap allowlist for the first administrator. After that person
signs in, use the Team access page to invite other email addresses and assign roles:

- **Operator:** view cases, create cases, and run analyses.
- **Reviewer:** operator capabilities plus approve, edit, and reject.
- **Admin:** reviewer capabilities plus invitations, roles, and account disabling.

There is intentionally no public password signup. The identity provider owns passwords, MFA,
recovery, and email verification; ComplaintOps owns the invite allowlist and authorization. A
disabled user or changed role takes effect on the next API request because the session is checked
against PostgreSQL each time. Remove `OIDC_ADMIN_EMAILS` after the first admin has activated if
you no longer need bootstrap recovery.

## Render + Neon deployment

The repository includes `render.yaml` for a free Render web service and uses Neon for managed
PostgreSQL with pgvector. The container reads Render's `PORT`, initializes the idempotent schema
before starting, and exposes `/health/ready` as a database-and-schema readiness check.

1. Create a Neon project in AWS Ohio (`us-east-2`) to match the Blueprint's Render region, then
   copy its pooled connection string. Neon normally returns a
   `postgresql://` URL; ComplaintOps automatically selects the installed psycopg driver. Keep
   `sslmode=require` in the URL.
2. Create an Auth0 Regular Web Application. Configure the allowed callback URL as
   `https://<your-render-service>.onrender.com/api/v1/auth/oidc/callback` and add
   `https://<your-render-service>.onrender.com` to Allowed Web Origins.
3. In Render, create a Blueprint from this Git repository. Render reads `render.yaml` and prompts
   for `DATABASE_URL`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, and
   `OIDC_ADMIN_EMAILS`. The Blueprint generates `SESSION_SECRET`; never replace it casually because
   doing so signs out every active session.
4. Leave `AGENT_PROVIDER=mock` for the first deployment. After login and the queue work, add
   `OPENAI_API_KEY` in Render's secret environment variables and change `AGENT_PROVIDER` to
   `openai` when paid analyses are intended.

Render supplies `RENDER_EXTERNAL_HOSTNAME`, which ComplaintOps converts to its HTTPS public origin.
If a custom domain is added later, set `PUBLIC_ORIGIN=https://your-domain.example` explicitly and
update the Auth0 callback URL.

The production service receives:

- `APP_ENV=production`; Render supplies the hostname, or `PUBLIC_ORIGIN` overrides it;
- `DATABASE_URL` for the managed PostgreSQL database;
- the OIDC and session settings above (the local operator fields are not used in OIDC mode);
- `AGENT_PROVIDER=mock` initially, or `openai` plus `OPENAI_API_KEY` when paid calls are intended.

Production startup fails when the OIDC secrets or HTTPS origin are absent. The session cookie
is HTTP-only, Secure, SameSite=Strict, and short-lived. API writes require a per-session CSRF
token. Login attempts, writes, and analysis calls have process-local rate limits (including 20
analyses per operator per day). These are not a hard OpenAI spending cap. Run **one API
worker** unless you add a shared limiter. Put a host-level rate limit and request-size cap at the
edge as well. Restrict database network access to the app and job runner. Do not publish the
database port.

The Docker startup command initializes the schema on every service start using idempotent SQL. To
initialize or repair it manually in a one-off shell, run:

```text
python -m app.services.db_init
```

Use the official CFPB narrative archive for the hosted demo; do not copy the local database
because it contains manually entered operational cases. The CFPB stopped publishing narratives
in its live database on August 14, 2026, so the live API now supplies structured metadata but not
the historical text needed for complaint RAG. A small initial corpus can be ingested with
`python -m app.services.archive_ingestion --max-records 500`, then embedded with
`python -m app.services.embeddings --max-cost-usd 0.20`. Embeddings incur OpenAI charges and
the importer may fetch many records; run these deliberately and inspect the resulting counts.

For ongoing structured-metadata updates, create an optional Render Cron Job from the same Git
repository and Dockerfile. Cron jobs are paid Render resources, so the Blueprint intentionally
does not create one. The current refresh command can continue upserting live API records, but it
will not expand the narrative RAG corpus unless the CFPB publishes a newer narrative archive.

Run the live importer manually when you want current structured complaint metadata. Archive and
live importers both upsert by CFPB ID, so overlap does not duplicate records. When the CFPB posts
a newer official narrative archive, point `archive_ingestion --archive-url` at that ZIP and rerun
the embedding pipeline. The scheduler itself is not included in local Compose; it belongs to the
selected host.

## Limits of this release

This is a single-organization portfolio application, not a multi-tenant complaints platform.
It now has managed identity integration and server-enforced roles, but it still lacks a shared
rate limiter, field-level case encryption, automated invitation email, and production incident
monitoring. Run one API worker until the process-local limiter is replaced. Render, Neon, and
Auth0 accounts plus the final public URL still need to be created by the project owner.
