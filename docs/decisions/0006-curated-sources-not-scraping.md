# ADR-0006: Job data comes from curated boards and APIs, never scraping

- **Status:** accepted
- **Date:** Step 3
- **Context:** The obvious data source (scraping large job sites)
  violates their terms, breaks weekly, and looks bad in exactly the
  interviews this project targets. Greenhouse and Lever expose public
  board endpoints per company; Remotive and Adzuna offer APIs.
- **Decision:** We will ingest only from sources that publish their
  data for programmatic use, via a curated company-board list that is
  itself reviewable data (`app/ingestion/boards.py`).
- **Consequences:** Easier: legal cleanliness, stable schemas,
  recorded-shape tests that stay true, an interview-safe answer to
  "where does your data come from." Harder: coverage is bounded by the
  curated list — growing it is deliberate editorial work (and a good
  contributor task).
