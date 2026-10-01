"""认证：账号登录、一体机注册/登录、游客模式、当前用户信息。

两条免密通道，区别必须守住
--------------------------
- `/kiosk/register` + `/kiosk/login`：用户在终端机上**填了姓名和手机号**。他愿意被
  识别、之后要回来查自己的记录，所以建的是 role=farmer 的真实用户，记录入库、
  历史与看板可用。
- `/guest`：用户**没填姓名**，点了"游客模式"。这类身份不可追溯，按策略不落库、
  历史与看板锁定（见 core/auth.is_guest）。

为什么一体机用手机号当账号主键
------------------------------
手机号是农户身上唯一稳定、不会重复的标识。早期版本手机号可留空，留空时就随机
生成账号 —— 同一个人下次来就找不回自己的记录，历史数据会散成一堆孤儿账号
（"手机号码和姓名必填，一定要匹配，不然历史记录和数据会乱掉"）。改成手机号做
主键后，同一个人靠手机号就能稳定认回自己的记录；姓名作为二次校验，避免张冠李戴
把记录串到别人的账号上。

游客账号固定复用同一个用户名（token 的 sub 恒为 "guest"），
避免每次点击都新建 users 行、把历史记录散成几百个孤儿账号。
"""

from __future__ import annotations

import random
import re
import string
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import CurrentUser
from app.core.exceptions import AppError
from app.core.security import create_access_token, verify_password
from app.db.database import get_db
from app.db.models import OperationLog, User
from app.schemas import GuestIn, KioskLoginIn, KioskRegisterIn, LoginIn, TokenOut, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

GUEST_USERNAME = "guest"
KIOSK_PREFIX = "kiosk_"

# 大陆手机号：1 开头，第二位 3-9，共 11 位纯数字。
# 之所以在入口就卡死格式，而不是"能塞进 username 就行"，是因为手机号是账号主键，
# 格式乱掉就会让同一个人产生多个账号，历史记录跟着散掉。
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def _normalize_phone(raw: str) -> str:
    """校验并返回 11 位手机号；不合法直接抛业务异常，调用方无需再判空。"""
    phone = (raw or "").strip()
    if not _PHONE_RE.match(phone):
        raise AppError("请填写正确的 11 位手机号", 400, "bad_phone")
    return phone


def _random_guest_name() -> str:
    """生成 游客-XXXX，四位大写字母数字。用 random 而非 uuid 是因为要短且好念。"""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"游客-{suffix}"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _issue_token(user: User) -> TokenOut:
    token = create_access_token(user.username, user.role)
    return TokenOut(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, request: Request, db: DbSession) -> TokenOut:
    user = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    # 用户不存在与密码错误返回同一提示，避免被用来枚举账号
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AppError("账号或密码不正确", 401, "invalid_credentials")
    if user.status != "active":
        raise AppError("该账号已被停用，请联系管理员", 403, "account_disabled")

    user.last_login_at = datetime.now(timezone.utc)
    return _issue_token(user)


@router.post("/guest", response_model=TokenOut)
async def guest(payload: GuestIn, request: Request, db: DbSession) -> TokenOut:
    name = (payload.display_name or "").strip() or _random_guest_name()

    user = (await db.execute(select(User).where(User.username == GUEST_USERNAME))).scalar_one_or_none()
    if user is None:
        # 首次进入游客模式时建档；无密码，只能走 /guest 拿 token
        user = User(
            username=GUEST_USERNAME,
            password_hash="",
            display_name=name,
            role="guest",
            lang_pref=payload.lang,
            status="active",
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        await db.flush()
    else:
        user.display_name = name
        user.lang_pref = payload.lang
        user.last_login_at = datetime.now(timezone.utc)

    db.add(
        OperationLog(
            actor=user.username,
            action="guest_login",
            target=GUEST_USERNAME,
            detail=f"游客进入：{name}",
            ip=_client_ip(request),
        )
    )
    return _issue_token(user)


@router.post("/kiosk/register", response_model=TokenOut)
async def kiosk_register(payload: KioskRegisterIn, request: Request, db: DbSession) -> TokenOut:
    """一体机注册 —— 与 /guest 是两条不同的通道，别混用。

    为什么手机号是账号主键：
    填了姓名+手机号意味着这位农户愿意被识别、之后要回来查自己的检测记录。
    手机号是唯一稳定、不重复的标识，用它拼出 username 就能保证"同一个人永远
    认回同一个账号"；早先"手机号可留空 + 随机账号"的写法会让历史记录散成一堆
    孤儿账号，所以这里手机号必填且格式强校验。

    姓名只做展示与二次校验，不进 username —— 同名的人很多，用它做键必然串号。
    """
    phone = _normalize_phone(payload.phone)
    name = payload.display_name.strip()

    username = f"{KIOSK_PREFIX}{phone}"
    now = datetime.now(timezone.utc)

    exists = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if exists is not None:
        # 同一手机号只允许有一个账号，重复注册会把人拆成两个身份、记录跟着分家
        raise AppError("这个手机号已经注册过了，请直接登录", 409, "phone_taken")

    user = User(
        username=username,
        password_hash="",
        display_name=name,
        phone=phone,
        role="farmer",
        region=payload.region.strip(),
        lang_pref=payload.lang,
        status="active",
        last_login_at=now,
    )
    db.add(user)
    await db.flush()

    db.add(
        OperationLog(
            actor=user.username,
            action="kiosk_register",
            target=username,
            detail=f"一体机注册：{name}（{phone}）",
            ip=_client_ip(request),
        )
    )
    return _issue_token(user)


@router.post("/kiosk/login", response_model=TokenOut)
async def kiosk_login(payload: KioskLoginIn, request: Request, db: DbSession) -> TokenOut:
    """一体机登录 —— 用手机号定位账号，再用姓名做二次校验。

    为什么必须"姓名和手机号都匹配"：
    手机号是账号主键，谁拿着这个号就能取走这个账号下的全部记录。若只对手机号，
    号码被说错一位、或被人冒用，记录就会张冠李戴串到别人头上。校验姓名能把大部分
    误操作挡在门外，这正是需求方强调的"一定要匹配"。
    """
    phone = _normalize_phone(payload.phone)
    name = payload.display_name.strip()

    username = f"{KIOSK_PREFIX}{phone}"
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        raise AppError("这个手机号还没注册，请先注册", 404, "phone_not_registered")
    if user.display_name != name:
        # 账号存在但姓名对不上：说明来的人不是这个号的户主，拒绝以免拿错记录
        raise AppError("姓名和手机号不匹配，请检查后重试", 403, "name_mismatch")
    if user.status != "active":
        raise AppError("该账号已被停用，请联系管理员", 403, "account_disabled")

    user.last_login_at = datetime.now(timezone.utc)
    user.lang_pref = payload.lang

    db.add(
        OperationLog(
            actor=user.username,
            action="kiosk_login",
            target=username,
            detail=f"一体机登录：{name}（{phone}）",
            ip=_client_ip(request),
        )
    )
    return _issue_token(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
