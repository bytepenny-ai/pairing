"""app/services/instance_count.py: each machine its own count of local instances."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SYSTEM_OWNER_ID, AppSetting
from app.models.server_coordination import Server
from app.services import instance_count
from app.services.instance_count import LEGACY_KEY, InstanceCount


async def _legacy(db: AsyncSession, count: int) -> None:
    db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=LEGACY_KEY, value={"count": count}))
    await db.commit()


@pytest.fixture
def shared(monkeypatch: pytest.MonkeyPatch) -> None:
    """As on MySQL: several machines share the database."""
    monkeypatch.setattr(instance_count, "shared_database", lambda db: True)


async def test_each_machine_keeps_its_own_count(db: AsyncSession, shared: None) -> None:
    await InstanceCount(db, "big").set(4)
    await InstanceCount(db, "small").set(1)
    assert await InstanceCount(db, "big").get() == 4
    assert await InstanceCount(db, "small").get() == 1


async def test_new_machine_starts_with_one_not_the_old_shared_count(db: AsyncSession, shared: None) -> None:
    await _legacy(db, 2)
    assert await InstanceCount(db, "new-node").get() == 1


async def test_old_shared_count_stays_with_the_machine_that_ran_instances(db: AsyncSession, shared: None) -> None:
    await _legacy(db, 2)
    db.add(Server(server_id="home:8001", version="1", is_primary=False, last_seen=0, details={"machine": "home"}))
    db.add(Server(server_id="other:8000", version="1", is_primary=True, last_seen=0))
    await db.commit()
    assert await InstanceCount(db, "home").get() == 2
    assert await InstanceCount(db, "other").get() == 1


async def test_own_setting_wins_over_the_old_shared_count(db: AsyncSession, shared: None) -> None:
    await _legacy(db, 3)
    db.add(Server(server_id="home:8001", version="1", is_primary=False, last_seen=0))
    await db.commit()
    await InstanceCount(db, "home").set(1)
    assert await InstanceCount(db, "home").get() == 1


async def test_sqlite_keeps_the_old_count(db: AsyncSession) -> None:
    await _legacy(db, 3)  # one machine only: the old count was its own
    assert await InstanceCount(db, "any").get() == 3


async def test_default_and_bad_values_give_one(db: AsyncSession) -> None:
    assert await InstanceCount(db, "m").get() == 1
    db.add(AppSetting(owner_id=SYSTEM_OWNER_ID, key=InstanceCount(db, "m").key, value={"count": "x"}))
    await db.commit()
    assert await InstanceCount(db, "m").get() == 1


def test_key_fits_the_column() -> None:
    assert len(InstanceCount(None, "h" * 300).key) == 100  # type: ignore[arg-type]
