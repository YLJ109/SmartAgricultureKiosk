"""FastAPI 入口：中间件、异常处理、路由挂载、启动初始化。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import asyncio

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import select

from app.api import admin, auth, chat, history, mobile, recognize, stats, system
from app.config import settings
from app.core.detector import detector
from app.core.exceptions import register_exception_handlers
from app.core.llm import PROVIDER_LABELS
from app.core.middleware import RateLimitMiddleware, RequestLogMiddleware
from app.core.security import hash_password
from app.db.database import SessionLocal, init_db
from app.db.models import User

VERSION = "1.0.0"


DEFAULT_ADMIN = {
    "username": "admin",
    "password": "admin123",
    "display_name": "系统管理员",
    "role": "admin",
}


async def _seed_default_admin() -> None:
    """首次启动时建一个管理员账号，避免装完登不进后台。"""
    async with SessionLocal() as db:
        exists = (await db.execute(select(User).where(User.username == DEFAULT_ADMIN["username"]))).scalar_one_or_none()
        if exists:
            return
        db.add(
            User(
                username=DEFAULT_ADMIN["username"],
                password_hash=hash_password(DEFAULT_ADMIN["password"]),
                display_name=DEFAULT_ADMIN["display_name"],
                role="admin",
                lang_pref="zh-CN",
            )
        )
        await db.commit()
        logger.info("已创建默认管理员：{} / {}", DEFAULT_ADMIN["username"], DEFAULT_ADMIN["password"])


async def startup() -> None:
    """启动流程：建表 + 播种默认管理员。

    抽成独立函数而不是直接写在 lifespan 里，是为了让测试可以显式调用 ——
    TestClient 不作为上下文管理器使用时不会触发 lifespan，全新环境下会因无表而失败。
    """
    await init_db()
    await _seed_default_admin()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await startup()
    provider = settings.active_provider
    logger.info("大模型接入：{}（{}）", PROVIDER_LABELS.get(provider, provider), provider)

    # 后台预热检测模型：虫害模型 88MB，首次加载 + 图优化要十几秒。
    # 留到第一次识别时才懒加载的话，第一个来用的农户要对着"识别中"干等；
    # 放后台做，不阻塞启动，等真有人用时模型已经是热的。
    asyncio.create_task(run_in_threadpool(detector.warmup))

    logger.info("{} v{} 启动完成，端口 {}", settings.app_name, VERSION, settings.port)
    yield
    logger.info("服务已停止")


app = FastAPI(
    title=settings.app_name,
    version=VERSION,
    description="面向少数民族地区农业自助终端的多语言一体机服务系统",
    lifespan=lifespan,
)

# ---------- 中间件（注意：add_middleware 是后进先出，限流要在日志外层）----------
app.add_middleware(RequestLogMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

# ---------- 静态资源：上传的图片 ----------
app.mount("/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")
# 内置示例图（真实病叶照片，随仓库分发）："试试看"入口点下去会真的跑一遍识别
app.mount("/static", StaticFiles(directory=str(settings.static_path)), name="static")

# ---------- 路由 ----------
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(recognize.router)
# 微信扫码上传：会话 + 手机端上传页 + 取件轮询（页面在 /m，接口在 /api/recognize/mobile/*）
app.include_router(mobile.router)
app.include_router(chat.router)
app.include_router(history.router)
app.include_router(stats.router)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "app": settings.app_name,
        "version": VERSION,
        "docs": "/docs",
        "time": datetime.now(timezone.utc),
    }
