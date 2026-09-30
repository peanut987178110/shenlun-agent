"""数据库会话与初始化。"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Base

engine = create_async_engine(
    settings.database_url,
    echo=False,
    # 多道题并发批改会同时写库，等锁最多 30 秒而不是立刻报 database is locked
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(sync_conn) -> None:
    """轻量迁移：给已有表补上新增的列（只 ADD COLUMN，不删不改，已有数据不受影响）。

    create_all 只建新表，不给旧表加列；老库升级后一查新字段就报 no such column。
    """
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(sync_conn.dialect)}'
            default = getattr(col.default, "arg", None)
            if isinstance(default, bool):
                ddl += f" DEFAULT {int(default)}"
            elif isinstance(default, (int, float)):
                ddl += f" DEFAULT {default}"
            elif isinstance(default, str):
                ddl += " DEFAULT '" + default.replace("'", "''") + "'"
            elif callable(default) and col.type.__class__.__name__ == "JSON":
                # 默认值是 list / dict 工厂（SQLAlchemy 会把它包一层，调用时传执行上下文）
                import json
                try:
                    v = default(None)
                except TypeError:
                    v = default()
                ddl += " DEFAULT '" + json.dumps(v) + "'"
            sync_conn.execute(text(ddl))
            print(f"[迁移] {table.name} 新增列 {col.name}")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
