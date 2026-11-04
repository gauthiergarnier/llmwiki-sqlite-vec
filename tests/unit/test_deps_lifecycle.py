"""Regression coverage for hosted request connection lifecycle."""

import asyncio
from types import SimpleNamespace

import pytest


class _Transaction:
    def __init__(self, *, fail_start: bool = False):
        self.fail_start = fail_start
        self.exit_type = None

    async def __aenter__(self):
        if self.fail_start:
            raise RuntimeError("begin failed")
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_type = exc_type


class _Connection:
    def __init__(self, transaction: _Transaction):
        self._transaction = transaction
        self.executed = []

    def transaction(self):
        return self._transaction

    async def execute(self, query, *args):
        self.executed.append((query, args))


class _Pool:
    def __init__(self, connection: _Connection):
        self.connection = connection
        self.released = []

    async def acquire(self):
        return self.connection

    async def release(self, connection):
        self.released.append(connection)


def _request():
    state = SimpleNamespace(auth_provider=None, sqlite_db=None)
    return SimpleNamespace(app=SimpleNamespace(state=state))


async def test_scoped_db_releases_connection_when_transaction_start_fails(monkeypatch):
    import auth
    from deps import get_scoped_db

    async def current_user(request):
        return "user-a"

    monkeypatch.setattr(auth, "get_current_user", current_user)
    transaction = _Transaction(fail_start=True)
    connection = _Connection(transaction)
    pool = _Pool(connection)
    dependency = get_scoped_db(_request(), pool)

    with pytest.raises(RuntimeError, match="begin failed"):
        await anext(dependency)

    assert pool.released == [connection]


async def test_scoped_db_rolls_back_and_releases_on_request_cancellation(monkeypatch):
    import auth
    from deps import get_scoped_db

    async def current_user(request):
        return "user-a"

    monkeypatch.setattr(auth, "get_current_user", current_user)
    transaction = _Transaction()
    connection = _Connection(transaction)
    pool = _Pool(connection)
    dependency = get_scoped_db(_request(), pool)

    scoped = await anext(dependency)
    assert scoped.user_id == "user-a"

    with pytest.raises(asyncio.CancelledError):
        await dependency.athrow(asyncio.CancelledError())

    assert transaction.exit_type is asyncio.CancelledError
    assert pool.released == [connection]


async def test_scoped_db_pool_acquisition_is_bounded(monkeypatch):
    import auth
    import deps

    acquire_cancelled = asyncio.Event()

    class StalledPool:
        async def acquire(self):
            try:
                await asyncio.Event().wait()
            finally:
                acquire_cancelled.set()

    async def current_user(request):
        return "user-a"

    monkeypatch.setattr(auth, "get_current_user", current_user)
    monkeypatch.setattr(deps, "DB_ACQUIRE_TIMEOUT_SECONDS", 0.01)
    dependency = deps.get_scoped_db(_request(), StalledPool())

    with pytest.raises(TimeoutError):
        await anext(dependency)

    assert acquire_cancelled.is_set()
