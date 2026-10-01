import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Database,
  FileSearch,
  FileText,
  Filter,
  LockKeyhole,
  Pencil,
  Search,
  ShieldCheck,
  Sparkles,
  UserRoundPlus,
  Users,
} from "lucide-react";
import { analyzeCase, createCase, getCaseReviews, getCases, getLatestAnalysis, getSession, getUsers, inviteUser, login, logout, reviewAnalysis, updateUser } from "./api";
import type { AgentRecommendation, Analysis, AuthSession, Case, CaseInput, Review, ReviewInput, TeamUser, UserRole } from "./types";

type View = "new-case" | "operations" | "team";

const products = [
  "Credit reporting",
  "Debt collection",
  "Checking or savings account",
  "Credit card",
  "Money transfer, virtual currency, or money service",
  "Mortgage",
  "Student loan",
  "Vehicle loan or lease",
];

const demoCases: Case[] = [
  {
    id: "demo-1001",
    source: "manual",
    source_complaint_id: null,
    product: "Debt collection",
    issue: "Attempts to collect debt not owed",
    company: "Sample Financial Company",
    state: "IL",
    narrative: "A collector contacted me about an account I do not recognize.",
    status: "awaiting_review",
    assigned_team: "Collections Resolution",
    priority: "standard",
    classification_confidence: 0.84,
    redaction_count: 0,
    created_at: "2026-08-20T15:00:00Z",
    updated_at: "2026-08-20T15:00:00Z",
  },
  {
    id: "demo-1002",
    source: "cfpb",
    source_complaint_id: 11335865,
    product: "Credit reporting",
    issue: "Incorrect information on a credit report",
    company: "Example Credit Bureau",
    state: "TX",
    narrative: "An account caused by identity theft remains on my report after my dispute.",
    status: "awaiting_review",
    assigned_team: "Credit Reporting",
    priority: "priority",
    classification_confidence: 0.91,
    redaction_count: 0,
    created_at: "2026-08-19T15:00:00Z",
    updated_at: "2026-08-19T15:00:00Z",
  },
  {
    id: "demo-1003",
    source: "manual",
    source_complaint_id: null,
    product: "Money transfer, virtual currency, or money service",
    issue: "Problem with a payment or transfer",
    company: "Demo Payments Inc.",
    state: "CA",
    narrative: "I cannot access the funds I need for rent after a transfer was frozen.",
    status: "new",
    assigned_team: "Payments",
    priority: "priority",
    classification_confidence: 0.87,
    redaction_count: 0,
    created_at: "2026-08-18T15:00:00Z",
    updated_at: "2026-08-18T15:00:00Z",
  },
];

function teamFor(product: string) {
  const value = product.toLowerCase();
  if (value.includes("credit reporting")) return "Credit Reporting";
  if (value.includes("debt collection")) return "Collections Resolution";
  if (value.includes("transfer") || value.includes("payment")) return "Payments";
  return "General Resolution";
}

function localAnalysis(item: Case): Analysis {
  const priority = /identity theft|cannot access|foreclosure|legal action/i.test(item.narrative);
  const team = teamFor(item.product);
  const recommendation: AgentRecommendation = {
    summary: `The consumer reports a ${item.product.toLowerCase()} problem${item.company ? ` involving ${item.company}` : ""}.`,
    classification: {
      product: item.product,
      issue: item.issue ?? "Needs specialist classification",
      assigned_team: team,
      priority: priority ? "priority" : "standard",
      confidence: priority ? 0.88 : 0.72,
      escalation_flags: priority ? ["Narrative contains a priority-review signal"] : [],
    },
    recommended_actions: [
      ...(priority ? ["Place the case in the priority-review queue."] : []),
      `Assign the case to ${team} for review.`,
      "Verify the account and dispute history against the consumer narrative.",
      "Prepare a plain-language acknowledgement and evidence checklist.",
    ],
    rationale: [`Product routes to ${team}.`, "Recommendation requires human approval."],
    citations: [
      {
        collection: "operating_policies",
        source_id: "complaint-handling-policy.md#triage",
        label: "Complaint Handling Policy — Triage",
        excerpt: `Route this product category to the ${team} team.`,
      },
      {
        collection: "historical_complaints",
        source_id: "11335865",
        label: "Comparable CFPB complaint",
        excerpt: "A consumer reported a comparable product and issue combination.",
      },
    ],
    provider: "mock",
    requires_human_review: true,
  };
  return {
    id: `analysis-${item.id}`,
    case_id: item.id,
    status: "completed",
    recommendation,
    model: null,
    prompt_tokens: null,
    completion_tokens: null,
    estimated_cost_usd: 0,
    tool_trace: [],
    created_at: new Date().toISOString(),
  };
}

function initials(company: string | null) {
  if (!company) return "NA";
  return company.split(" ").slice(0, 2).map((word) => word[0]).join("");
}

function App() {
  const [view, setView] = useState<View>("operations");
  const [cases, setCases] = useState<Case[]>([]);
  const [apiAvailable, setApiAvailable] = useState(false);
  const [caseLoadState, setCaseLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [session, setSession] = useState<AuthSession | null>(null);
  const [authLoadError, setAuthLoadError] = useState(false);

  function updateCase(caseId: string, status: string, recommendation?: AgentRecommendation) {
    setCases((current) => current.map((item) => item.id === caseId ? {
      ...item,
      status,
      issue: recommendation?.classification.issue ?? item.issue,
      assigned_team: recommendation?.classification.assigned_team ?? item.assigned_team,
      priority: recommendation?.classification.priority ?? item.priority,
    } : item));
  }

  useEffect(() => {
    getSession().then(setSession).catch(() => {
      if (import.meta.env.DEV) {
        setSession({ auth_required: false, authenticated: true, auth_mode: "demo", username: "Demo Operator", email: "demo@local", display_name: "Demo Operator", role: "admin", can_review: true, can_admin: true, csrf_token: null });
      } else {
        setAuthLoadError(true);
      }
    });
  }, []);

  useEffect(() => {
    if (!session?.authenticated) return;
    setCaseLoadState("loading");
    getCases()
      .then((result) => {
        setApiAvailable(true);
        setCases(result.items);
        setCaseLoadState("ready");
      })
      .catch(() => {
        setApiAvailable(false);
        setCases(session.auth_required ? [] : demoCases);
        setCaseLoadState("error");
      });
  }, [session?.authenticated, session?.auth_required]);

  function addCase(item: Case) {
    setCases((current) => [item, ...current.filter((entry) => entry.id !== item.id)]);
  }

  if (authLoadError) return <main className="auth-screen"><p role="alert">The ComplaintOps API is unavailable. Refresh after the service is running.</p></main>;
  if (!session) return <main className="auth-screen"><p>Connecting to ComplaintOps…</p></main>;
  if (session.auth_required && !session.authenticated) return <LoginScreen session={session} onAuthenticated={setSession} />;
  if (session.auth_required && caseLoadState === "loading") return <main className="auth-screen"><p>Loading cases…</p></main>;
  if (session.auth_required && caseLoadState === "error") return <main className="auth-screen"><p role="alert">You are signed in, but the case list could not be loaded.</p><button type="button" onClick={() => window.location.reload()}>Retry</button></main>;

  async function signOut() {
    try { await logout(); } catch { /* Local state still clears if the session expired. */ }
    setApiAvailable(false);
    setCases([]);
    setSession({ auth_required: true, authenticated: false, auth_mode: session?.auth_mode ?? "local", username: null, email: null, display_name: null, role: null, can_review: false, can_admin: false, csrf_token: null });
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark"><ShieldCheck size={23} /></div>
        <nav aria-label="Primary navigation">
          <button type="button" title="Operations workspace" className={`nav-button ${view === "operations" ? "active" : ""}`} onClick={() => setView("operations")} aria-label="Operations workspace"><ClipboardCheck /></button>
          <button type="button" title="Create a case" className={`nav-button ${view === "new-case" ? "active" : ""}`} onClick={() => setView("new-case")} aria-label="Create a case"><UserRoundPlus /></button>
          {session.can_admin && <button type="button" title="Team access" className={`nav-button ${view === "team" ? "active" : ""}`} onClick={() => setView("team")} aria-label="Team access"><Users /></button>}
        </nav>
        {session.auth_required && <button type="button" className="signout-button" title="Sign out" onClick={() => void signOut()}>Sign out</button>}
        <div className="user-avatar" title={`${session.display_name ?? "Operator"} · ${session.role ?? "operator"}`}>{(session.display_name ?? "DK").slice(0, 2).toUpperCase()}</div>
      </aside>
      {view === "new-case" ? (
        <NewCaseForm apiAvailable={apiAvailable} allowPreview={!session.auth_required} onCreated={addCase} onOpenOperations={() => setView("operations")} />
      ) : view === "team" && session.can_admin ? (
        <TeamAccess onOpenOperations={() => setView("operations")} />
      ) : (
        <OperationsWorkspace cases={cases} apiAvailable={apiAvailable} allowPreview={!session.auth_required} canReview={session.can_review} reviewerName={session.display_name ?? "Operator"} onNewCase={() => setView("new-case")} onCaseUpdated={updateCase} />
      )}
    </div>
  );
}

function LoginScreen({ session, onAuthenticated }: { session: AuthSession; onAuthenticated: (session: AuthSession) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError("");
    try {
      onAuthenticated(await login(username.trim(), password));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Sign-in failed");
    } finally {
      setWorking(false);
    }
  }

  if (session.auth_mode === "oidc") return <main className="auth-screen"><section className="auth-card">
    <span className="auth-logo"><ShieldCheck size={25} /></span>
    <p className="eyebrow">COMPLAINTOPS · INTERNAL ACCESS</p>
    <h1>Sign in to the operations workspace</h1>
    <p>Use your organization account. Access is limited to invited team members.</p>
    <button className="submit-button" type="button" onClick={() => { window.location.href = "/api/v1/auth/oidc/login"; }}>Continue with company sign-in <ArrowRight size={16} /></button>
    <p className="auth-help">Need access? Ask a ComplaintOps administrator to invite your email address.</p>
  </section></main>;

  return <main className="auth-screen"><form className="auth-card" onSubmit={submit}>
    <span className="auth-logo"><ShieldCheck size={25} /></span>
    <p className="eyebrow">COMPLAINTOPS · INTERNAL ACCESS</p>
    <h1>Sign in to the operations workspace</h1>
    <p>Authorized demonstration operators only.</p>
    <label>Username<input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} /></label>
    <label>Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
    {error && <p className="auth-error" role="alert">{error}</p>}
    <button className="submit-button" disabled={working}>{working ? "Signing in…" : "Sign in"}</button>
  </form></main>;
}

function TeamAccess({ onOpenOperations }: { onOpenOperations: () => void }) {
  const [users, setUsers] = useState<TeamUser[]>([]);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<UserRole>("operator");
  const [message, setMessage] = useState("Loading team access…");
  const [working, setWorking] = useState(false);

  useEffect(() => {
    getUsers().then((result) => { setUsers(result.items); setMessage(""); }).catch((failure) => setMessage(failure instanceof Error ? failure.message : "Could not load users"));
  }, []);

  async function invite(event: FormEvent) {
    event.preventDefault();
    setWorking(true);
    setMessage("");
    try {
      const user = await inviteUser(email.trim(), displayName.trim(), role);
      setUsers((current) => [user, ...current]);
      setEmail("");
      setDisplayName("");
      setMessage("Access recorded. They can sign in after their identity-provider account exists.");
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : "Could not invite user");
    } finally {
      setWorking(false);
    }
  }

  async function changeUser(user: TeamUser, update: { role?: UserRole; status?: "invited" | "active" | "disabled" }) {
    setMessage("");
    try {
      const saved = await updateUser(user.id, update);
      setUsers((current) => current.map((item) => item.id === saved.id ? saved : item));
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : "Could not update user");
    }
  }

  return <main className="team-main">
    <header className="topbar"><div><button type="button" className="back-link" onClick={onOpenOperations}><ArrowLeft size={14} /> Return to complaint queue</button><p className="eyebrow">IDENTITY & ACCESS</p><h1>Team access</h1></div><span className="system-status"><i /> Invite-only workspace</span></header>
    <section className="team-layout">
      <form className="invite-card" onSubmit={invite}><p className="eyebrow">ADD TEAM MEMBER</p><h2>Authorize a company email</h2><p>The identity provider manages the account and verifies the email. ComplaintOps decides what that person may do.</p><label>Email<input type="email" required maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" /></label><label>Display name (optional)<input maxLength={200} value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label><label>Role<select value={role} onChange={(event) => setRole(event.target.value as UserRole)}><option value="operator">Operator · view and analyze</option><option value="reviewer">Reviewer · approve and reject</option><option value="admin">Admin · manage team access</option></select></label><button className="submit-button" disabled={working}>{working ? "Saving…" : "Authorize member"}</button></form>
      <section className="team-table-card"><div className="team-table-heading"><div><p className="eyebrow">AUTHORIZED USERS</p><h2>{users.length} team member{users.length === 1 ? "" : "s"}</h2></div></div>{message && <p className="team-message" role="status">{message}</p>}<div className="team-table">{users.map((user) => <article key={user.id}><div className="member-identity"><span>{(user.display_name ?? user.email).slice(0, 2).toUpperCase()}</span><div><strong>{user.display_name || user.email}</strong><small>{user.email}</small></div></div><select aria-label={`Role for ${user.email}`} value={user.role} onChange={(event) => void changeUser(user, { role: event.target.value as UserRole })}><option value="operator">Operator</option><option value="reviewer">Reviewer</option><option value="admin">Admin</option></select><button type="button" className={`status-control ${user.status}`} onClick={() => void changeUser(user, { status: user.status === "disabled" ? "active" : "disabled" })}>{user.status === "disabled" ? "Enable" : user.status === "invited" ? "Invited · disable" : "Active · disable"}</button></article>)}</div></section>
    </section>
  </main>;
}

function NewCaseForm({ apiAvailable, allowPreview, onCreated, onOpenOperations }: { apiAvailable: boolean; allowPreview: boolean; onCreated: (item: Case) => void; onOpenOperations: () => void }) {
  const [form, setForm] = useState<CaseInput>({ product: products[0], narrative: "", company: null, state: null, consent_to_store_redacted_text: false });
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [submittedCase, setSubmittedCase] = useState<Case | null>(null);
  const [isWorking, setIsWorking] = useState(false);
  const [saved, setSaved] = useState(false);
  const [formError, setFormError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsWorking(true);
    setFormError("");
    let created: Case | null = null;
    try {
      created = await createCase(form);
      setSubmittedCase(created);
      onCreated(created);
      const result = await analyzeCase(created.id);
      setAnalysis(result);
      setSaved(true);
    } catch (failure) {
      if (created) {
        setFormError("The case was saved, but analysis failed. Open the complaint queue to retry analysis.");
        return;
      }
      if (!allowPreview) {
        setFormError(failure instanceof Error ? failure.message : "The case could not be saved.");
        return;
      }
      const now = new Date().toISOString();
      const localCase: Case = {
        id: `local-${Date.now()}`,
        source: "manual",
        source_complaint_id: null,
        product: form.product,
        issue: null,
        narrative: form.narrative,
        company: form.company,
        state: form.state,
        status: "preview_only",
        assigned_team: teamFor(form.product),
        priority: null,
        classification_confidence: null,
        redaction_count: 0,
        created_at: now,
        updated_at: now,
      };
      setSubmittedCase(localCase);
      setAnalysis(localAnalysis(localCase));
      setSaved(false);
      onCreated(localCase);
    } finally {
      setIsWorking(false);
    }
  }

  if (analysis && submittedCase) {
    const result = analysis.recommendation;
    return (
      <main className="consumer-main">
        <header className="consumer-topbar">
          <button type="button" className="text-button" onClick={() => { setAnalysis(null); setSubmittedCase(null); }}><ArrowLeft size={16} /> Create another case</button>
          <button type="button" className="operator-link" onClick={onOpenOperations}>Return to complaint queue <ArrowRight size={15} /></button>
        </header>
        <div className="report-shell">
          <div className="report-intro">
            <span className="success-icon"><Check size={24} /></span>
            <p className="eyebrow">CASE CREATED AND ANALYZED</p>
            <h1>Ready for operations review</h1>
            <p>The preliminary recommendation is waiting for an employee to approve, edit, or reject it.</p>
            <span className={`save-status ${saved ? "saved" : ""}`}>{saved ? "Saved to the operations queue" : "Preview only — database is not running"}</span>
          </div>
          <section className="report-grid">
            <article className="report-card summary-card">
              <div className="section-title"><Sparkles size={18} /><h2>Agent summary</h2></div>
              <p>{result.summary}</p>
              <div className="classification-grid">
                <div><span>Predicted issue</span><strong>{result.classification.issue}</strong></div>
                <div><span>Assigned team</span><strong>{result.classification.assigned_team}</strong></div>
                <div><span>Priority</span><strong>{result.classification.priority}</strong></div>
                <div><span>Confidence</span><strong>{Math.round(result.classification.confidence * 100)}%</strong></div>
              </div>
            </article>
            <article className="report-card actions-card">
              <div className="section-title"><ClipboardCheck size={18} /><h2>Recommended next steps</h2></div>
              <ol>{result.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ol>
              <div className="human-notice"><ShieldCheck size={17} /><span><strong>Human review required</strong>This agent cannot finalize routing or a response.</span></div>
            </article>
            <article className="report-card evidence-card">
              <div className="section-title"><FileSearch size={18} /><h2>Evidence used</h2></div>
              <div className="citation-list">
                {result.citations.map((citation) => (
                  <div className="citation" key={`${citation.collection}-${citation.source_id}`}>
                    <span>{citation.collection === "historical_complaints" ? "Historical case" : "Operating policy"}</span>
                    <strong>{citation.label}</strong>
                    <p>{citation.excerpt}</p>
                  </div>
                ))}
              </div>
            </article>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="consumer-main">
      <header className="consumer-topbar">
        <div className="consumer-brand"><span>ComplaintOps</span><small>Operations intake</small></div>
        <button type="button" className="operator-link" onClick={onOpenOperations}>Return to complaint queue <ArrowRight size={15} /></button>
      </header>
      <div className="intake-layout">
        <section className="intake-copy">
          <p className="eyebrow">EMPLOYEE CASE INTAKE</p>
          <h1>Create a new case.<br /><em>The agent prepares the first review.</em></h1>
          <p className="lede">Enter a complaint received by phone, email, or another channel. ComplaintOps structures it, searches historical CFPB cases and operating policies, then prepares a cited recommendation.</p>
          <div className="trust-list">
            <div><span><LockKeyhole size={18} /></span><p><strong>Sensitive-data screening</strong>Common account, contact, and identity details are removed before the case is stored.</p></div>
            <div><span><Database size={18} /></span><p><strong>Real historical evidence</strong>Recommendations use public CFPB complaint patterns, not invented outcomes.</p></div>
            <div><span><ShieldCheck size={18} /></span><p><strong>The employee stays responsible</strong>The agent recommends; you approve, edit, or reject.</p></div>
          </div>
          <p className="disclaimer">Internal demonstration workflow. Do not enter real SSNs, full account numbers, or other highly sensitive information.</p>
        </section>
        <form className="intake-form" onSubmit={submit}>
          <div className="form-heading"><div><p className="eyebrow">NEW INCOMING CASE</p><h2>Record the complaint</h2></div><span className={`api-dot ${apiAvailable ? "online" : ""}`}>{apiAvailable ? "API connected" : "Preview mode"}</span></div>
          <label>Consumer's financial product<select value={form.product} onChange={(event) => setForm({ ...form, product: event.target.value })}>{products.map((product) => <option key={product}>{product}</option>)}</select></label>
          <div className="form-row">
            <label>Company <span>Optional</span><input placeholder="Company name" value={form.company ?? ""} onChange={(event) => setForm({ ...form, company: event.target.value || null })} /></label>
            <label>State <span>Optional</span><input maxLength={2} placeholder="IL" value={form.state ?? ""} onChange={(event) => setForm({ ...form, state: event.target.value.toUpperCase() || null })} /></label>
          </div>
          <label>Complaint narrative<textarea minLength={30} maxLength={10000} required placeholder="Include dates, the consumer's expected outcome, what happened, and steps already taken. Do not include unnecessary sensitive account details." value={form.narrative} onChange={(event) => setForm({ ...form, narrative: event.target.value })} /><small className="character-count">{form.narrative.length} / 10,000</small></label>
          <label className="consent"><input type="checkbox" required checked={form.consent_to_store_redacted_text} onChange={(event) => setForm({ ...form, consent_to_store_redacted_text: event.target.checked })} /><span>I confirm that the redacted narrative may be stored in this demonstration case.</span></label>
          <button className="submit-button" disabled={isWorking || submittedCase !== null || form.narrative.length < 30 || !form.consent_to_store_redacted_text}>{isWorking ? "Creating and analyzing…" : <>Create and analyze case <ArrowRight size={17} /></>}</button>
          {formError && <p className="auth-error" role="alert">{formError}</p>}
          {!isWorking && form.narrative.length < 30 && <p className="button-hint">Enter at least 30 characters to enable analysis.</p>}
          {!isWorking && form.narrative.length >= 30 && !form.consent_to_store_redacted_text && <p className="button-hint">Confirm redacted-text storage to enable analysis.</p>}
          <p className="form-footnote"><LockKeyhole size={12} /> Your API key is never entered in this form or sent to the browser.</p>
        </form>
      </div>
    </main>
  );
}

function OperationsWorkspace({ cases, apiAvailable, allowPreview, canReview, reviewerName, onNewCase, onCaseUpdated }: { cases: Case[]; apiAvailable: boolean; allowPreview: boolean; canReview: boolean; reviewerName: string; onNewCase: () => void; onCaseUpdated: (caseId: string, status: string, recommendation?: AgentRecommendation) => void }) {
  const [selectedId, setSelectedId] = useState(cases[0]?.id);
  const [queueStatus, setQueueStatus] = useState<"pending" | "approved" | "rejected">("pending");
  const [query, setQuery] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [priorityFilter, setPriorityFilter] = useState<"all" | "priority" | "standard">("all");
  const [analysis, setAnalysis] = useState<Analysis | null>(cases[0] ? localAnalysis(cases[0]) : null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [reviewHistory, setReviewHistory] = useState<Review[]>([]);
  const [localReviews, setLocalReviews] = useState<Record<string, Review[]>>({});
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [reviewingAction, setReviewingAction] = useState<ReviewInput["action"] | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editSummary, setEditSummary] = useState("");
  const [editTeam, setEditTeam] = useState("");
  const [editPriority, setEditPriority] = useState<"standard" | "priority">("standard");
  const [editActions, setEditActions] = useState("");
  const [editNotes, setEditNotes] = useState("");

  const pending = cases.filter((item) => !["approved", "rejected"].includes(item.status));

  const filtered = useMemo(() => {
    const normalized = query.toLowerCase();
    return cases.filter((item) => {
      const matchesStatus = queueStatus === "pending" ? !["approved", "rejected"].includes(item.status) : item.status === queueStatus;
      const matchesQuery = [item.product, item.issue ?? "", item.company ?? "", item.state ?? ""].join(" ").toLowerCase().includes(normalized);
      const itemPriority = item.priority ?? localAnalysis(item).recommendation.classification.priority;
      return matchesStatus && matchesQuery && (priorityFilter === "all" || itemPriority === priorityFilter);
    });
  }, [cases, priorityFilter, query, queueStatus]);
  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
  const selectedCaseId = selected?.id;
  const visibleAnalysis = selected && analysis?.case_id === selected.id ? analysis : null;
  const liveAgent = visibleAnalysis?.recommendation.provider === "openai";

  useEffect(() => {
    if (selected) {
      setAnalysis(allowPreview ? localAnalysis(selected) : null);
      setAnalysisLoading(false);
      setReviewHistory(localReviews[selected.id] ?? []);
      setActionMessage(null);
      setIsEditing(false);
      if (apiAvailable && !selected.id.startsWith("demo-") && !selected.id.startsWith("local-")) {
        let active = true;
        setAnalysisLoading(true);
        getLatestAnalysis(selected.id).then((result) => { if (active) setAnalysis(result); }).catch(() => undefined).finally(() => { if (active) setAnalysisLoading(false); });
        getCaseReviews(selected.id).then((result) => { if (active) setReviewHistory(result.items); }).catch(() => undefined);
        return () => { active = false; };
      }
    } else {
      setAnalysis(null);
      setAnalysisLoading(false);
    }
  }, [apiAvailable, allowPreview, selectedCaseId]);

  async function runAnalysis() {
    if (!selected || isAnalyzing) return;
    setIsAnalyzing(true);
    setActionMessage("Searching both knowledge collections and preparing a recommendation…");
    try {
      const result = await analyzeCase(selected.id);
      setAnalysis(result);
      onCaseUpdated(selected.id, "awaiting_review", result.recommendation);
      setQueueStatus("pending");
      setActionMessage("Analysis complete. Review the updated recommendation and citations.");
    } catch {
      if (allowPreview) setAnalysis(localAnalysis(selected));
      setActionMessage(allowPreview ? "Live analysis was unavailable, so a local preview is shown." : "Analysis failed. Please try again.");
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function review(action: ReviewInput["action"], editedRecommendation: AgentRecommendation | null = null, notes: string | null = null) {
    if (!selected || !visibleAnalysis || reviewingAction) return;
    if (!canReview) {
      setActionMessage("A reviewer or administrator must make the final decision.");
      return;
    }
    if (!allowPreview && (!apiAvailable || visibleAnalysis.id.startsWith("analysis-"))) {
      setActionMessage("The live API is unavailable; no review was saved.");
      return;
    }
    setReviewingAction(action);
    setActionMessage("Saving review decision…");
    if (apiAvailable && !visibleAnalysis.id.startsWith("analysis-")) {
      try {
        const saved = await reviewAnalysis(visibleAnalysis.id, { action, notes, edited_recommendation: editedRecommendation });
        setReviewHistory((current) => [saved, ...current]);
      } catch {
        setActionMessage("The review was not saved. Check the API and try again.");
        setReviewingAction(null);
        return;
      }
    } else {
      const localReview: Review = {
        id: -Date.now(),
        analysis_run_id: visibleAnalysis.id,
        action,
        reviewer: reviewerName,
        notes,
        edited_recommendation: editedRecommendation,
        created_at: new Date().toISOString(),
      };
      setLocalReviews((current) => ({ ...current, [selected.id]: [localReview, ...(current[selected.id] ?? [])] }));
      setReviewHistory((current) => [localReview, ...current]);
    }
    if (editedRecommendation) setAnalysis({ ...visibleAnalysis, recommendation: editedRecommendation });
    onCaseUpdated(selected.id, action === "rejected" ? "rejected" : "approved", editedRecommendation ?? undefined);
    setQueueStatus(action === "rejected" ? "rejected" : "approved");
    setIsEditing(false);
    setActionMessage(action === "edited" ? "Edited recommendation approved and saved." : `Recommendation ${action} and saved.`);
    setReviewingAction(null);
  }

  function startEditing() {
    if (!visibleAnalysis) return;
    const recommendation = visibleAnalysis.recommendation;
    setEditSummary(recommendation.summary);
    setEditTeam(recommendation.classification.assigned_team);
    setEditPriority(recommendation.classification.priority);
    setEditActions(recommendation.recommended_actions.join("\n"));
    setEditNotes("");
    setIsEditing(true);
  }

  function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!visibleAnalysis) return;
    const actions = editActions.split("\n").map((value) => value.trim()).filter(Boolean);
    if (!editSummary.trim() || !editTeam.trim() || !actions.length) return;
    const editedRecommendation: AgentRecommendation = {
      ...visibleAnalysis.recommendation,
      summary: editSummary.trim(),
      classification: { ...visibleAnalysis.recommendation.classification, assigned_team: editTeam.trim(), priority: editPriority },
      recommended_actions: actions,
    };
    void review("edited", editedRecommendation, editNotes.trim() || null);
  }

  return (
    <main className="operations-main">
      <header className="topbar">
        <div><button type="button" className="back-link" onClick={onNewCase}><UserRoundPlus size={14} /> New incoming case</button><p className="eyebrow">OPERATIONS CONTROL</p><h1>Complaint queue</h1></div>
        <div className="status-group"><span className="demo-pill">{apiAvailable ? "Live database" : "Demo data"}</span><span className="system-status"><i /> Interface operational</span></div>
      </header>
      <section className="metrics" aria-label="Queue metrics">
        <article><span>Pending review</span><strong>{pending.length}</strong><small>Awaiting a decision</small></article>
        <article><span>Priority review</span><strong>{pending.filter((item) => item.priority === "priority").length}</strong><small className="warn">Escalation signals</small></article>
        <article><span>Manual intake</span><strong>{cases.filter((item) => item.source === "manual").length}</strong><small>Consumer submissions</small></article>
        <article><span>Selected analysis</span><strong className="metric-word">{visibleAnalysis ? liveAgent ? "Live AI" : "Mock" : "None"}</strong><small>{visibleAnalysis ? liveAgent ? `${visibleAnalysis.model ?? "OpenAI"} · $${(visibleAnalysis.estimated_cost_usd ?? 0).toFixed(4)}` : "Zero API cost" : "Select a case to view its analysis"}</small></article>
      </section>
      <section className="workspace">
        <div className="queue-panel">
          <div className="queue-tabs" role="tablist" aria-label="Review status">
            {(["pending", "approved", "rejected"] as const).map((status) => <button type="button" role="tab" aria-selected={queueStatus === status} className={queueStatus === status ? "active" : ""} key={status} onClick={() => setQueueStatus(status)}>{status === "pending" ? "Pending" : status === "approved" ? "Approved" : "Rejected"}<span>{status === "pending" ? pending.length : cases.filter((item) => item.status === status).length}</span></button>)}
          </div>
          <div className="toolbar"><label className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search cases" /></label><button type="button" className={`filter-button ${showFilters || priorityFilter !== "all" ? "active" : ""}`} aria-expanded={showFilters} onClick={() => setShowFilters((current) => !current)}><Filter size={16} /> Filter{priorityFilter !== "all" ? " · 1" : ""}</button></div>
          {showFilters && <div className="filter-panel"><label>Priority<select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value as "all" | "priority" | "standard")}><option value="all">All cases</option><option value="priority">Priority only</option><option value="standard">Standard only</option></select></label><button type="button" onClick={() => { setPriorityFilter("all"); setQuery(""); }}>Clear filters</button></div>}
          <div className="column-labels"><span>Case</span><span>Received</span></div>
          <div className="case-list">{filtered.map((item) => <button type="button" key={item.id} className={`case-row ${item.id === selected?.id ? "selected" : ""}`} onClick={() => setSelectedId(item.id)}><span className="company-avatar">{initials(item.company)}</span><span className="case-copy"><strong>{item.issue ?? "Unclassified complaint"}</strong><small>{item.company ?? "Company not provided"} · {item.state ?? "—"}</small><span className="product-tag">{item.product}</span></span><time>{new Date(item.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</time></button>)}{filtered.length === 0 && <div className="empty-cases"><Search size={20} /><strong>No {queueStatus} cases found</strong><span>Try changing the search or priority filter.</span></div>}</div>
        </div>
        {selected && visibleAnalysis ? <div className="detail-panel">
          <div className="detail-header"><div><p className="eyebrow">CASE {selected.id.slice(0, 12).toUpperCase()}</p><h2>{selected.product}</h2></div><span className={`priority ${visibleAnalysis.recommendation.classification.priority}`}>{visibleAnalysis.recommendation.classification.priority === "priority" ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}{visibleAnalysis.recommendation.classification.priority}</span></div>
          <div className="case-metadata"><div><span>Company</span><strong>{selected.company ?? "Not provided"}</strong></div><div><span>Source</span><strong>{selected.source.toUpperCase()}</strong></div><div><span>Review state</span><strong>{selected.status === "approved" ? "Recommendation approved" : selected.status === "rejected" ? "Recommendation rejected" : "Pending review"}</strong></div></div>
          <section className="narrative-card"><div className="section-title"><FileText size={17} /><h3>Consumer narrative</h3></div><p>{selected.narrative}</p></section>
          <section className="recommendation-card"><div className="agent-heading"><div className="agent-icon"><Sparkles size={18} /></div><div className="agent-copy"><p className="eyebrow">AGENT RECOMMENDATION · {visibleAnalysis.recommendation.provider === "openai" ? "LIVE TWO-COLLECTION RAG" : "MOCK PREVIEW"}</p><h3>{visibleAnalysis.recommendation.summary}</h3></div><span className="human-tag"><ShieldCheck size={12} /> {selected.status === "approved" ? "Reviewed" : selected.status === "rejected" ? "Rejected" : "Review required"}</span></div><div className="recommendation-route"><div><span>Assign to</span><strong>{visibleAnalysis.recommendation.classification.assigned_team}</strong></div><ArrowRight size={18} /><div><span>Confidence</span><strong>{Math.round(visibleAnalysis.recommendation.classification.confidence * 100)}%</strong></div></div><ul>{visibleAnalysis.recommendation.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ul><div className="compact-citations">{visibleAnalysis.recommendation.citations.map((citation) => <span key={`${citation.collection}-${citation.source_id}`}><FileSearch size={12} /> {citation.label}</span>)}</div>{visibleAnalysis.recommendation.provider === "openai" && <p className="form-footnote">Model: {visibleAnalysis.model} · Tokens: {(visibleAnalysis.prompt_tokens ?? 0) + (visibleAnalysis.completion_tokens ?? 0)} · Estimated cost: ${(visibleAnalysis.estimated_cost_usd ?? 0).toFixed(4)}</p>}</section>
          {isEditing && <form className="edit-panel" onSubmit={saveEdit}><div className="section-title"><Pencil size={16} /><h3>Edit and approve recommendation</h3></div><p>Adjust the operational recommendation. Evidence citations remain unchanged.</p><label>Summary<textarea maxLength={2000} required value={editSummary} onChange={(event) => setEditSummary(event.target.value)} /></label><div className="edit-fields"><label>Assigned team<input maxLength={120} required value={editTeam} onChange={(event) => setEditTeam(event.target.value)} /></label><label>Priority<select value={editPriority} onChange={(event) => setEditPriority(event.target.value as "standard" | "priority")}><option value="standard">Standard</option><option value="priority">Priority</option></select></label></div><label>Recommended actions (one per line)<textarea required value={editActions} onChange={(event) => setEditActions(event.target.value)} /></label><label>Reason for edit (optional)<textarea maxLength={2000} value={editNotes} onChange={(event) => setEditNotes(event.target.value)} /></label><div className="edit-actions"><button type="button" className="secondary" onClick={() => setIsEditing(false)}>Cancel</button><button type="submit" className="primary" disabled={reviewingAction !== null || !editActions.trim()}>{reviewingAction === "edited" ? "Saving…" : "Save edit and approve"}</button></div></form>}
          <section className="review-history"><div className="section-title"><ClipboardCheck size={17} /><h3>Review history</h3></div>{reviewHistory.length ? <ol>{reviewHistory.map((item) => <li key={item.id}><strong>{item.action === "edited" ? "Edited and approved" : item.action === "approved" ? "Approved" : "Rejected"}</strong><span>{item.reviewer} · {new Date(item.created_at).toLocaleString()}</span>{item.notes && <p>{item.notes}</p>}</li>)}</ol> : <p>No review decisions recorded yet.</p>}</section>
          {!canReview && queueStatus === "pending" && <p className="permission-note"><LockKeyhole size={14} /> You can analyze this case, but only a reviewer or administrator can approve, edit, or reject it.</p>}
          {actionMessage && <p className="action-message" role="status">{actionMessage}</p>}
          <div className="actions">{queueStatus === "pending" && canReview && <><button type="button" className="secondary" onClick={() => void review("rejected")} disabled={isAnalyzing || reviewingAction !== null}>{reviewingAction === "rejected" ? "Rejecting…" : "Reject"}</button><button type="button" className="secondary" onClick={startEditing} disabled={isAnalyzing || reviewingAction !== null || isEditing}><Pencil size={13} /> Edit</button></>}<button type="button" className="secondary" onClick={runAnalysis} disabled={isAnalyzing || reviewingAction !== null}>{isAnalyzing ? "Analyzing…" : queueStatus === "pending" ? "Run analysis" : "Re-run analysis"}</button>{queueStatus === "pending" && canReview && <button type="button" className="primary" onClick={() => void review("approved")} disabled={isAnalyzing || reviewingAction !== null}>{reviewingAction === "approved" ? "Approving…" : "Approve recommendation"}</button>}</div>
        </div> : <div className="detail-panel detail-empty"><ClipboardCheck size={26} /><h2>{analysisLoading ? "Loading analysis…" : selected ? "No completed analysis" : `No ${queueStatus} cases`}</h2><p>{selected ? analysisLoading ? "Retrieving the latest recommendation." : "Run an analysis to prepare a recommendation for review." : "Choose another review status or create a new case."}</p>{selected && !analysisLoading && <button type="button" className="primary" onClick={runAnalysis} disabled={isAnalyzing || !apiAvailable && !allowPreview}>{isAnalyzing ? "Analyzing…" : "Run analysis"}</button>}{actionMessage && <p className="action-message" role="status">{actionMessage}</p>}</div>}
      </section>
    </main>
  );
}

export default App;
