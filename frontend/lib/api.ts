// The API client: every conversation with the backend, in one typed file.
//
// Design rules, mirroring the backend's own:
// - ONE function (request) all calls pass through, so error handling —
//   including Step 8's kind 429 quota and 503 budget messages — exists
//   exactly once and every page benefits.
// - Types mirror the backend's response shapes. If the backend changes a
//   field, the TypeScript build fails here, loudly, at compile time.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // A non-JSON error body: keep the generic message.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

// --- types (mirrors of the backend's answers) -------------------------------

export type Health = {
  status: string;
  version: string;
  database: string;
  jobs_indexed: number | null;
  budget: { spent_today_usd?: number; cap_usd?: number; exhausted?: boolean };
};

export type Me = { id: number; email: string };

export type Candidate = { id: number; name: string; created_at: string };

export type CandidateProfile = {
  name: string;
  headline: string;
  skills: string[];
  titles: string[];
  years_of_experience: number;
  summary: string;
};

export type MatchJobStatus = {
  match_job_id: number;
  status: "queued" | "running" | "done" | "failed";
  scored: number;
  total_to_score: number;
  error: string | null;
};

export type Match = {
  job_id: number;
  title: string;
  company: string;
  location: string | null;
  url: string;
  vector_score: number;
  llm_score: number | null;
  analysis: {
    score: number;
    verdict: string;
    strengths: string[];
    gaps: string[];
  } | null;
};

export type ChatTurn = {
  session_id: number;
  reply: string;
  tools_used: string[];
  latency_ms: number;
  timed_out: boolean;
};

export type Tailored = {
  id: number;
  job_id: number;
  title: string;
  company: string;
  created_at: string;
  content: {
    target_summary: string;
    skills_ordered: string[];
    experience_bullets: string[];
    keywords_covered: string[];
    gaps_not_claimed: string[];
    change_log: string[];
  };
};

// --- calls ------------------------------------------------------------------

export const api = {
  health: () => request<Health>("/health"),
  me: () => request<Me>("/me"),
  requestLink: (email: string) =>
    request<{ sent: boolean; dev_link?: string }>("/auth/request-link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    }),
  verify: (token: string) =>
    request<{ signed_in: boolean; email: string }>(
      `/auth/verify?token=${encodeURIComponent(token)}`,
    ),
  logout: () => request<{ signed_out: boolean }>("/auth/logout", { method: "POST" }),

  candidates: () => request<Candidate[]>("/candidates"),
  candidate: (id: number) =>
    request<{ id: number; name: string; profile: CandidateProfile }>(
      `/candidates/${id}`,
    ),
  upload: (file: File, consent: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("consent", String(consent));
    return request<{ id: number; name: string; profile: CandidateProfile }>(
      "/candidates",
      { method: "POST", body: form },
    );
  },

  startMatching: (candidateId: number) =>
    request<{ match_job_id: number; status: string }>(
      `/candidates/${candidateId}/match`,
      { method: "POST" },
    ),
  matchJob: (candidateId: number, jobId: number) =>
    request<MatchJobStatus>(`/candidates/${candidateId}/match-jobs/${jobId}`),
  matches: (candidateId: number) =>
    request<Match[]>(`/candidates/${candidateId}/matches`),

  chat: (candidateId: number, message: string, sessionId: number | null) =>
    request<ChatTurn>(`/candidates/${candidateId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    }),

  tailor: (candidateId: number, jobId: number) =>
    request<Tailored>(`/candidates/${candidateId}/jobs/${jobId}/tailor`, {
      method: "POST",
    }),
  tailored: (candidateId: number) =>
    request<Tailored[]>(`/candidates/${candidateId}/tailored`),

  deleteMe: () => request<{ deleted: boolean }>("/me", { method: "DELETE" }),
};

// The active candidate: which resume the Matches/Coach/Tailored pages talk
// about. Kept in the browser's local storage — page-level state, not a
// secret (the backend enforces ownership regardless of what this says).
export function activeCandidate(): number | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("jobhunter_candidate");
  return raw ? Number(raw) : null;
}

export function setActiveCandidate(id: number | null): void {
  if (id === null) window.localStorage.removeItem("jobhunter_candidate");
  else window.localStorage.setItem("jobhunter_candidate", String(id));
}
