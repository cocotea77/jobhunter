"use client";

// The tailored page: every saved tailoring, with its honesty on display.
// gaps_not_claimed and the change log are shown as prominently as the
// content itself — the product's promise is that it never lies for you,
// and this page is where that promise is visible.

import { useEffect, useState } from "react";
import { api, activeCandidate, type Tailored } from "@/lib/api";

export default function TailoredPage() {
  const [candidateId, setCandidateId] = useState<number | null>(null);
  const [items, setItems] = useState<Tailored[]>([]);

  useEffect(() => {
    const id = activeCandidate();
    setCandidateId(id);
    if (id) api.tailored(id).then(setItems).catch(() => setItems([]));
  }, []);

  if (!candidateId) {
    return (
      <main className="card">
        <h2>Tailored resumes</h2>
        <p className="hint">
          Upload a resume on the <a href="/">home page</a> first.
        </p>
      </main>
    );
  }

  return (
    <main>
      {items.length === 0 && (
        <section className="card">
          <h2>Tailored resumes</h2>
          <p className="hint">
            Nothing yet — press “Tailor resume” on a match, or ask the coach.
          </p>
        </section>
      )}

      {items.map((item) => (
        <section className="card" key={item.id}>
          <h2>
            {item.title} · {item.company}
          </h2>
          <p>{item.content.target_summary}</p>

          <p className="hint">Skills, reordered for this job:</p>
          <p>
            {item.content.skills_ordered.map((skill) => (
              <span className="pill" key={skill}>
                {skill}
              </span>
            ))}
          </p>

          <p className="hint">Experience, rewritten toward the posting:</p>
          <ul className="list-plain">
            {item.content.experience_bullets.map((bullet) => (
              <li key={bullet}>{bullet}</li>
            ))}
          </ul>

          <div className="banner info">
            <strong>Not claimed (honest gaps):</strong>{" "}
            {item.content.gaps_not_claimed.join("; ")}
          </div>

          <details>
            <summary className="hint">What was changed, and why</summary>
            <ul className="list-plain">
              {item.content.change_log.map((change) => (
                <li key={change}>{change}</li>
              ))}
            </ul>
          </details>
        </section>
      ))}
    </main>
  );
}
