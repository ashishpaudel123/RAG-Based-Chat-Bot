// Typed client for the FastAPI backend. The Gemini API key never reaches the
// browser: the frontend only talks to our own backend with a user JWT.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "chatbot_token";

export type Role = "user" | "admin";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Citation {
  chunk_id: string | null;
  document_id: string | null;
  document_title: string;
  section: string | null;
  page: number | null;
  snippet: string;
  score: number;
  rank: number;
  source_type: string | null;
  authority_tier: number | null;
  validity_status: string | null;
  legal_reference: string | null;
  district: string | null;
  effective_from: string | null;
  source_url: string | null;
  last_verified: string | null;
}

export interface Feedback {
  id: string;
  rating: 1 | -1;
  comment: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  is_fallback: boolean;
  latency_ms: number | null;
  created_at: string;
  kind?: "answer" | "clarification" | "fallback" | "small_talk" | null;
  confidence?: "HIGH" | "MEDIUM" | "LOW" | "NEEDS_CLARIFICATION" | null;
  language?: string | null;
  citations: Citation[];
  feedback: Feedback | null;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}

export interface ChatResponse {
  conversation_id: string;
  conversation_title: string;
  user_message: Message;
  assistant_message: Message;
}

export interface DocumentInfo {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  version: number;
  tags: string[];
  status: "pending" | "indexed" | "failed";
  error: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
  record_id: string | null;
  source_type: string;
  authority: string | null;
  authority_tier: number;
  category: string | null;
  legal_reference: string | null;
  jurisdiction: string | null;
  district: string | null;
  validity_status: "current" | "superseded" | "historical";
  effective_from: string | null;
  effective_until: string | null;
  source_url: string | null;
  last_verified: string | null;
  verification_status: "verified" | "pending" | "rejected";
  language: string | null;
  lineage_id: string | null;
  supersedes_id: string | null;
}

/** Editable source metadata (form fields). Empty string clears a free-text field. */
export interface DocumentMeta {
  source_type?: string;
  authority_tier?: string;
  authority?: string;
  category?: string;
  legal_reference?: string;
  jurisdiction?: string;
  district?: string;
  validity_status?: string;
  effective_from?: string;
  effective_until?: string;
  source_url?: string;
  last_verified?: string;
  verification_status?: string;
  language?: string;
}

export interface Profile {
  id: string;
  assistant_name: string;
  tagline: string;
  suggestions: string[];
  answer_format: string;
}

export const SOURCE_TYPES = [
  "constitution", "act", "amendment", "regulation", "directive", "circular", "official_notice", "form",
  "court_decision", "dao_charter", "local_notice", "official_portal", "secondary", "faq", "informal", "other",
] as const;

export interface Chunk {
  id: string;
  chunk_index: number;
  text: string;
  section: string | null;
  page: number | null;
}

export interface IndexRun {
  id: number;
  scope: string;
  embedding_model: string;
  embedding_dimensions: number;
  chunk_size: number;
  chunk_overlap: number;
  documents_indexed: number;
  chunks_indexed: number;
  failures: number;
  duration_ms: number;
  created_at: string;
}

export interface ErrorLog {
  id: number;
  level: string;
  source: string;
  message: string;
  user_id: string | null;
  path: string | null;
  created_at: string;
}

export interface Stats {
  users: number;
  conversations: number;
  messages: number;
  documents: number;
  chunks: number;
  feedback_positive: number;
  feedback_negative: number;
  fallback_rate: number;
  avg_latency_ms: number | null;
  errors_last_24h: number;
}

export interface Health {
  status: string;
  database: string;
  vector_store: string;
  llm_provider: string;
  llm_configured: boolean;
  indexed_chunks: number;
  version: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const tokenStore = {
  get: () => (typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY)),
  set: (token: string) => window.localStorage.setItem(TOKEN_KEY, token),
  clear: () => window.localStorage.removeItem(TOKEN_KEY),
};

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    // FastAPI validation errors
    return detail
      .map((d: { msg?: string; loc?: unknown[] }) => {
        const field = Array.isArray(d.loc) ? String(d.loc[d.loc.length - 1]) : "";
        const msg = (d.msg || "Invalid value").replace(/^Value error, /, "");
        return field && field !== "body" ? `${field}: ${msg}` : msg;
      })
      .join(" · ");
  }
  if (status === 0) return "Cannot reach the server. Check your connection and try again.";
  return `Request failed (${status})`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, errorMessage(null, 0));
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token && onUnauthorized) onUnauthorized();
    throw new ApiError(res.status, errorMessage(body, res.status));
  }
  return body as T;
}

const json = (data: unknown) => JSON.stringify(data);

export const api = {
  // auth
  register: (email: string, full_name: string, password: string) =>
    request<TokenResponse>("/api/auth/register", { method: "POST", body: json({ email, full_name, password }) }),
  login: (email: string, password: string) =>
    request<TokenResponse>("/api/auth/login", { method: "POST", body: json({ email, password }) }),
  me: () => request<User>("/api/auth/me"),

  // chat
  sendMessage: (message: string, conversation_id?: string | null) =>
    request<ChatResponse>("/api/chat", { method: "POST", body: json({ message, conversation_id }) }),
  listChats: () => request<ConversationSummary[]>("/api/chats"),
  getChat: (id: string) => request<ConversationDetail>(`/api/chats/${id}`),
  renameChat: (id: string, title: string) =>
    request<ConversationSummary>(`/api/chats/${id}`, { method: "PATCH", body: json({ title }) }),
  deleteChat: (id: string) => request<void>(`/api/chats/${id}`, { method: "DELETE" }),
  sendFeedback: (message_id: string, rating: 1 | -1, comment?: string) =>
    request<Feedback>("/api/feedback", { method: "POST", body: json({ message_id, rating, comment }) }),

  // knowledge (admin)
  listDocuments: () => request<DocumentInfo[]>("/api/documents"),
  uploadDocument: (file: File, title?: string, tags?: string, meta: DocumentMeta = {}) => {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    if (tags) form.append("tags", tags);
    // On upload, empty fields mean "use the file's front matter / defaults".
    for (const [k, v] of Object.entries(meta)) if (v) form.append(k, v);
    return request<DocumentInfo>("/api/documents/upload", { method: "POST", body: form });
  },
  updateDocument: (id: string, opts: { file?: File | null; title?: string; tags?: string; meta?: DocumentMeta }) => {
    const form = new FormData();
    if (opts.file) form.append("file", opts.file);
    if (opts.title !== undefined) form.append("title", opts.title);
    if (opts.tags !== undefined) form.append("tags", opts.tags);
    for (const [k, v] of Object.entries(opts.meta ?? {})) if (v !== undefined) form.append(k, v);
    return request<DocumentInfo>(`/api/documents/${id}`, { method: "PUT", body: form });
  },
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  documentChunks: (id: string) => request<Chunk[]>(`/api/documents/${id}/chunks`),
  reindex: (document_id?: string) =>
    request<IndexRun>("/api/knowledge/reindex", { method: "POST", body: json({ document_id: document_id ?? null }) }),
  indexRuns: () => request<IndexRun[]>("/api/knowledge/runs"),

  // administration
  listUsers: () => request<User[]>("/api/admin/users"),
  updateUser: (id: string, patch: { role?: Role; is_active?: boolean }) =>
    request<User>(`/api/admin/users/${id}`, { method: "PATCH", body: json(patch) }),
  logs: () => request<ErrorLog[]>("/api/admin/logs"),
  stats: () => request<Stats>("/api/admin/stats"),
  health: () => request<Health>("/api/health"),
  profile: () => request<Profile>("/api/profile"),
};
