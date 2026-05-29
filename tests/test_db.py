import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_session_connects(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_base_metadata_has_tables():
    from src.db.base import Base

    table_names = Base.metadata.tables.keys()
    assert "training_records" in table_names
    assert "user_preferences" in table_names
