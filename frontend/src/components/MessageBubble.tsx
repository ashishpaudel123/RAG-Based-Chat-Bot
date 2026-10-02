"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type Citation, type Message } from "@/lib/api";
import { Logo } from "./ui";

const SOURCE_LABEL: Record<string, string> = {
  constitution: "Constitution", act: "Act", amendment: "Amendment", regulation: "Regulation",
  directive: "Directive", circular: "Circular", official_notice: "Notice", form: "Form",
  court_decision: "Court", dao_charter: "Office charter", local_notice: "Local notice",
  official_portal: "Official", secondary: "Secondary", faq: "FAQ", informal: "Informal",
};

export function MessageBubble({ message, onUpdate }: { message: Message; onUpdate?: (m: Message) => void }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-sm text-white dark:text-black">
          {message.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex gap-3">
      <Logo size={30} />
      <div className="min-w-0 max-w-[85%] flex-1">
        <div className="rounded-2xl rounded-tl-md border border-border bg-surface px-4 py-3 text-sm shadow-sm">
          {(() => {
            const ne = message.language != null && message.language !== "en";
            const label = message.is_fallback
              ? ne ? "आधिकारिक स्रोतमा भेटिएन" : "Not found in the knowledge base"
              : message.kind === "clarification"
                ? ne ? "केही विवरण चाहियो" : "A few details needed"
                : message.confidence === "LOW"
                  ? ne ? "कम निश्चितता — सम्बन्धित कार्यालयमा पुष्टि गर्नुहोस्" : "Low confidence — please verify with the relevant office"
                  : null;
            return label ? (
              <p className="mb-2 inline-flex items-center gap-1.5 rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                {label}
              </p>
            ) : null;
          })()}
          <div className="prose-chat">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer nofollow">{children}</a> }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
          {message.citations.length > 0 && <Sources citations={message.citations} />}
        </div>
        {onUpdate && message.id && !message.id.startsWith("tmp-") && (
          <FeedbackBar message={message} onUpdate={onUpdate} />
        )}
      </div>
    </div>
  );
}

function Sources({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="mt-3 border-t border-border pt-2.5">
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Sources</p>
      <ul className="space-y-1.5">
        {citations.map((c) => {
          const location = [c.legal_reference, c.section, c.page ? `page ${c.page}` : null, c.district]
            .filter(Boolean).join(" · ");
          const expanded = open === c.rank;
          return (
            <li key={`${c.rank}-${c.chunk_id}`} className="rounded-lg bg-background text-xs">
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : c.rank)}
                className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
                aria-expanded={expanded}
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-accent-soft font-semibold text-accent">
                  {c.rank}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {c.source_type && SOURCE_LABEL[c.source_type] && (
                    <span className="mr-1.5 rounded bg-surface px-1 py-px text-[10px] font-semibold uppercase tracking-wide text-muted">
                      {SOURCE_LABEL[c.source_type]}
                    </span>
                  )}
                  <span className="font-medium">{c.document_title}</span>
                  {location && <span className="text-muted"> — {location}</span>}
                  {c.validity_status && c.validity_status !== "current" && (
                    <span className="ml-1.5 rounded bg-amber-50 px-1 text-[10px] font-semibold text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
                      {c.validity_status}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-muted" title="Retrieval similarity">{Math.round(c.score * 100)}%</span>
                <span className="shrink-0 text-muted">{expanded ? "▴" : "▾"}</span>
              </button>
              {expanded && (
                <div className="border-t border-border px-2.5 py-2">
                  <p className="whitespace-pre-wrap leading-relaxed text-muted">{c.snippet}</p>
                  {(c.source_url || c.last_verified || c.effective_from) && (
                    <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
                      {c.effective_from && <span>Effective from: {c.effective_from}</span>}
                      {c.last_verified && <span>Last verified: {c.last_verified}</span>}
                      {c.source_url && /^https?:\/\//.test(c.source_url) && (
                        <a href={c.source_url} target="_blank" rel="noopener noreferrer nofollow"
                          className="font-medium text-accent hover:underline">
                          Official source ↗
                        </a>
                      )}
                    </p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function FeedbackBar({ message, onUpdate }: { message: Message; onUpdate: (m: Message) => void }) {
  const [busy, setBusy] = useState(false);
  const [askComment, setAskComment] = useState(false);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const rating = message.feedback?.rating;

  async function send(value: 1 | -1, text?: string) {
    setBusy(true);
    setError(null);
    try {
      const feedback = await api.sendFeedback(message.id, value, text);
      onUpdate({ ...message, feedback });
      setAskComment(value === -1 && text === undefined);
      if (text !== undefined) setComment("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save feedback");
    } finally {
      setBusy(false);
    }
  }

  const btn = (active: boolean) =>
    `rounded-md p-1 transition hover:bg-surface ${active ? "text-accent" : "text-muted"} disabled:opacity-50`;

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1 pl-1 text-xs text-muted">
      <button type="button" className={btn(rating === 1)} disabled={busy} onClick={() => send(1)} aria-label="Helpful"
        aria-pressed={rating === 1} title="Helpful">
        <Thumb up />
      </button>
      <button type="button" className={btn(rating === -1)} disabled={busy} onClick={() => send(-1)} aria-label="Not helpful"
        aria-pressed={rating === -1} title="Not helpful">
        <Thumb />
      </button>
      {rating && !askComment && <span>Thanks for your feedback</span>}
      {message.latency_ms != null && <span className="ml-auto">{(message.latency_ms / 1000).toFixed(1)}s</span>}
      {askComment && (
        <form
          className="mt-1 flex w-full gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send(-1, comment.trim());
          }}
        >
          <input className="input py-1 text-xs" placeholder="What was wrong? (optional)" value={comment}
            onChange={(e) => setComment(e.target.value)} maxLength={1000} />
          <button className="btn-secondary py-1 text-xs" disabled={busy}>Send</button>
          <button type="button" className="text-xs text-muted hover:underline" onClick={() => setAskComment(false)}>Skip</button>
        </form>
      )}
      {error && <span className="text-red-600">{error}</span>}
    </div>
  );
}

function Thumb({ up = false }: { up?: boolean }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" style={up ? undefined : { transform: "rotate(180deg)" }}>
      <path d="M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
    </svg>
  );
}

export function TypingIndicator() {
  return (
    <div className="flex gap-3">
      <Logo size={30} />
      <div className="typing flex items-center gap-1 rounded-2xl rounded-tl-md border border-border bg-surface px-4 py-3.5 shadow-sm"
        aria-label="Assistant is thinking">
        <span className="h-1.5 w-1.5 rounded-full bg-muted" />
        <span className="h-1.5 w-1.5 rounded-full bg-muted" />
        <span className="h-1.5 w-1.5 rounded-full bg-muted" />
      </div>
    </div>
  );
}
