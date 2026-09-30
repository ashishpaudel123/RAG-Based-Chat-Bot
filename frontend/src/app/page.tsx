"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatSidebar } from "@/components/ChatSidebar";
import { MessageBubble, TypingIndicator } from "@/components/MessageBubble";
import { FullPageLoader, Logo } from "@/components/ui";
import { api, type ConversationSummary, type Message } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";

const MAX_CHARS = 2000;
const SUGGESTIONS = [
  "How many days do I have to return a product?",
  "How much does delivery cost outside Kathmandu Valley?",
  "What does the warranty not cover?",
  "Which payment methods do you accept?",
];

export default function ChatPage() {
  const { user, ready, logout } = useRequireAuth();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingChat, setLoadingChat] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<{ text: string; retry?: string } | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const tmpCounter = useRef(0);

  const refreshList = useCallback(
    () =>
      api
        .listChats()
        .then(setConversations)
        .catch((e) => setError({ text: e instanceof Error ? e.message : "Could not load conversations" }))
        .finally(() => setListLoading(false)),
    [],
  );

  useEffect(() => {
    if (ready) refreshList();
  }, [ready, refreshList]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  async function openConversation(id: string) {
    setSidebarOpen(false);
    if (id === activeId) return;
    setActiveId(id);
    setError(null);
    setLoadingChat(true);
    setMessages([]);
    try {
      const detail = await api.getChat(id);
      setMessages(detail.messages);
    } catch (e) {
      setError({ text: e instanceof Error ? e.message : "Could not load conversation" });
    } finally {
      setLoadingChat(false);
    }
  }

  function newChat() {
    setActiveId(null);
    setMessages([]);
    setError(null);
    setSidebarOpen(false);
    inputRef.current?.focus();
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || sending) return;
    if (message.length > MAX_CHARS) {
      setError({ text: `Messages are limited to ${MAX_CHARS} characters.` });
      return;
    }
    setError(null);
    setSending(true);
    setInput("");
    const optimistic: Message = {
      id: `tmp-${++tmpCounter.current}`, role: "user", content: message, is_fallback: false, latency_ms: null,
      created_at: "", citations: [], feedback: null,
    };
    setMessages((prev) => [...prev, optimistic]);
    try {
      const res = await api.sendMessage(message, activeId);
      setMessages((prev) => [...prev.filter((m) => m.id !== optimistic.id), res.user_message, res.assistant_message]);
      if (!activeId) setActiveId(res.conversation_id);
      refreshList();
    } catch (e) {
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      setInput(message);
      setError({ text: e instanceof Error ? e.message : "Something went wrong", retry: message });
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  async function rename(id: string, title: string) {
    try {
      const updated = await api.renameChat(id, title);
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title: updated.title } : c)));
    } catch (e) {
      setError({ text: e instanceof Error ? e.message : "Could not rename conversation" });
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteChat(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (id === activeId) newChat();
    } catch (e) {
      setError({ text: e instanceof Error ? e.message : "Could not delete conversation" });
    }
  }

  if (!ready || !user) return <FullPageLoader />;

  const activeTitle = conversations.find((c) => c.id === activeId)?.title ?? "New conversation";
  const empty = !loadingChat && messages.length === 0;

  return (
    <div className="flex h-full overflow-hidden">
      {/* Sidebar: static on desktop, drawer on mobile */}
      <div className={`fixed inset-y-0 left-0 z-30 transition-transform md:static md:translate-x-0 ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}`}>
        <ChatSidebar user={user} conversations={conversations} activeId={activeId} loading={listLoading}
          onSelect={openConversation} onNew={newChat} onRename={rename} onDelete={remove} onLogout={logout} />
      </div>
      {sidebarOpen && <button aria-label="Close menu" className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={() => setSidebarOpen(false)} />}

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border bg-surface/80 px-4 py-3 backdrop-blur">
          <button type="button" className="btn-secondary px-2 md:hidden" onClick={() => setSidebarOpen(true)} aria-label="Open menu">☰</button>
          <h1 className="truncate text-sm font-semibold">{activeTitle}</h1>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-5 px-4 py-6">
            {loadingChat && <p className="py-10 text-center text-sm text-muted">Loading conversation…</p>}
            {empty && !sending && (
              <div className="flex flex-col items-center py-12 text-center">
                <Logo size={52} />
                <h2 className="mt-4 text-xl font-semibold">Hi {user.full_name.split(" ")[0]}, how can I help?</h2>
                <p className="mt-1.5 max-w-md text-sm text-muted">
                  Answers come from our approved knowledge base, with the sources shown so you can check them.
                </p>
                <div className="mt-6 grid w-full max-w-xl gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" onClick={() => send(s)}
                      className="rounded-xl border border-border bg-surface px-3.5 py-3 text-left text-sm transition hover:border-accent">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m}
                onUpdate={(updated) => setMessages((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))} />
            ))}
            {sending && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="border-t border-border bg-surface px-4 py-3">
          <div className="mx-auto max-w-3xl">
            {error && (
              <div role="alert" className="mb-2 flex items-center gap-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
                <span className="flex-1">{error.text}</span>
                {error.retry && (
                  <button type="button" className="font-medium underline" onClick={() => send(error.retry!)}>Retry</button>
                )}
                <button type="button" aria-label="Dismiss" onClick={() => setError(null)}>✕</button>
              </div>
            )}
            <form
              className="flex items-end gap-2 rounded-2xl border border-border bg-background p-2 focus-within:border-accent"
              onSubmit={(e) => { e.preventDefault(); send(input); }}
            >
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    send(input);
                  }
                }}
                rows={1}
                placeholder="Ask a question about our products, orders or policies…"
                className="max-h-40 min-h-[2.25rem] flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none"
                style={{ fieldSizing: "content" } as React.CSSProperties}
                maxLength={MAX_CHARS}
                disabled={sending}
                aria-label="Message"
              />
              <button type="submit" className="btn-primary h-9 px-3" disabled={sending || !input.trim()} aria-label="Send">
                {sending ? "…" : "Send"}
              </button>
            </form>
            <p className="mt-1.5 flex justify-between px-1 text-[11px] text-muted">
              <span>AI answers can be wrong. Check the sources for important decisions.</span>
              {input.length > MAX_CHARS * 0.8 && <span>{input.length}/{MAX_CHARS}</span>}
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
