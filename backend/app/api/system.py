"""系统信息与健康检查：终端端启动时拉一次，决定界面语言、可用性与限流提示。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import CATEGORIES, LANGS
from app.core import knowledge
from app.core.llm import PROVIDER_LABELS
from app.db.database import get_db
from app.schemas import HealthOut, SystemInfo

router = APIRouter(prefix="/api/system", tags=["system"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/health", response_model=HealthOut)
async def health(db: DbSession) -> HealthOut:
    """探活：数据库与知识库任一异常都返回 degraded，便于运维一眼看出问题。"""
    db_state = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_state = "error"

    kb_class_total = knowledge.stats().get("class_total", 0)
    kb_state = "ok" if kb_class_total > 0 else "empty"

    return HealthOut(
        status="ok" if db_state == "ok" and kb_state == "ok" else "degraded",
        database=db_state,
        knowledge=kb_state,
        ai_provider=settings.active_provider,
        time=datetime.now(timezone.utc),
    )


@router.get("/info", response_model=SystemInfo)
async def info() -> SystemInfo:
    """前端首页的"一次问清"接口：版本、语言清单、知识库规模、AI 接入情况。"""
    provider = settings.active_provider
    model = settings.provider_credentials(provider)["model"] if provider != "none" else ""
    return SystemInfo(
        app_name=settings.app_name,
        version="1.0.0",
        env="development" if settings.debug else "production",
        langs=LANGS,
        categories=CATEGORIES,
        knowledge=knowledge.stats(),
        ai={
            "provider": provider,
            "provider_label": PROVIDER_LABELS.get(provider, provider),
            "model": model,
            "configured": provider != "none",
        },
        upload_limit_mb=settings.max_upload_mb,
    )


@router.get("/langs")
async def langs() -> list[dict]:
    """语言清单单独给一个轻量接口，切换语言时不必重拉整个 info。"""
    return LANGS


@router.get("/classes")
async def classes(lang: str = Query("zh-CN")) -> list[dict]:
    """知识库全部类别（本地化）。这里刻意只过 localize_class，

    不把 signature / weights / keywords 等内部指纹暴露给前端 —— 那些是算法细节。
    """
    return [knowledge.localize_class(c, lang) for c in knowledge.all_classes()]


@router.get("/calendar")
async def calendar(lang: str = Query("zh-CN")) -> list[dict]:
    """当月农事提醒，终端端首页滚动条用。"""
    return knowledge.current_month_tips(lang)
