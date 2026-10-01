"""ORM 模型。

设计说明：
- 多语言内容（症状/防治/用药）以 JSON 字段整体存储，避免为 6 种语言各开一张翻译表。
  代价是无法按语言建索引，但本系统是"读多写少 + 数据量小"，这样更简单。
- 分类名等需要展示的字段在写入时做快照（*_snapshot），避免知识库改版后历史记录串味。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """终端用户与后台管理员共用一张表，用 role 区分。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    display_name: Mapped[str] = mapped_column(String(64), default="")
    # 一体机用户的手机号会拼进 username（kiosk_<phone>，username 已设 unique），
    # 由它保证一人一号；这里单独存一份是为了后台展示与查询，不要用它做唯一键。
    phone: Mapped[str] = mapped_column(String(20), default="")
    role: Mapped[str] = mapped_column(String(16), default="farmer", index=True)
    lang_pref: Mapped[str] = mapped_column(String(10), default="zh-CN")
    region: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | disabled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    detections: Mapped[list["DetectionRecord"]] = relationship(back_populates="user")
    chats: Mapped[list["ChatRecord"]] = relationship(back_populates="user")


class DetectionRecord(Base):
    """一次拍照识别的完整档案。"""

    __tablename__ = "detection_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    image_path: Mapped[str] = mapped_column(String(255), default="")
    image_thumb: Mapped[str] = mapped_column(String(255), default="")

    # 分类结果
    category: Mapped[str] = mapped_column(String(16), default="unknown")  # disease/pest/nutrient/phyto/healthy/unknown
    class_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    name_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # {lang: name}
    crop: Mapped[str] = mapped_column(String(32), default="")
    latin: Mapped[str] = mapped_column(String(128), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String(16), default="info")

    # 展示内容快照（按语言）
    symptoms: Mapped[dict] = mapped_column(JSON, default=dict)
    cause: Mapped[dict] = mapped_column(JSON, default=dict)
    treatment: Mapped[dict] = mapped_column(JSON, default=dict)
    pesticide: Mapped[dict] = mapped_column(JSON, default=dict)

    # 诊断过程可解释性
    reason: Mapped[dict] = mapped_column(JSON, default=dict)  # 启发式指标明细
    engine: Mapped[str] = mapped_column(String(32), default="heuristic")  # heuristic | model
    lang: Mapped[str] = mapped_column(String(10), default="zh-CN")
    source_channel: Mapped[str] = mapped_column(String(16), default="local")  # local | qrcode
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

    user: Mapped[User | None] = relationship(back_populates="detections")


class ChatRecord(Base):
    """农事问答记录。answer_source 记录答案是本地知识库还是大模型产出。"""

    __tablename__ = "chat_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    answer_source: Mapped[str] = mapped_column(String(16), default="local")  # local | llm | fallback
    intent: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    lang: Mapped[str] = mapped_column(String(10), default="zh-CN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

    user: Mapped[User | None] = relationship(back_populates="chats")


class ProviderConfig(Base):
    """大模型厂商配置：后台可视化维护，与 .env 互为备份。"""

    __tablename__ = "provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), unique=True)  # zhipu/qwen/...
    label: Mapped[str] = mapped_column(String(64), default="")
    base_url: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    api_key: Mapped[str] = mapped_column(String(255), default="")  # 存储做掩码展示，见 core/llm.py
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class LangResource(Base):
    """多语言词条：后台可覆盖前端内置词条。"""

    __tablename__ = "lang_resources"
    __table_args__ = (UniqueConstraint("lang", "key", name="uq_lang_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lang: Mapped[str] = mapped_column(String(10), index=True)
    key: Mapped[str] = mapped_column(String(128), index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class OperationLog(Base):
    """后台操作日志。"""

    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
