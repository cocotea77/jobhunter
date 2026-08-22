"use client";

// The home page: the front door. Three cards — system status (the health
// endpoint, humanized), sign-in by email link, and the consented resume
// upload with the candidate selector the other pages rely on.

import { useEffect, useState } from "react";
import {
  ApiError,
  api,
  activeCandidate,
  setActiveCandidate,
  type Candidate,
  type Health,
  type Me,
} from "@/lib/api";

export default function HomePage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [active, setActive] = useState<number | null>(null);

  const [email, setEmail] = useState("");
  const [devLink, setDevLink] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<{ kind: string; text: string } | null>(null);

  async function refresh() {
    api.health().then(setHealth).catch(() => setHealth(null));
    try {
      setMe(await api.me());
      setCandidates(await api.candidates());
      setActive(activeCandidate());
    } catch {
      setMe(null);
      setCandidates([]);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function requestLink() {
    setBanner(null);
    try {
      const result = await api.requestLink(email);
      setSent(true);
      setDevLink(result.dev_link ?? null);
    } catch (error) {
      setBanner({ kind: "error", text: (error as Error).message });
    }
  }

  // Development convenience: the backend returns the link directly, so
  // one click completes sign-in without an email service. In production
  // this button never appears — the link arrives by email instead.
  async function useDevLink() {
    if (!devLink) return;
    const token = devLink.split("token=")[1];
    try {
      await api.verify(token);
      await refresh();
      setBanner({ kind: "ok", text: "Signed in." });
    } catch (error) {
      setBanner({ kind: "error", text: (error as Error).message });
    }
  }

  async function upload() {
    if (!file) return;
    setBusy(true);
    setBanner(null);
    try {
      const created = await api.upload(file, consent);
      setActiveCandidate(created.id);
      setActive(created.id);
      setCandidates(await api.candidates());
      setBanner({
        kind: "ok",
        text: `Resume understood: ${created.name}. Head to Matches.`,
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Upload failed.";
      setBanner({ kind: "error", text: message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <section className="card">
        <h2>System status</h2>
        {health ? (
          <p className="hint">
            {health.status === "ok" ? "All systems healthy." : "Degraded."}{" "}
            {health.jobs_indexed !== null &&
              `${health.jobs_indexed.toLocaleString()} job postings indexed. `}
            {health.budget.exhausted
              ? "Today's AI budget is used up — AI features resume at midnight UTC."
              : "AI features available."}
          </p>
        ) : (
          <p className="hint">Checking…</p>
        )}
      </section>

      {!me && (
        <section className="card">
          <h2>Sign in</h2>
          <p className="hint">
            No password — we email you a one-time sign-in link, valid for 15
            minutes.
          </p>
          <div className="row">
            <input
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <button onClick={requestLink} disabled={!email.includes("@")}>
              Email me a link
            </button>
          </div>
          {sent && !devLink && (
            <div className="banner ok">Check your email for the link.</div>
          )}
          {devLink && (
            <div className="banner info">
              Development mode: no email is sent.{" "}
              <button onClick={useDevLink}>Use the link now</button>
            </div>
          )}
        </section>
      )}

      {me && (
        <section className="card">
          <h2>Your resume</h2>
          <p className="hint">
            PDF or plain text. We read it, build an honest profile (nothing
            invented), and match it against real postings.
          </p>
          <div className="row">
            <input
              type="text"
              readOnly
              value={file ? file.name : "no file chosen"}
            />
            <input
              id="file"
              type="file"
              accept=".pdf,.txt,.md"
              style={{ display: "none" }}
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <button
              className="quiet"
              onClick={() => document.getElementById("file")?.click()}
            >
              Choose file
            </button>
            <button onClick={upload} disabled={!file || !consent || busy}>
              {busy ? "Reading…" : "Upload"}
            </button>
          </div>
          <label className="hint" style={{ display: "block", marginTop: 10 }}>
            <input
              type="checkbox"
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
            />{" "}
            I agree that this resume will be processed and stored as described
            in the <a href="/api/privacy">privacy notes</a>.
          </label>

          {candidates.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <p className="hint">Working with:</p>
              <div className="row">
                {candidates.map((candidate) => (
                  <button
                    key={candidate.id}
                    className={candidate.id === active ? "" : "quiet"}
                    onClick={() => {
                      setActiveCandidate(candidate.id);
                      setActive(candidate.id);
                    }}
                  >
                    {candidate.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {banner && <div className={`banner ${banner.kind}`}>{banner.text}</div>}
    </main>
  );
}
