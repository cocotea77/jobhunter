# This file does two jobs.
#
# 1. Its presence at the project root tells pytest where the project
#    begins, so test files can write "from app.config import ..." on any
#    machine, including GitHub's checking computer.
#
# 2. The fixture below fixes, AT THE ROOT, a bug family that bit this
#    project four separate times before being cured here: the
#    application's database engine pools connections, and each pooled
#    connection belongs to the event loop that created it. Tests create
#    many short-lived loops (each asyncio.run and each TestClient block
#    is one), so a test could inherit a connection whose loop no longer
#    exists and explode with "attached to a different loop" — but only
#    in certain test ORDERS, which is what made it flaky. The fixture
#    discards the pool before every test (dispose(close=False):
#    "forget those connections; do not try to close them — their loop is
#    gone"). Fresh test, fresh pool, deterministic suite.
#
#    The lesson worth keeping: when the same bug appears a third time in
#    different clothes, stop patching occurrences and fix the mechanism.

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _fresh_connection_pool():
    from app.db import engine

    asyncio.run(engine.dispose(close=False))
    yield
