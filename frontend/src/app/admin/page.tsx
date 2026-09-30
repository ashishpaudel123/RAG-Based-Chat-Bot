"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, FullPageLoader, Logo, Spinner, formatBytes, formatDate } from "@/components/ui";
import {
  api,
  type Chunk,
  type DocumentInfo,
  type ErrorLog,
  type Health,
  type IndexRun,
  type Stats,
  type User,
} from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";

type Tab = "knowledge" | "overview" | "users" | "logs";

export default function AdminPage() {
  const { user, ready, logout } = useRequireAuth("admin");
  const [tab, setTab] = useState<Tab>("knowledge");
  if (!ready || !user) return <FullPageLoader />;

  const tabs: [Tab, string][] = [["knowledge", "Knowledge base"], ["overview", "Overview"], ["users", "Users"], ["logs", "Error logs"]];
  return (
    <div className="min-h-full">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <Logo size={30} />
          <h1 className="text-sm font-semibold">Admin dashboard</h1>
          <div className="ml-auto flex items-center gap-2">
            <Link href="/" className="btn-secondary">Back to chat</Link>
            <button type="button" className="btn-secondary" onClick={logout}>Sign out</button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4" aria-label="Admin sections">
          {tabs.map(([id, label]) => (
            <button key={id} type="button" onClick={() => setTab(id)}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm transition ${tab === id ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-foreground"}`}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        {tab === "knowledge" && <KnowledgeTab />}
        {tab === "overview" && <OverviewTab />}
        {tab === "users" && <UsersTab me={user} />}
        {tab === "logs" && <LogsTab />}
      </main>
    </div>
  );
}

function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <p role="alert" className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p>;
}

function Card({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mb-6 rounded-2xl border border-border bg-surface p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-3">
        <h2 className="text-base font-semibold">{title}</h2>
        <div className="ml-auto">{action}</div>
      </div>
      {children}
    </section>
  );
}

const msg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

// ---------------------------------------------------------------- knowledge
function KnowledgeTab() {
  const [docs, setDocs] = useState<DocumentInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<DocumentInfo | null>(null);
  const [viewing, setViewing] = useState<{ doc: DocumentInfo; chunks: Chunk[] } | null>(null);

  const load = useCallback(() => api.listDocuments().then(setDocs).catch((e) => setError(msg(e))), []);
  useEffect(() => { load(); }, [load]);

  async function run(label: string, fn: () => Promise<string | void>) {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      const note = await fn();
      if (note) setNotice(note);
      await load();
    } catch (e) {
      setError(msg(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <UploadCard onUploaded={(d) => { setNotice(d.status === "indexed" ? `Indexed “${d.title}” into ${d.chunk_count} chunk${d.chunk_count === 1 ? "" : "s"}.` : `Uploaded “${d.title}” but indexing failed: ${d.error}`); load(); }} />
      <Card
        title="Documents"
        action={
          <button type="button" className="btn-secondary" disabled={!!busy}
            onClick={() => confirm("Re-index the entire knowledge base? This re-embeds every document.") &&
              run("all", async () => {
                const r = await api.reindex();
                return `Re-indexed ${r.documents_indexed} documents into ${r.chunks_indexed} chunks in ${(r.duration_ms / 1000).toFixed(1)}s${r.failures ? ` (${r.failures} failed)` : ""}.`;
              })}>
            {busy === "all" && <Spinner />} Re-index all
          </button>
        }
      >
        <ErrorNote error={error} />
        {notice && <p className="mb-4 rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent">{notice}</p>}
        {docs === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : docs.length === 0 ? (
          <p className="text-sm text-muted">No documents yet. Upload approved policies, manuals or FAQs above.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted">
                <tr className="border-b border-border">
                  <th className="py-2 pr-3 font-medium">Document</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Chunks</th>
                  <th className="py-2 pr-3 font-medium">Version</th>
                  <th className="py-2 pr-3 font-medium">Updated</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id} className="border-b border-border last:border-0 align-top">
                    <td className="py-3 pr-3">
                      <p className="font-medium">{d.title}</p>
                      <p className="text-xs text-muted">{d.filename} · {formatBytes(d.size_bytes)}</p>
                      {d.tags.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{d.tags.map((t) => <Badge key={t}>{t}</Badge>)}</div>}
                      {d.error && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{d.error}</p>}
                    </td>
                    <td className="py-3 pr-3"><Badge tone={d.status === "indexed" ? "good" : d.status === "failed" ? "bad" : "warn"}>{d.status}</Badge></td>
                    <td className="py-3 pr-3">{d.chunk_count}</td>
                    <td className="py-3 pr-3">v{d.version}</td>
                    <td className="py-3 pr-3 whitespace-nowrap text-muted">{formatDate(d.updated_at)}</td>
                    <td className="py-3">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <button type="button" className="btn-secondary" onClick={async () => {
                          try { setViewing({ doc: d, chunks: await api.documentChunks(d.id) }); } catch (e) { setError(msg(e)); }
                        }}>Chunks</button>
                        <button type="button" className="btn-secondary" onClick={() => setEditing(d)}>Edit</button>
                        <button type="button" className="btn-secondary" disabled={!!busy}
                          onClick={() => run(d.id, async () => { await api.reindex(d.id); return `Re-indexed “${d.title}”.`; })}>
                          {busy === d.id && <Spinner />} Re-index
                        </button>
                        <button type="button" className="btn-danger" disabled={!!busy}
                          onClick={() => confirm(`Delete “${d.title}” from the knowledge base?`) &&
                            run(`del-${d.id}`, async () => { await api.deleteDocument(d.id); return `Deleted “${d.title}”.`; })}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {editing && (
        <EditDialog doc={editing} onClose={() => setEditing(null)}
          onSaved={(d) => { setEditing(null); setNotice(`Saved “${d.title}” (v${d.version}, ${d.status}).`); load(); }} />
      )}
      {viewing && (
        <Modal title={`${viewing.doc.title} — ${viewing.chunks.length} chunks`} onClose={() => setViewing(null)}>
          <ol className="space-y-3">
            {viewing.chunks.map((c) => (
              <li key={c.id} className="rounded-lg border border-border p-3 text-sm">
                <p className="mb-1 text-xs text-muted">#{c.chunk_index + 1}{c.section ? ` · ${c.section}` : ""}{c.page ? ` · page ${c.page}` : ""} · {c.text.length} chars</p>
                <p className="whitespace-pre-wrap leading-relaxed">{c.text}</p>
              </li>
            ))}
          </ol>
        </Modal>
      )}
    </>
  );
}

function UploadCard({ onUploaded }: { onUploaded: (d: DocumentInfo) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const doc = await api.uploadDocument(file, title.trim() || undefined, tags.trim() || undefined);
      setFile(null); setTitle(""); setTags("");
      if (fileRef.current) fileRef.current.value = "";
      onUploaded(doc);
    } catch (err) {
      setError(msg(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Upload approved document">
      <ErrorNote error={error} />
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-[2fr_1.5fr_1.5fr_auto] md:items-end">
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">File</span>
          <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" required
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-accent-soft file:px-3 file:py-2 file:text-sm file:font-medium file:text-accent" />
        </label>
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">Title <span className="font-normal text-muted">(optional)</span></span>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} placeholder="From file name" />
        </label>
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">Tags <span className="font-normal text-muted">(comma separated)</span></span>
          <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} maxLength={500} placeholder="policy, returns" />
        </label>
        <button type="submit" className="btn-primary h-[38px]" disabled={!file || busy}>{busy && <Spinner />} Upload & index</button>
      </form>
      <p className="mt-2 text-xs text-muted">PDF, DOCX, TXT or Markdown · max 10 MB · only upload documents approved for customer use.</p>
    </Card>
  );
}

function EditDialog({ doc, onClose, onSaved }: { doc: DocumentInfo; onClose: () => void; onSaved: (d: DocumentInfo) => void }) {
  const [title, setTitle] = useState(doc.title);
  const [tags, setTags] = useState(doc.tags.join(", "));
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.updateDocument(doc.id, { file, title, tags }));
    } catch (err) {
      setError(msg(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={`Edit “${doc.title}”`} onClose={onClose}>
      <form onSubmit={save} className="space-y-4">
        <ErrorNote error={error} />
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Title</span>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={255} /></label>
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Tags</span>
          <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} maxLength={500} /></label>
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Replace with a new version <span className="font-normal text-muted">(optional)</span></span>
          <input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm" /></label>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}>{busy && <Spinner />} Save & re-index</button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl border border-border bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-border px-5 py-3">
          <h3 className="truncate text-sm font-semibold">{title}</h3>
          <button type="button" className="ml-auto text-muted hover:text-foreground" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- overview
function OverviewTab() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [runs, setRuns] = useState<IndexRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.stats(), api.health(), api.indexRuns()])
      .then(([s, h, r]) => { setStats(s); setHealth(h); setRuns(r); })
      .catch((e) => setError(msg(e)));
  }, []);

  if (error) return <ErrorNote error={error} />;
  if (!stats || !health) return <p className="text-sm text-muted">Loading…</p>;
  const totalFeedback = stats.feedback_positive + stats.feedback_negative;
  const tiles: [string, string][] = [
    ["Users", String(stats.users)],
    ["Conversations", String(stats.conversations)],
    ["Messages", String(stats.messages)],
    ["Documents / chunks", `${stats.documents} / ${stats.chunks}`],
    ["Helpful rating", totalFeedback ? `${Math.round((stats.feedback_positive / totalFeedback) * 100)}% of ${totalFeedback}` : "—"],
    ["Fallback rate", `${(stats.fallback_rate * 100).toFixed(1)}%`],
    ["Avg. response time", stats.avg_latency_ms != null ? `${(stats.avg_latency_ms / 1000).toFixed(2)}s` : "—"],
    ["Errors (24h)", String(stats.errors_last_24h)],
  ];
  return (
    <>
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-border bg-surface p-4 shadow-sm">
            <p className="text-xs text-muted">{label}</p>
            <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
          </div>
        ))}
      </div>
      <Card title="System health">
        <div className="flex flex-wrap gap-2 text-sm">
          <Badge tone={health.status === "ok" ? "good" : "warn"}>overall: {health.status}</Badge>
          <Badge tone={health.database === "ok" ? "good" : "bad"}>database: {health.database}</Badge>
          <Badge tone={health.vector_store === "ok" ? "good" : "bad"}>vector store: {health.vector_store}</Badge>
          <Badge tone={health.llm_configured ? "good" : "bad"}>LLM: {health.llm_provider}{health.llm_configured ? "" : " (not configured)"}</Badge>
          <Badge>indexed chunks: {health.indexed_chunks}</Badge>
          <Badge>v{health.version}</Badge>
        </div>
      </Card>
      <Card title="Recent index runs">
        {runs.length === 0 ? <p className="text-sm text-muted">No re-index runs yet.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted">
                <tr className="border-b border-border">
                  {["When", "Scope", "Embedding model", "Chunk / overlap", "Docs", "Chunks", "Failures", "Time"].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-3 whitespace-nowrap">{formatDate(r.created_at)}</td>
                    <td className="py-2 pr-3">{r.scope === "full" ? "full" : "single document"}</td>
                    <td className="py-2 pr-3">{r.embedding_model} ({r.embedding_dimensions}d)</td>
                    <td className="py-2 pr-3">{r.chunk_size} / {r.chunk_overlap}</td>
                    <td className="py-2 pr-3">{r.documents_indexed}</td>
                    <td className="py-2 pr-3">{r.chunks_indexed}</td>
                    <td className="py-2 pr-3">{r.failures}</td>
                    <td className="py-2 pr-3">{(r.duration_ms / 1000).toFixed(1)}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

// -------------------------------------------------------------------- users
function UsersTab({ me }: { me: User }) {
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.listUsers().then(setUsers).catch((e) => setError(msg(e))); }, []);

  async function update(u: User, patch: { role?: "user" | "admin"; is_active?: boolean }) {
    setError(null);
    try {
      const updated = await api.updateUser(u.id, patch);
      setUsers((prev) => prev?.map((x) => (x.id === u.id ? updated : x)) ?? null);
    } catch (e) {
      setError(msg(e));
    }
  }

  return (
    <Card title="Users">
      <ErrorNote error={error} />
      {!users ? <p className="text-sm text-muted">Loading…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted">
              <tr className="border-b border-border">
                {["Name", "Email", "Role", "Status", "Joined", ""].map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-border last:border-0">
                  <td className="py-2.5 pr-3 font-medium">{u.full_name}{u.id === me.id && <span className="text-muted"> (you)</span>}</td>
                  <td className="py-2.5 pr-3">{u.email}</td>
                  <td className="py-2.5 pr-3"><Badge tone={u.role === "admin" ? "good" : "neutral"}>{u.role}</Badge></td>
                  <td className="py-2.5 pr-3"><Badge tone={u.is_active ? "good" : "bad"}>{u.is_active ? "active" : "disabled"}</Badge></td>
                  <td className="py-2.5 pr-3 whitespace-nowrap text-muted">{formatDate(u.created_at)}</td>
                  <td className="py-2.5">
                    {u.id !== me.id && (
                      <div className="flex justify-end gap-1.5">
                        <button type="button" className="btn-secondary" onClick={() => update(u, { role: u.role === "admin" ? "user" : "admin" })}>
                          {u.role === "admin" ? "Make user" : "Make admin"}
                        </button>
                        <button type="button" className={u.is_active ? "btn-danger" : "btn-secondary"} onClick={() => update(u, { is_active: !u.is_active })}>
                          {u.is_active ? "Disable" : "Enable"}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------- logs
function LogsTab() {
  const [logs, setLogs] = useState<ErrorLog[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => { api.logs().then(setLogs).catch((e) => setError(msg(e))); }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <Card title="Operational error logs" action={<button type="button" className="btn-secondary" onClick={load}>Refresh</button>}>
      <ErrorNote error={error} />
      {!logs ? <p className="text-sm text-muted">Loading…</p> : logs.length === 0 ? <p className="text-sm text-muted">No errors recorded. 🎉</p> : (
        <ul className="space-y-2">
          {logs.map((l) => (
            <li key={l.id} className="rounded-lg border border-border p-3 text-sm">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                <Badge tone={l.level === "error" ? "bad" : "warn"}>{l.level}</Badge>
                <span className="font-medium text-foreground">{l.source}</span>
                {l.path && <span>{l.path}</span>}
                <span className="ml-auto">{formatDate(l.created_at)}</span>
              </div>
              <p className="break-words font-mono text-xs">{l.message}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
