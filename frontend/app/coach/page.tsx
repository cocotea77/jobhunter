"use client";

// The coach page: the tool-using agent, visible. Each assistant message
// shows which tools it used and how long the turn took — the same
// metadata the orchestrator persists. Transparency is a feature: users
// (and interviewers) can SEE the agent look things up.

import { useEffect, useRef, useState } from "react";
import { ApiError, api, activeCandidate, type ChatTurn } from "@/lib/api";

type Message = {
  role: "user" | "assistant";
  text: string;
  tools?: string[];
  ms?: number;
};

export default function CoachPage() {
  const [candidateId, setCandidateId] = useState<number | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setCandidateId(activeCandidate());
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    if (!candidateId || !draft.trim() || busy) return;
    const text = draft.trim();
    setDraft("");
    setBanner(null);
    setMessages((current) => [...current, { role: "user", text }]);
    setBusy(true);
    try {
      const turn: ChatTurn = await api.chat(candidateId, text, sessionId);
      setSessionId(turn.session_id);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: turn.reply,
          tools: turn.tools_used,
          ms: turn.latency_ms,
        },
      ]);
    } catch (error) {
      setBanner(error instanceof ApiError ? error.message : "The coach is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  if (!candidateId) {
    return (
      <main className="card">
        <h2>Coach</h2>
        <p className="hint">
          Upload a resume on the <a href="/">home page</a> first.
        </p>
      </main>
    );
  }

  return (
    <main>
      <section className="card">
        <div className="row">
          <h2 style={{ margin: 0, flex: 1 }}>Coach</h2>
          <button
            className="quiet"
            onClick={() => {
              setSessionId(null);
              setMessages([]);
            }}
          >
            New conversation
          </button>
        </div>
        <p className="hint">
          Ask about your matches, a specific job, or request a tailored
          resume. The coach looks things up rather than guessing — the tools
          it used appear under each answer.
        </p>

        <div className="chat" style={{ margin: "14px 0" }}>
          {messages.map((message, index) => (
            <div className={`msg ${message.role}`} key={index}>
              {message.text}
              {message.role === "assistant" && (
                <span className="meta">
                  {message.tools && message.tools.length > 0
                    ? `tools: ${message.tools.join(", ")} · `
                    : "no tools · "}
                  {message.ms} ms
                </span>
              )}
            </div>
          ))}
          {busy && <div className="msg assistant">…</div>}
          <div ref={bottom} />
        </div>

        {banner && <div className="banner info">{banner}</div>}

        <div className="row">
          <input
            type="text"
            placeholder="What are my top matches?"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && send()}
          />
          <button onClick={send} disabled={busy || !draft.trim()}>
            Send
          </button>
        </div>
      </section>
    </main>
  );
}
