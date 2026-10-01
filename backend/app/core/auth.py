"""认证依赖：从 Authorization 头解析当前用户，并做角色校验。"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import ADMIN_ROLES
from app.core.security import decode_access_token
from app.db.database import get_db
from app.db.models import User


class AuthError(Exception):
    """认证/授权失败。由 core/exceptions.py 统一转 401/403。"""

    def __init__(self, message: str = "未登录或登录已过期", status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _extract_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("缺少 Authorization 请求头")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Authorization 头格式应为 'Bearer <token>'")
    return parts[1]


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,  # type: ignore[assignment]
) -> User:
    token = _extract_token(authorization)
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("登录已过期，请重新登录") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("登录凭证无效") from exc

    username = payload.get("sub")
    if not username:
        raise AuthError("登录凭证缺少用户标识")

    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        raise AuthError("用户不存在")
    if user.status != "active":
        raise AuthError("账号已被停用", status_code=403)
    return user


async def get_optional_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,  # type: ignore[assignment]
) -> User | None:
    """游客模式：带 token 就解析，不带也放行。用于终端端允许匿名使用的接口。"""
    if not authorization:
        return None
    try:
        return await get_current_user(authorization=authorization, db=db)
    except AuthError:
        return None


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role not in ADMIN_ROLES:
        raise AuthError("需要管理员或农技员权限", status_code=403)
    return user


def is_guest(user: User | None) -> bool:
    """是否游客。

    一体机摆在大厅等公共区域，游客身份不可追溯 —— 把识别/问答记录挂在这个账号下
    既没有归属人也没有取用价值，还会污染运营统计，所以游客的请求一律不落库。
    匿名（未登录）同理。
    """
    return user is None or user.role == "guest"


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(require_admin)]
