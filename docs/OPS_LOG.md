# JobHunter Operations Log

One entry per incident or notable operational event, newest first.
An incident is anything that surprised the operator: an outage, a wrong
answer shown to a user, a cost spike, a failed deploy, a security probe.

The ritual (fill it in within a day, while it is fresh):

---

## YYYY-MM-DD — one-line title

- **Noticed by:** (uptime alert / Sentry / a user / me, doing X)
- **Impact:** who saw what, for how long
- **Timeline:** first symptom -> diagnosis -> fix live (times, UTC)
- **Root cause:** the sentence that names the actual mechanism
- **Fix:** what changed (link the Pull Request)
- **Prevention:** the test or golden case that now pins this
  (link it — an incident without a pin will return)

---

*Why keep this file in the repository: it is the difference between
"I deployed a project" and "I operated a service." Interviewers ask for
incident stories; this file is where they come from, with dates.*
