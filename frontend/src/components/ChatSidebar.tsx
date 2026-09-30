"use client";

import Link from "next/link";
import { useState } from "react";
import type { ConversationSummary, User } from "@/lib/api";
import { Logo } from "./ui";

interface Props {
  user: User;
  conversations: ConversationSummary[];
  activeId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  onLogout: () => void;
}

export function ChatSidebar({ user, conversations, activeId, loading, onSelect, onNew, onRename, onDelete, onLogout }: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  return (
    <aside className="flex h-full w-72 flex-col border-r border-border bg-surface">
      <div className="flex items-center gap-2.5 px-4 py-4">
        <Logo size={30} />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">Customer Service</p>
          <p className="text-xs text-muted">AI assistant</p>
        </div>
      </div>
      <div className="px-3">
        <button type="button" onClick={onNew} className="btn-primary w-full">
          <span aria-hidden>＋</span> New chat
        </button>
      </div>
      <nav className="mt-4 flex-1 overflow-y-auto px-2 pb-2" aria-label="Conversations">
        <p className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-muted">History</p>
        {loading && <p className="px-2 py-2 text-sm text-muted">Loading…</p>}
        {!loading && conversations.length === 0 && (
          <p className="px-2 py-2 text-sm text-muted">No conversations yet.</p>
        )}
        <ul className="space-y-0.5">
          {conversations.map((c) => (
            <li key={c.id} className="group relative">
              {editing === c.id ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (draft.trim()) onRename(c.id, draft.trim());
                    setEditing(null);
                  }}
                >
                  <input autoFocus className="input py-1.5" value={draft} maxLength={200}
                    onChange={(e) => setDraft(e.target.value)} onBlur={() => setEditing(null)}
                    onKeyDown={(e) => e.key === "Escape" && setEditing(null)} />
                </form>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    className={`w-full truncate rounded-lg px-2.5 py-2 pr-14 text-left text-sm transition ${
                      c.id === activeId ? "bg-accent-soft font-medium text-accent" : "hover:bg-background"
                    }`}
                    title={c.title}
                  >
                    {c.title}
                  </button>
                  <div className="absolute right-1 top-1/2 hidden -translate-y-1/2 gap-0.5 group-hover:flex group-focus-within:flex">
                    <IconButton label="Rename" onClick={() => { setDraft(c.title); setEditing(c.id); }}>✎</IconButton>
                    <IconButton label="Delete" onClick={() => { if (confirm(`Delete “${c.title}”?`)) onDelete(c.id); }}>🗑</IconButton>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      </nav>
      <div className="border-t border-border p-3">
        {user.role === "admin" && (
          <Link href="/admin" className="btn-secondary mb-2 w-full">Admin dashboard</Link>
        )}
        <div className="flex items-center gap-2.5 px-1">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-background text-sm font-semibold">
            {user.full_name.charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{user.full_name}</p>
            <p className="truncate text-xs text-muted">{user.email}</p>
          </div>
          <button type="button" onClick={onLogout} className="text-xs text-muted hover:text-foreground hover:underline">
            Sign out
          </button>
        </div>
      </div>
    </aside>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className="rounded-md px-1.5 py-0.5 text-xs text-muted hover:bg-surface hover:text-foreground">
      {children}
    </button>
  );
}
