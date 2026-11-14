"""Prompt cache: "Short index" (index) becomes the default for fresh installs; an existing install keeps what it had

The setting is stored only once an admin saves the Prompt cache page, so a changed default would switch every existing
install that never did. Here an existing database (it has users) without a saved setting gets "Stable order" saved,
as before; a fresh one (no users yet) is left to the new default.

Revision ID: d9e4f6a8b0c3
Revises: c8d3e5f7a9b2
"""

import sqlalchemy as sa

from alembic import op

revision = "d9e4f6a8b0c3"
down_revision = "c8d3e5f7a9b2"
branch_labels = None
depends_on = None

_SYSTEM = "__system__"  # app.models.app_setting.SYSTEM_OWNER_ID
_settings = sa.table(
    "app_settings",
    sa.column("owner_id", sa.String),
    sa.column("key", sa.String),
    sa.column("value", sa.JSON),
)
_users = sa.table("users", sa.column("id", sa.String))


def upgrade() -> None:
    bind = op.get_bind()
    existing = bind.execute(sa.select(sa.func.count()).select_from(_users)).scalar()
    saved = bind.execute(
        sa.select(sa.func.count())
        .select_from(_settings)
        .where(_settings.c.owner_id == _SYSTEM, _settings.c.key == "prompt_cache")
    ).scalar()
    if existing and not saved:
        bind.execute(_settings.insert().values(owner_id=_SYSTEM, key="prompt_cache", value={"mode": "ordered"}))


def downgrade() -> None:
    pass  # a saved "ordered" stays valid on the older version
