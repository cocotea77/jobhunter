"use client";

// The navigation bar: who you are, where you can go, sign out.
// A client component because it asks /me and reacts to the answer.

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Me } from "@/lib/api";

export function Nav() {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);

  async function signOut() {
    await api.logout().catch(() => undefined);
    window.location.href = "/";
  }

  return (
    <nav className="nav">
      <Link className="brand" href="/">
        JobHunter
      </Link>
      <Link className="link" href="/matches">
        Matches
      </Link>
      <Link className="link" href="/coach">
        Coach
      </Link>
      <Link className="link" href="/tailored">
        Tailored
      </Link>
      <span className="spacer" />
      {me ? (
        <>
          <span className="who">{me.email}</span>
          <button className="quiet" onClick={signOut}>
            Sign out
          </button>
        </>
      ) : (
        <span className="who">not signed in</span>
      )}
    </nav>
  );
}
