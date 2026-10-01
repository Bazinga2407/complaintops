export type Case = {
  id: string;
  source: "manual" | "cfpb";
  source_complaint_id: number | null;
  product: string;
  issue: string | null;
  narrative: string;
  company: string | null;
  state: string | null;
  status: string;
  assigned_team: string | null;
  priority: string | null;
  classification_confidence: number | null;
  redaction_count: number;
  created_at: string;
  updated_at: string;
};

export type CaseCreated = Case & {
  privacy_message: string;
};

export type CaseList = {
  items: Case[];
  total: number;
};

export type Citation = {
  collection: "historical_complaints" | "operating_policies";
  source_id: string;
  label: string;
  excerpt: string;
};

export type AgentRecommendation = {
  summary: string;
  classification: {
    product: string;
    issue: string;
    assigned_team: string;
    priority: "standard" | "priority";
    confidence: number;
    escalation_flags: string[];
  };
  recommended_actions: string[];
  rationale: string[];
  citations: Citation[];
  provider: "mock" | "openai";
  requires_human_review: boolean;
};

export type Analysis = {
  id: string;
  case_id: string;
  status: string;
  recommendation: AgentRecommendation;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  estimated_cost_usd: number | null;
  tool_trace: Array<{ tool?: string; status: string; result_count?: number }>;
  created_at: string;
};

export type CaseInput = {
  product: string;
  narrative: string;
  company: string | null;
  state: string | null;
  consent_to_store_redacted_text: boolean;
};

export type ReviewInput = {
  action: "approved" | "edited" | "rejected";
  notes: string | null;
  edited_recommendation: AgentRecommendation | null;
};

export type Review = {
  id: number;
  analysis_run_id: string;
  action: ReviewInput["action"];
  reviewer: string;
  notes: string | null;
  edited_recommendation: AgentRecommendation | null;
  created_at: string;
};

export type ReviewHistory = { items: Review[] };

export type AuthSession = {
  auth_required: boolean;
  authenticated: boolean;
  auth_mode: "demo" | "local" | "oidc";
  username: string | null;
  email: string | null;
  display_name: string | null;
  role: "operator" | "reviewer" | "admin" | null;
  can_review: boolean;
  can_admin: boolean;
  csrf_token: string | null;
};

export type UserRole = "operator" | "reviewer" | "admin";
export type UserStatus = "invited" | "active" | "disabled";

export type TeamUser = {
  id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  status: UserStatus;
  last_login_at: string | null;
  created_at: string;
};

export type TeamUserList = { items: TeamUser[] };
