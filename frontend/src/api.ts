import type { Analysis, AuthSession, CaseCreated, CaseInput, CaseList, Review, ReviewHistory, ReviewInput, TeamUser, TeamUserList, UserRole, UserStatus } from "./types";

// In development Vite proxies /api to the local backend. Keeping requests on the
// page's origin ensures the HTTP-only login cookie works with either localhost
// or 127.0.0.1 (and avoids cross-site cookie behavior between those hosts).
const API_URL = import.meta.env.VITE_API_URL ?? "";
let csrfToken: string | null = null;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method?.toUpperCase() ?? "GET";
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken && method !== "GET" ? { "X-CSRF-Token": csrfToken } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `API request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getSession(): Promise<AuthSession> {
  const result = await request<AuthSession>("/api/v1/auth/session");
  csrfToken = result.csrf_token;
  return result;
}

export async function login(username: string, password: string): Promise<AuthSession> {
  const result = await request<AuthSession>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  csrfToken = result.csrf_token;
  return result;
}

export async function logout(): Promise<void> {
  await request("/api/v1/auth/logout", { method: "POST" });
  csrfToken = null;
}

export function getCases(): Promise<CaseList> {
  return request<CaseList>("/api/v1/cases", { signal: AbortSignal.timeout(8000) });
}

export function createCase(payload: CaseInput): Promise<CaseCreated> {
  return request<CaseCreated>("/api/v1/cases", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function analyzeCase(caseId: string): Promise<Analysis> {
  return request<Analysis>(`/api/v1/cases/${caseId}/analyze`, { method: "POST" });
}

export function getLatestAnalysis(caseId: string): Promise<Analysis> {
  return request<Analysis>(`/api/v1/cases/${caseId}/analyses/latest`, { signal: AbortSignal.timeout(8000) });
}

export function reviewAnalysis(analysisId: string, payload: ReviewInput): Promise<Review> {
  return request<Review>(`/api/v1/cases/analyses/${analysisId}/reviews`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCaseReviews(caseId: string): Promise<ReviewHistory> {
  return request<ReviewHistory>(`/api/v1/cases/${caseId}/reviews`, { signal: AbortSignal.timeout(8000) });
}

export function getUsers(): Promise<TeamUserList> {
  return request<TeamUserList>("/api/v1/users");
}

export function inviteUser(email: string, displayName: string, role: UserRole): Promise<TeamUser> {
  return request<TeamUser>("/api/v1/users/invitations", {
    method: "POST",
    body: JSON.stringify({ email, display_name: displayName || null, role }),
  });
}

export function updateUser(userId: string, update: { role?: UserRole; status?: UserStatus }): Promise<TeamUser> {
  return request<TeamUser>(`/api/v1/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}
