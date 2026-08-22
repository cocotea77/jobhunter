"use client";

// The landing page for emailed sign-in links. In production the link in
// the email points HERE (the frontend origin), this page redeems the
// token through the same-origin proxy, and the session cookie therefore
// lands on the origin the browser actually uses. (Sending users to the
// backend's address instead would set the cookie on the wrong origin —
// the bug this page exists to prevent.)

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

function VerifyInner() {
  const params = useSearchParams();
  const [state, setState] = useState<"working" | "ok" | "failed">("working");
  const [detail, setDetail] = useState("");

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setState("failed");
      setDetail("The link is missing its token.");
      return;
    }
    api
      .verify(token)
      .then(() => {
        setState("ok");
        setTimeout(() => (window.location.href = "/"), 800);
      })
      .catch((error: Error) => {
        setState("failed");
        setDetail(error.message);
      });
  }, [params]);

  return (
    <main className="card">
      <h2>Signing you in…</h2>
      {state === "ok" && <div className="banner ok">Signed in — taking you home.</div>}
      {state === "failed" && (
        <div className="banner error">
          {detail} Request a fresh link from the <a href="/">home page</a>.
        </div>
      )}
    </main>
  );
}

export default function VerifyPage() {
  return (
    <Suspense>
      <VerifyInner />
    </Suspense>
  );
}
