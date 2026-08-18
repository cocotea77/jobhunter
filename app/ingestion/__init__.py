"""The ingestion package: fetching real job postings from public sources.

- sources.py   — one fetcher per source, all returning the same shape
- pipeline.py  — fetch everything, capture failures, dedupe, store
- boards.py    — the starter curated list of company boards
"""
