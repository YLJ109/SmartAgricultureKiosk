"""管理后台：用户、大模型厂商、多语言资源、操作日志。

整个模块在 router 上挂 require_admin，避免每个接口重复写鉴权。
所有写操作统一走 _log() 记一条 OperationLog，后台可追溯"谁在什么时候改了什么"。
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import stats
from app.config import settings
from app.constants import DEFAULT_PAGE_SIZE, LANG_CODES, MAX_PAGE_SIZE, ROLES
from app.core import knowledge, llm
from app.core.auth import CurrentUser, require_admin
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.security import hash_password, mask_key
from app.db.database import get_db
from app.db.models import LangResource, OperationLog, ProviderConfig, User
from app.schemas import (
    LangResourceIn,
    LangResourceOut,
    LogOut,
    OkOut,
    Paged,
    ProviderIn,
    ProviderOut,
    ProviderPatch,
    UserIn,
    UserOut,
    UserPatch,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_LOG_PROBE = [{"role": "user", "content": "回复两个字：正常"}]


# ==========================================================================
# 内部工具
# ==========================================================================

def _where(stmt, conds: list):
    """条件可能为空（如不按角色筛选），SQLAlchemy 不接受空 where，故这里兜一下。"""
    return stmt.where(*conds) if conds else stmt


async def _log(db: AsyncSession, user: User, action: str, target: str, detail: str, request: Request) -> None:
    db.add(
        OperationLog(
            actor=user.username,
            action=action,
            target=target,
            detail=detail,
            ip=request.client.host if request.client else "",
        )
    )


def _configured_by_env(provider: str) -> bool:
    cred = settings.provider_credentials(provider)
    if not cred["api_key"]:
        return False
    # 百度还要 secret_key 才算配置完整
    if provider == "baidu" and not settings.baidu_secret_key:
        return False
    return True


def _provider_payload(p: ProviderConfig) -> dict:
    """出参一律掩码，绝不把完整密钥返回给前端。"""
    full_key = p.api_key or settings.provider_credentials(p.provider)["api_key"]
    return {
        "id": p.id,
        "provider": p.provider,
        "label": p.label,
        "base_url": p.base_url,
        "model": p.model,
        "enabled": p.enabled,
        "is_default": p.is_default,
        "updated_at": p.updated_at,
        "api_key_masked": mask_key(full_key),
        "configured": bool(full_key),
    }


async def _clear_default(db: AsyncSession, keep: ProviderConfig | None = None) -> None:
    rows = (await db.execute(select(ProviderConfig).where(ProviderConfig.is_default.is_(True)))).scalars().all()
    for row in rows:
        if keep is None or row.id != keep.id:
            row.is_default = False


async def _seed_providers(db: AsyncSession) -> None:
    """首次访问且表为空时，按 .env 播种 6 家厂商，后台打开就有内容可看。"""
    total = (await db.execute(select(func.count()).select_from(ProviderConfig))).scalar_one()
    if total:
        return
    for name in ["zhipu", "qwen", "deepseek", "moonshot", "baidu", "custom"]:
        cred = settings.provider_credentials(name)
        db.add(
            ProviderConfig(
                provider=name,
                label=llm.PROVIDER_LABELS.get(name, name),
                base_url=cred["base_url"],
                model=cred["model"],
                api_key=cred["api_key"],
                enabled=_configured_by_env(name),
                is_default=(name == settings.active_provider),
            )
        )
    await db.flush()


# ==========================================================================
# 看板
# ==========================================================================

@router.get("/dashboard")
async def dashboard(db: DbSession) -> dict:
    """复用 stats 的聚合函数，保证后台看板与终端看板口径完全一致。"""
    providers = (await db.execute(select(ProviderConfig).order_by(ProviderConfig.id))).scalars().all()
    logs = (
        await db.execute(select(OperationLog).order_by(OperationLog.created_at.desc(), OperationLog.id.desc()).limit(10))
    ).scalars().all()

    return {
        "overview": await stats.overview_data(db),
        "provider_configs": [ProviderOut(**_provider_payload(p)) for p in providers],
        "recent_logs": [LogOut.model_validate(x) for x in logs],
        "knowledge": knowledge.stats(),
    }


# ==========================================================================
# 用户管理
# ==========================================================================

@router.get("/users", response_model=Paged[UserOut])
async def list_users(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str = Query(""),
    role: str = Query(""),
) -> Paged[UserOut]:
    conds = []
    if role:
        conds.append(User.role == role)
    if keyword:
        like = f"%{keyword.strip()}%"
        conds.append(or_(User.username.like(like), User.display_name.like(like), User.phone.like(like)))

    total = int((await db.execute(_where(select(func.count()).select_from(User), conds))).scalar_one())
    rows = (
        await db.execute(
            _where(select(User), conds).order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return Paged[UserOut](
        items=[UserOut.model_validate(u) for u in rows], total=total, page=page, page_size=page_size
    )


@router.post("/users", response_model=UserOut)
async def create_user(payload: UserIn, request: Request, db: DbSession, user: CurrentUser) -> UserOut:
    exists = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    if exists:
        raise ConflictError(f"用户名「{payload.username}」已存在，请换一个")
    if payload.role not in ROLES:
        raise AppError(f"角色「{payload.role}」不合法，可选：{'、'.join(ROLES)}", 400, "bad_role")

    new_user = User(
        username=payload.username,
        password_hash=hash_password(payload.password) if payload.password else "",
        display_name=payload.display_name,
        phone=payload.phone,
        role=payload.role,
        lang_pref=payload.lang_pref,
        region=payload.region,
        status=payload.status,
    )
    db.add(new_user)
    await db.flush()
    await _log(db, user, "create_user", payload.username, f"新建用户 {payload.username}（{payload.role}）", request)
    return UserOut.model_validate(new_user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, payload: UserPatch, request: Request, db: DbSession, user: CurrentUser) -> UserOut:
    target = await db.get(User, user_id)
    if target is None:
        raise NotFoundError("用户不存在")

    data = payload.model_dump(exclude_unset=True)
    # password 单独处理：只有真正传了非空值才重置
    pwd = data.pop("password", None)
    if pwd:
        target.password_hash = hash_password(pwd)
    if data.get("role") is not None and data["role"] not in ROLES:
        raise AppError(f"角色「{data['role']}」不合法，可选：{'、'.join(ROLES)}", 400, "bad_role")
    for field, value in data.items():
        if value is not None:
            setattr(target, field, value)

    await db.flush()
    await _log(db, user, "update_user", target.username, f"更新用户 {target.username}", request)
    return UserOut.model_validate(target)


@router.delete("/users/{user_id}", response_model=OkOut)
async def delete_user(user_id: int, request: Request, db: DbSession, user: CurrentUser) -> OkOut:
    target = await db.get(User, user_id)
    if target is None:
        raise NotFoundError("用户不存在")
    if target.id == user.id:
        raise AppError("不能删除当前登录的账号", 400, "cannot_delete_self")
    if target.role == "admin":
        admin_total = int((await db.execute(select(func.count()).select_from(User).where(User.role == "admin"))).scalar_one())
        if admin_total <= 1:
            raise AppError("系统至少需要保留一名管理员，无法删除最后一位管理员", 400, "last_admin")

    username = target.username
    await db.delete(target)
    await db.flush()
    await _log(db, user, "delete_user", username, f"删除用户 {username}", request)
    return OkOut(message=f"已删除用户「{username}」")


# ==========================================================================
# 大模型厂商配置
# ==========================================================================

@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(db: DbSession) -> list[ProviderOut]:
    await _seed_providers(db)
    rows = (await db.execute(select(ProviderConfig).order_by(ProviderConfig.id))).scalars().all()
    return [ProviderOut(**_provider_payload(p)) for p in rows]


@router.post("/providers", response_model=ProviderOut)
async def create_provider(payload: ProviderIn, request: Request, db: DbSession, user: CurrentUser) -> ProviderOut:
    provider = payload.provider.strip()
    if not provider:
        raise AppError("provider 不能为空，例如 zhipu / qwen / deepseek", 400, "bad_provider")
    exists = (await db.execute(select(ProviderConfig).where(ProviderConfig.provider == provider))).scalar_one_or_none()
    if exists:
        raise ConflictError(f"厂商「{provider}」的配置已存在，请改用修改")

    row = ProviderConfig(
        provider=provider,
        label=payload.label or llm.PROVIDER_LABELS.get(provider, provider),
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
        enabled=payload.enabled,
        is_default=False,
    )
    db.add(row)
    await db.flush()
    if payload.is_default:
        row.is_default = True
        await _clear_default(db, keep=row)

    await _log(db, user, "create_provider", provider, f"新增厂商配置 {provider}", request)
    return ProviderOut(**_provider_payload(row))


@router.patch("/providers/{provider}", response_model=ProviderOut)
async def update_provider(
    provider: str, payload: ProviderPatch, request: Request, db: DbSession, user: CurrentUser
) -> ProviderOut:
    row = (await db.execute(select(ProviderConfig).where(ProviderConfig.provider == provider))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("厂商配置不存在")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is not None:
            setattr(row, field, value)
    await db.flush()
    if payload.is_default:
        await _clear_default(db, keep=row)

    await _log(db, user, "update_provider", provider, f"更新厂商配置 {provider}", request)
    return ProviderOut(**_provider_payload(row))


@router.delete("/providers/{provider}", response_model=OkOut)
async def delete_provider(provider: str, request: Request, db: DbSession, user: CurrentUser) -> OkOut:
    row = (await db.execute(select(ProviderConfig).where(ProviderConfig.provider == provider))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("厂商配置不存在")

    await db.delete(row)
    await db.flush()
    await _log(db, user, "delete_provider", provider, f"删除厂商配置 {provider}", request)
    return OkOut(message=f"已删除厂商配置「{provider}」")


@router.post("/providers/{provider}/test")
async def test_provider(provider: str, request: Request, db: DbSession, user: CurrentUser) -> dict:
    """连通性测试：当前 active 厂商走标准 healthcheck，其它厂商用库里的凭据临时探测。"""
    started = time.perf_counter()

    if provider == settings.active_provider:
        result = await llm.healthcheck()
        return {
            "ok": bool(result.get("ok")),
            "message": result.get("message", ""),
            "model": result.get("model", ""),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    row = (await db.execute(select(ProviderConfig).where(ProviderConfig.provider == provider))).scalar_one_or_none()
    cred = settings.provider_credentials(provider)
    api_key = (row.api_key if row else "") or cred["api_key"]
    model = (row.model if row else "") or cred["model"]
    base_url = (row.base_url if row else "") or cred["base_url"]

    if not api_key:
        return {"ok": False, "message": "该厂商尚未配置密钥", "model": model, "latency_ms": 0}

    try:
        if provider == "baidu":
            await llm._call_baidu(settings.baidu_api_key, settings.baidu_secret_key, model, _LOG_PROBE)
        else:
            if not base_url:
                return {"ok": False, "message": "该厂商未填写 base_url", "model": model, "latency_ms": 0}
            await llm._call_openai_compatible(base_url, api_key, model, _LOG_PROBE)
        ok, message = True, "连接正常"
    except Exception as exc:
        ok, message = False, f"连接失败：{exc}"

    latency = int((time.perf_counter() - started) * 1000)
    await _log(db, user, "test_provider", provider, f"测试厂商 {provider}：{'成功' if ok else '失败'}", request)
    return {"ok": ok, "message": message, "model": model, "latency_ms": latency}


# ==========================================================================
# 多语言资源
# ==========================================================================

@router.get("/lang-resources", response_model=Paged[LangResourceOut])
async def list_lang_resources(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    lang: str = Query(""),
    keyword: str = Query(""),
) -> Paged[LangResourceOut]:
    conds = []
    if lang:
        conds.append(LangResource.lang == lang)
    if keyword:
        like = f"%{keyword.strip()}%"
        conds.append(or_(LangResource.key.like(like), LangResource.value.like(like)))

    total = int((await db.execute(_where(select(func.count()).select_from(LangResource), conds))).scalar_one())
    rows = (
        await db.execute(
            _where(select(LangResource), conds)
            .order_by(LangResource.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return Paged[LangResourceOut](
        items=[LangResourceOut.model_validate(x) for x in rows], total=total, page=page, page_size=page_size
    )


@router.put("/lang-resources", response_model=LangResourceOut)
async def upsert_lang_resource(
    payload: LangResourceIn, request: Request, db: DbSession, user: CurrentUser
) -> LangResourceOut:
    if payload.lang not in LANG_CODES:
        raise AppError(f"语言代码「{payload.lang}」不受支持，可选：{'、'.join(LANG_CODES)}", 400, "bad_lang")

    row = (
        await db.execute(
            select(LangResource).where(LangResource.lang == payload.lang, LangResource.key == payload.key)
        )
    ).scalar_one_or_none()
    action = "update_lang_resource"
    if row is None:
        row = LangResource(lang=payload.lang, key=payload.key, value=payload.value)
        db.add(row)
        action = "create_lang_resource"
    else:
        row.value = payload.value

    await db.flush()
    await _log(db, user, action, f"{payload.lang}:{payload.key}", f"更新词条 {payload.key}", request)
    return LangResourceOut.model_validate(row)


@router.delete("/lang-resources/{res_id}", response_model=OkOut)
async def delete_lang_resource(res_id: int, request: Request, db: DbSession, user: CurrentUser) -> OkOut:
    row = await db.get(LangResource, res_id)
    if row is None:
        raise NotFoundError("词条不存在")

    target = f"{row.lang}:{row.key}"
    await db.delete(row)
    await db.flush()
    await _log(db, user, "delete_lang_resource", target, f"删除词条 {row.key}", request)
    return OkOut(message=f"已删除词条「{target}」")


# ==========================================================================
# 操作日志
# ==========================================================================

@router.get("/logs", response_model=Paged[LogOut])
async def list_logs(
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    action: str = Query(""),
    keyword: str = Query(""),
) -> Paged[LogOut]:
    conds = []
    if action:
        conds.append(OperationLog.action == action)
    if keyword:
        like = f"%{keyword.strip()}%"
        conds.append(
            or_(
                OperationLog.actor.like(like),
                OperationLog.target.like(like),
                OperationLog.detail.like(like),
            )
        )

    total = int((await db.execute(_where(select(func.count()).select_from(OperationLog), conds))).scalar_one())
    rows = (
        await db.execute(
            _where(select(OperationLog), conds)
            .order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return Paged[LogOut](
        items=[LogOut.model_validate(x) for x in rows], total=total, page=page, page_size=page_size
    )
