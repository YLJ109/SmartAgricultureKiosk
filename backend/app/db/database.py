"""数据库连接与会话管理（SQLAlchemy 2.0 异步 + SQLite）。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import DATA_DIR, settings

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    # SQLite 在多线程下需要放开同线程校验
    connect_args={"check_same_thread": False},
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个会话，异常自动回滚。"""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """建表（Demo 阶段用 create_all，生产应换成 Alembic 迁移）。"""
    from app.db import models  # noqa: F401  仅为触发模型注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
