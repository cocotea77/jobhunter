"use client";

// The matches page: press the button, watch honest progress, read ranked
// results. The progress bar is real numbers from the match-jobs row —
// "Scoring match 5 of 8" — not a spinner guessing. Step 8's kind refusals
// (quota 429, budget 503) render as written.

import { useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  activeCandidate,
  type Match,
  type MatchJobStatus,
} from "@/lib/api";

function scoreClass(score: number | null): string {
  if (score === null) return "low";
  if (score >= 70) return "good";
  if (score >= 50) return "mid";
  return "low";
}

export default function MatchesPage() {
  const [candidateId, setCandidateId] = useState<number | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [job, setJob] = useState<MatchJobStatus | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [tailoring, setTailoring] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const id = activeCandidate();
    setCandidateId(id);
    if (id) api.matches(id).then(setMatches).catch(() => setMatches([]));
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  async function start() {
    if (!candidateId) return;
    setBanner(null);
    try {
      const queued = await api.startMatching(candidateId);
      poll(queued.match_job_id);
    } catch (error) {
      // 429 (today's allowance) and 503 (budget) arrive here with the
      // backend's kind sentence — show it exactly as written.
      setBanner(error instanceof ApiError ? error.message : "Could not start.");
    }
  }

  function poll(jobId: number) {
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(async () => {
      if (!candidateId) return;
      const status = await api.matchJob(candidateId, jobId).catch(() => null);
      if (!status) return;
      setJob(status);
      if (status.status === "done" || status.status === "failed") {
        if (timer.current) clearInterval(timer.current);
        if (status.status === "done") {
          setMatches(await api.matches(candidateId));
        } else {
          setBanner(status.error ?? "Matching failed.");
        }
        setJob(status.status === "done" ? null : status);
      }
    }, 1000);
  }

  async function tailor(jobId: number) {
    if (!candidateId) return;
    setTailoring(jobId);
    setBanner(null);
    try {
      await api.tailor(candidateId, jobId);
      setBanner("Tailored resume saved — see the Tailored page.");
    } catch (error) {
      setBanner(error instanceof ApiError ? error.message : "Tailoring failed.");
    } finally {
      setTailoring(null);
    }
  }

  if (!candidateId) {
    return (
      <main className="card">
        <h2>Matches</h2>
        <p className="hint">
          Upload a resume on the <a href="/">home page</a> first.
        </p>
      </main>
    );
  }

  const running = job && (job.status === "queued" || job.status === "running");

  return (
    <main>
      <section className="card">
        <div className="row">
          <h2 style={{ margin: 0, flex: 1 }}>Matches</h2>
          <button onClick={start} disabled={!!running}>
            {running ? "Matching…" : "Run matching"}
          </button>
        </div>
        {running && (
          <div style={{ marginTop: 12 }}>
            <p className="hint">
              {job.total_to_score > 0
                ? `Scoring match ${job.scored} of ${job.total_to_score}…`
                : "Finding the closest postings…"}
            </p>
            <div className="progress">
              <div
                style={{
                  width:
                    job.total_to_score > 0
                      ? `${(100 * job.scored) / job.total_to_score}%`
                      : "8%",
                }}
              />
            </div>
          </div>
        )}
        {banner && <div className="banner info">{banner}</div>}
      </section>

      {matches.map((match) => (
        <section className="card" key={match.job_id}>
          <div className="row">
            <span className={`score ${scoreClass(match.llm_score)}`}>
              {match.llm_score ?? "–"}
            </span>
            <div style={{ flex: 1 }}>
              <strong>{match.title}</strong>
              <div className="hint">
                {match.company}
                {match.location ? ` · ${match.location}` : ""} ·{" "}
                <a href={match.url} target="_blank" rel="noreferrer">
                  view posting
                </a>
              </div>
            </div>
            <button
              className="quiet"
              onClick={() => tailor(match.job_id)}
              disabled={tailoring === match.job_id}
            >
              {tailoring === match.job_id ? "Tailoring…" : "Tailor resume"}
            </button>
          </div>

          {match.analysis ? (
            <div style={{ marginTop: 10 }}>
              <p>{match.analysis.verdict}</p>
              <p className="hint">Strengths:</p>
              <ul className="list-plain">
                {match.analysis.strengths.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <p className="hint">Honest gaps:</p>
              <ul className="list-plain">
                {match.analysis.gaps.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="hint" style={{ marginTop: 10 }}>
              Ranked by meaning similarity ({match.vector_score.toFixed(2)}) —
              outside the AI-explained top group.
            </p>
          )}
        </section>
      ))}
    </main>
  );
}
