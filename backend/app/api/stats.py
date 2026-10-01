"""数据看板：所有数字都从库里实时聚合，不写死任何常量。

终端端与管理后台共用这里的聚合逻辑 —— 内部函数（*_data）返回 dict，
路由再套上 Pydantic 模型出参；admin 直接 import 这些函数复用，避免两份口径。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import LANG_CODES
from app.core import knowledge
from app.core.auth import CurrentUser, OptionalUser, is_guest
from app.core.exceptions import AppError
from app.core.llm import PROVIDER_LABELS
from app.db.database import get_db
from app.db.models import ChatRecord, DetectionRecord, User
from app.schemas import MyStats, NameValue, StatsOverview, TopQuestion, TrendPoint

router = APIRouter(prefix="/api/stats", tags=["stats"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

# 固定色板：图表里同一维度保持同色，切换语言 / 刷新不换色
_DIST_COLORS = ["#2e9e4f", "#1a73e8", "#e59500", "#6b46c1", "#d93025", "#0f8f8f"]


def _today_start_utc() -> datetime:
    """当天 0 点（服务器本地时区）换算成 UTC 且去掉时区。

    库里 created_at 用 now_utc() 写入，SQLite 存的是"UTC 墙钟时间"。
    直接用本地 0 点去比会差 ~8 小时，所以这里统一换算到 UTC 再比较。
    """
    now_local = datetime.now().astimezone()
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc).replace(tzinfo=None)


async def _count(db: AsyncSession, model, *conds) -> int:
    stmt = select(func.count()).select_from(model)
    if conds:
        stmt = stmt.where(*conds)
    return int((await db.execute(stmt)).scalar_one())


# ==========================================================================
# 聚合逻辑（路由与 admin 复用）
# ==========================================================================

async def overview_data(db: AsyncSession) -> dict:
    today = _today_start_utc()

    detection_total = await _count(db, DetectionRecord)
    detection_today = await _count(db, DetectionRecord, DetectionRecord.created_at >= today)
    chat_total = await _count(db, ChatRecord)
    chat_today = await _count(db, ChatRecord, ChatRecord.created_at >= today)
    users_total = await _count(db, User, User.role != "guest")
    identified = await _count(db, DetectionRecord, DetectionRecord.class_key != "")

    avg_conf = (await db.execute(select(func.avg(DetectionRecord.confidence)))).scalar_one()
    provider = settings.active_provider

    return {
        "detection_total": detection_total,
        "detection_today": detection_today,
        "chat_total": chat_total,
        "chat_today": chat_today,
        "users_total": users_total,
        "avg_confidence": round(float(avg_conf or 0.0), 1),
        "identified_rate": round(identified / detection_total * 100, 1) if detection_total else 0.0,
        "class_total": knowledge.stats().get("class_total", 0),
        "lang_count": len(LANG_CODES),
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
    }


async def trend_data(db: AsyncSession, days: int = 30, conds: list | None = None) -> list[dict]:
    """按天统计检测次数。

    conds 可选：个人看板传"只属于该用户"的条件，全站接口不传即为全量，
    这样两处共用同一段补齐日期的逻辑，避免口径跑偏。
    """
    today = datetime.now().astimezone().date()
    start_date = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start_date, time.min).astimezone().astimezone(timezone.utc).replace(tzinfo=None)

    stmt = select(func.date(DetectionRecord.created_at), func.count()).where(DetectionRecord.created_at >= start_dt)
    if conds:
        stmt = stmt.where(*conds)
    rows = (await db.execute(stmt.group_by(func.date(DetectionRecord.created_at)))).all()
    counts = {str(day): int(c) for day, c in rows}

    # 必须补齐没有数据的日期，否则折线会把"没识别"和"没这天"混为一谈
    return [
        {"label": f"{(start_date + timedelta(days=i)).month}/{(start_date + timedelta(days=i)).day}",
         "value": counts.get((start_date + timedelta(days=i)).isoformat(), 0)}
        for i in range(days)
    ]


async def disease_dist_data(db: AsyncSession, lang: str = "zh-CN", limit: int = 6) -> list[dict]:
    rows = (
        await db.execute(
            select(DetectionRecord.class_key, func.count().label("c"))
            .where(DetectionRecord.class_key != "")
            .group_by(DetectionRecord.class_key)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()

    index = knowledge.class_index()
    out: list[dict] = []
    for i, (key, count) in enumerate(rows):
        cls = index.get(key)
        name = knowledge.pick(cls.get("name"), lang) if cls else str(key)
        out.append({"name": name, "value": int(count), "color": _DIST_COLORS[i % len(_DIST_COLORS)]})
    return out


async def regions_data(db: AsyncSession, lang: str = "zh-CN", limit: int = 6) -> list[dict]:
    rows = (
        await db.execute(
            select(User.region, func.count(DetectionRecord.id))
            .select_from(DetectionRecord)
            .join(User, User.id == DetectionRecord.user_id)
            .group_by(User.region)
            .order_by(func.count(DetectionRecord.id).desc())
            .limit(limit)
        )
    ).all()
    unlabeled = knowledge.pick({"zh-CN": "未标注", "en-US": "Unlabeled"}, lang)
    return [{"name": (region or "").strip() or unlabeled, "value": int(c), "color": ""} for region, c in rows]


async def top_questions_data(db: AsyncSession, limit: int = 5) -> list[dict]:
    rows = (
        await db.execute(
            select(ChatRecord.question, func.count().label("c"))
            .group_by(ChatRecord.question)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    return [{"q": q, "c": int(c)} for q, c in rows]


async def mine_data(db: AsyncSession, user: User, lang: str = "zh-CN", days: int = 7) -> dict:
    """个人看板：所有口径都先按 user_id 收窄到"当前登录用户自己"。

    与全站接口的差别只有一处 —— 每个查询都带上 user_id 过滤，其余聚合逻辑一致。
    空数据时返回空数组（不是 null），前端据此渲染空状态即可。
    """
    today = _today_start_utc()
    conds = [DetectionRecord.user_id == user.id]

    detection_total = await _count(db, DetectionRecord, *conds)
    today_total = await _count(db, DetectionRecord, *conds, DetectionRecord.created_at >= today)
    chat_total = await _count(db, ChatRecord, ChatRecord.user_id == user.id)

    # 最常见问题：按 class_key（具体种类）聚合，名称沿用知识库的本地化函数
    rows = (
        await db.execute(
            select(DetectionRecord.class_key, func.count().label("c"))
            .where(*conds, DetectionRecord.class_key != "")
            .group_by(DetectionRecord.class_key)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    index = knowledge.class_index()
    top_issues = []
    for key, count in rows:
        cls = index.get(key)
        name = knowledge.pick(cls.get("name"), lang) if cls else str(key)
        top_issues.append({"code": str(key), "name": name, "count": int(count)})

    # 大类分布：category 保持英文枚举，前端用 i18n 映射成六语文案
    cat_rows = (
        await db.execute(
            select(DetectionRecord.category, func.count().label("c"))
            .where(*conds)
            .group_by(DetectionRecord.category)
            .order_by(func.count().desc())
        )
    ).all()
    category_dist = [{"category": cat or "unknown", "count": int(c)} for cat, c in cat_rows]

    return {
        "detection_total": detection_total,
        "chat_total": chat_total,
        "today_total": today_total,
        "top_issues": top_issues,
        "category_dist": category_dist,
        "trend": await trend_data(db, days, conds),
    }


# ==========================================================================
# 路由
# ==========================================================================

@router.get("/overview", response_model=StatsOverview)
async def overview(db: DbSession, user: OptionalUser) -> StatsOverview:
    return StatsOverview(**await overview_data(db))


@router.get("/trend", response_model=list[TrendPoint])
async def trend(db: DbSession, user: OptionalUser, days: int = Query(30, ge=1, le=365)) -> list[TrendPoint]:
    return [TrendPoint(**p) for p in await trend_data(db, days)]


@router.get("/disease-dist", response_model=list[NameValue])
async def disease_dist(
    db: DbSession,
    user: OptionalUser,
    lang: str = Query("zh-CN"),
    limit: int = Query(6, ge=1, le=20),
) -> list[NameValue]:
    return [NameValue(**x) for x in await disease_dist_data(db, lang, limit)]


@router.get("/regions", response_model=list[NameValue])
async def regions(
    db: DbSession,
    user: OptionalUser,
    lang: str = Query("zh-CN"),
    limit: int = Query(6, ge=1, le=20),
) -> list[NameValue]:
    return [NameValue(**x) for x in await regions_data(db, lang, limit)]


@router.get("/top-questions", response_model=list[TopQuestion])
async def top_questions(db: DbSession, user: OptionalUser, limit: int = Query(5, ge=1, le=20)) -> list[TopQuestion]:
    return [TopQuestion(**x) for x in await top_questions_data(db, limit)]


@router.get("/mine", response_model=MyStats)
async def mine(
    db: DbSession,
    user: CurrentUser,
    lang: str = Query("zh-CN"),
    days: int = Query(7, ge=1, le=90),
) -> MyStats:
    """个人看板：按当前登录用户聚合。

    游客没有可归属的记录（一律不落库），对它们开放只会得到一屏 0，
    反而误导用户"系统坏了"，所以在入口直接拒绝。
    """
    if is_guest(user):
        raise AppError("游客不可使用个人看板，请登录后查看", 403, "forbidden")
    return MyStats(**await mine_data(db, user, lang, days))
