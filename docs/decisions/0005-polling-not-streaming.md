# ADR-0005: Progress is polled, not streamed

- **Status:** accepted
- **Date:** Step 9
- **Context:** Matching takes up to a minute; the page needs progress.
  WebSockets and server-sent events are strictly more capable; both add
  connection state, proxy quirks, and reconnection logic.
- **Decision:** We will store progress as real numbers in the
  `match_jobs` row and have the page GET it once a second until a
  terminal state.
- **Consequences:** Easier: zero new infrastructure; works through any
  proxy and phone network; the progress numbers double as the
  operator's investigation trail. Harder: sub-second liveliness is
  impossible and each poll costs a request — both irrelevant at a
  once-per-second progress bar. Revisit only if the product ever
  streams tokens.
