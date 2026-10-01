"""历史记录：识别档案与问答记录的查询、详情、删除。

可见性规则（列表与详情共用）
----------------------------
- 未登录：只能看 user_id 为空的匿名记录（终端端不登录直用产生的）；
- 已登录：看自己的记录；
- 管理员 / 农技员：不做 user_id 过滤，可查看全部，用于后台巡检。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import ADMIN_ROLES, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core import records
from app.core.auth import OptionalUser
from app.core.exceptions import AppError, NotFoundError
from app.db.database import get_db
from app.db.models import ChatRecord, DetectionRecord, User
from app.schemas import OkOut, Paged, RecordBrief, RecordDetail

router = APIRouter(prefix="/api/history", tags=["history"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _visibility_conds(user: User | None) -> list:
    """把"谁能看哪些记录"翻译成一组 WHERE 条件。"""
    if user is None:
        return [DetectionRecord.user_id.is_(None)]
    if user.role in ADMIN_ROLES:
        return []
    return [DetectionRecord.user_id == user.id]


def _where(stmt, conds: list):
    """条件可能为空（管理员不过滤），SQLAlchemy 不接受空 where，故这里兜一下。"""
    return stmt.where(*conds) if conds else stmt


@router.get("", response_model=Paged[RecordBrief])
async def list_records(
    db: DbSession,
    user: OptionalUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str = Query(""),
    category: str = Query(""),
    lang: str = Query("zh-CN"),
    days: int = Query(0, ge=0),
) -> Paged[RecordBrief]:
    conds = _visibility_conds(user)
    if category:
        conds.append(DetectionRecord.category == category)
    if days > 0:
        conds.append(DetectionRecord.created_at >= datetime.now(timezone.utc) - timedelta(days=days))
    if keyword:
        like = f"%{keyword.strip()}%"
        # name_snapshot 是 JSON，SQLite 无法对子键单独建条件，只能整体转字符串模糊匹配
        conds.append(
            or_(
                DetectionRecord.record_no.like(like),
                DetectionRecord.crop.like(like),
                cast(DetectionRecord.name_snapshot, String).like(like),
            )
        )

    total = (await db.execute(_where(select(func.count()).select_from(DetectionRecord), conds))).scalar_one()
    rows = (
        await db.execute(
            _where(select(DetectionRecord), conds)
            .order_by(DetectionRecord.created_at.desc(), DetectionRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items = [RecordBrief(**records.to_brief(r, lang)) for r in rows]
    return Paged[RecordBrief](items=items, total=total, page=page, page_size=page_size)


@router.get("/chats", response_model=Paged[dict])
async def list_chats(
    db: DbSession,
    user: OptionalUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str = Query(""),
) -> Paged[dict]:
    conds = []
    if user is None:
        conds.append(ChatRecord.user_id.is_(None))
    elif user.role not in ADMIN_ROLES:
        conds.append(ChatRecord.user_id == user.id)

    if keyword:
        like = f"%{keyword.strip()}%"
        conds.append(or_(ChatRecord.question.like(like), ChatRecord.answer.like(like)))

    total = (await db.execute(_where(select(func.count()).select_from(ChatRecord), conds))).scalar_one()
    rows = (
        await db.execute(
            _where(select(ChatRecord), conds)
            .order_by(ChatRecord.created_at.desc(), ChatRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    items = [
        {
            "id": r.id,
            "question": r.question,
            "answer": r.answer,
            "answer_source": r.answer_source,
            "provider": r.provider,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return Paged[dict](items=items, total=total, page=page, page_size=page_size)


@router.get("/{record_no}", response_model=RecordDetail)
async def record_detail(
    record_no: str,
    db: DbSession,
    user: OptionalUser,
    lang: str = Query("zh-CN"),
) -> RecordDetail:
    record = (
        await db.execute(select(DetectionRecord).where(DetectionRecord.record_no == record_no))
    ).scalar_one_or_none()
    if record is None:
        raise NotFoundError("记录不存在")

    # 详情同样套用可见性规则：越权访问一律按"不存在"处理，不泄露记录是否存在
    if user is None:
        if record.user_id is not None:
            raise NotFoundError("记录不存在")
    elif user.role not in ADMIN_ROLES and record.user_id not in (None, user.id):
        raise NotFoundError("记录不存在")

    return RecordDetail(**records.localize(record, lang))


@router.delete("/{record_no}", response_model=OkOut)
async def delete_record(record_no: str, db: DbSession, user: OptionalUser) -> OkOut:
    record = (
        await db.execute(select(DetectionRecord).where(DetectionRecord.record_no == record_no))
    ).scalar_one_or_none()
    if record is None:
        raise NotFoundError("记录不存在")

    if user is None or (user.role not in ADMIN_ROLES and record.user_id != user.id):
        raise AppError("无权删除该记录", 403, "forbidden")

    await db.delete(record)
    await db.flush()
    return OkOut(message=f"已删除记录 {record_no}")
