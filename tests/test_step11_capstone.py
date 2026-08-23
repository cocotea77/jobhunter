"""Step 11 tests: the capstone artifacts, held to their own standards.

The wrap-up step produces prose and scripts rather than features — and
prose rots faster than code, because nothing fails when it drifts. So
these tests make the paperwork fail like code: the README's evidence
links must point at files that exist, the ADRs must carry the fields the
template demands, the drill must actually pass against the real
database, and the CI workflow must run it.
"""

import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).parent.parent


# --- the README's claims must point at real evidence -------------------------


def test_readme_evidence_links_resolve():
    """Every relative link in README.md must point at a file or folder
    that exists — a claims table with dead links is worse than none."""
    readme = (ROOT / "README.md").read_text()
    links = re.findall(r"\]\(((?!https?://)[^)#]+)\)", readme)
    assert links, "the README must contain relative evidence links"
    missing = [link for link in links if not (ROOT / link).exists()]
    assert not missing, f"README links to nothing: {missing}"


def test_readme_names_the_core_claims():
    readme = (ROOT / "README.md").read_text()
    for phrase in (
        "gaps_not_claimed",
        "hostile suite",
        "regression",
        "FAKE_AI",
        "backup_restore_drill",
    ):
        assert phrase in readme, f"README no longer states the claim: {phrase}"


# --- the decision records ----------------------------------------------------


def test_every_adr_carries_status_context_decision_consequences():
    decisions = sorted((ROOT / "docs" / "decisions").glob("0*.md"))
    assert len(decisions) >= 6, "the six founding ADRs must exist"
    for path in decisions:
        text = path.read_text()
        for field in ("**Status:**", "**Context:**", "**Decision:**", "**Consequences:**"):
            assert field in text, f"{path.name} is missing {field}"
        assert "We will" in text, (
            f"{path.name}: a decision is written in the active voice"
        )


# --- the drill: run it for real ---------------------------------------------


def _database_is_running() -> bool:
    import asyncio

    import asyncpg

    from app.config import settings

    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    async def probe() -> None:
        connection = await asyncpg.connect(url, timeout=2)
        await connection.close()

    try:
        asyncio.run(probe())
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _database_is_running(),
    reason="database is not running — start it with: docker compose up -d",
)
def test_backup_restore_drill_passes_against_the_real_database():
    """Not a syntax check — the actual drill: dump, restore into a
    scratch database, compare bookmark, table count, rows, extension."""
    result = subprocess.run(
        ["sh", str(ROOT / "scripts" / "backup_restore_drill.sh")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"drill failed:\n{result.stdout}\n{result.stderr}"
    assert "DRILL PASSED" in result.stdout


def test_ci_runs_the_drill():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "backup_restore_drill.sh" in workflow, (
        "the drill must run in CI — restorability is a gate, not a hope"
    )


# --- dependency updates flow through the same gate ---------------------------


def test_dependabot_covers_all_three_ecosystems():
    config = (ROOT / ".github" / "dependabot.yml").read_text()
    for ecosystem in ('"pip"', '"npm"', '"github-actions"'):
        assert ecosystem in config, f"dependabot must watch {ecosystem}"
    assert '"/frontend"' in config, "npm updates must target the frontend folder"


# --- the smoke script stays honest about what it is --------------------------


def test_smoke_load_script_declares_itself_and_reports_percentiles():
    script = (ROOT / "scripts" / "smoke_load.py").read_text()
    assert "SMOKE" in script and "not a stress test" in script
    assert "p95" in script


# --- the version decision, pinned -------------------------------------------


def test_capstone_did_not_bump_the_product_version():
    """Step 11 changes paperwork, not the product; version numbers
    describe the product. This test pins that decision (see the Step 11
    document's semantic-versioning definition)."""
    from app.config import settings

    assert settings.version == "1.0.0"
