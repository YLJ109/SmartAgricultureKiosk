"""Pydantic 请求/响应模型。字段命名统一 snake_case，前端 axios 侧不再转换。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ==========================================================================
# 通用
# ==========================================================================

class Paged(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size if self.page_size else 0


class OkOut(BaseModel):
    ok: bool = True
    message: str = ""


# ==========================================================================
# 认证
# ==========================================================================

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class GuestIn(BaseModel):
    display_name: str = Field(default="", max_length=64)
    lang: str = "zh-CN"


class KioskRegisterIn(BaseModel):
    """一体机注册：手机号必填，它同时是账号主键，保证同一个人能稳定认回自己的记录。"""

    display_name: str = Field(min_length=1, max_length=64)
    # 手机号只在这里声明为必填，长度/格式交给接口里的正则统一校验。
    # 不在此处写 min_length=11：否则像 "123" 这种会被 Pydantic 先判成 422，
    # 拿不到业务侧那句可读的中文提示（400 bad_phone）。
    phone: str = Field(min_length=1)
    region: str = Field(default="", max_length=64)
    lang: str = "zh-CN"


class KioskLoginIn(BaseModel):
    """一体机登录：手机号定位账号，姓名做二次校验，避免把记录串到别人账号上。"""

    display_name: str = Field(min_length=1, max_length=64)
    # 同上：格式校验统一走接口里的正则，避免 422 把友好提示挡掉
    phone: str = Field(min_length=1)
    lang: str = "zh-CN"


class UserOut(ORMModel):
    id: int
    username: str
    display_name: str
    phone: str
    role: str
    lang_pref: str
    region: str
    status: str
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ==========================================================================
# 识别
# ==========================================================================

class RecognitionOut(BaseModel):
    record_no: str
    image_url: str
    category: str
    class_key: str
    name: str
    crop: str
    latin: str
    confidence: float
    severity: str
    symptoms: list[str] = []
    cause: str = ""
    treatment: list[str] = []
    pesticide: list[str] = []
    # 检测框：相对坐标 0~1，前端按渲染尺寸换算后叠加在图上
    boxes: list[dict[str, Any]] = []
    engine: str = "heuristic"
    matched: bool = False
    is_reference: bool = False
    reason: dict[str, Any] = {}
    created_at: datetime


class RecordBrief(ORMModel):
    id: int
    record_no: str
    image_url: str = ""
    category: str
    class_key: str
    crop: str
    confidence: float
    severity: str
    name: str = ""
    created_at: datetime


class RecordDetail(RecordBrief):
    symptoms: list[str] = []
    cause: str = ""
    treatment: list[str] = []
    pesticide: list[str] = []
    latin: str = ""
    boxes: list[dict[str, Any]] = []
    engine: str = ""
    is_reference: bool = False
    reason: dict[str, Any] = {}
    lang: str = "zh-CN"


# ==========================================================================
# 问答
# ==========================================================================

class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    lang: str = "zh-CN"


class ChatOut(BaseModel):
    answer: str
    source: str                # local | llm | fallback
    provider: str = ""
    provider_label: str = ""
    model: str = ""
    tokens: int = 0
    latency_ms: int = 0
    record_id: int | None = None


class QuickAsk(BaseModel):
    key: str
    text: str


# ==========================================================================
# 统计 / 看板
# ==========================================================================

class StatsOverview(BaseModel):
    detection_total: int
    detection_today: int
    chat_total: int
    chat_today: int
    users_total: int
    avg_confidence: float
    identified_rate: float          # 能给出具体病名的比例
    class_total: int
    lang_count: int
    provider: str
    provider_label: str


class TrendPoint(BaseModel):
    label: str
    value: int


class NameValue(BaseModel):
    name: str
    value: int
    color: str = ""


class TopQuestion(BaseModel):
    q: str
    c: int


class MineIssue(BaseModel):
    """个人看板里的"最常见问题"条目：code 是知识库 class_key，name 已按语言本地化。"""

    code: str
    name: str
    count: int


class MineCategory(BaseModel):
    """按大类的分布。category 保持机器可读的英文枚举，文案由前端 i18n 负责。"""

    category: str
    count: int


class MyStats(BaseModel):
    """个人看板：只聚合当前登录用户自己的记录。

    空数据时各列表返回空数组（不是 null），前端不必特判。
    """

    detection_total: int
    chat_total: int
    today_total: int
    top_issues: list[MineIssue] = []
    category_dist: list[MineCategory] = []
    trend: list[TrendPoint] = []


# ==========================================================================
# 管理后台
# ==========================================================================

class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(default="", max_length=128)
    display_name: str = ""
    phone: str = ""
    role: str = "farmer"
    lang_pref: str = "zh-CN"
    region: str = ""
    status: str = "active"


class UserPatch(BaseModel):
    display_name: str | None = None
    phone: str | None = None
    role: str | None = None
    lang_pref: str | None = None
    region: str | None = None
    status: str | None = None
    password: str | None = None


class ProviderOut(ORMModel):
    id: int
    provider: str
    label: str
    base_url: str
    model: str
    enabled: bool
    is_default: bool
    updated_at: datetime | None = None
    api_key_masked: str = ""
    configured: bool = False


class ProviderIn(BaseModel):
    provider: str
    label: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    enabled: bool = False
    is_default: bool = False


class ProviderPatch(BaseModel):
    label: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class LangResourceOut(ORMModel):
    id: int
    lang: str
    key: str
    value: str
    updated_at: datetime | None = None


class LangResourceIn(BaseModel):
    lang: str
    key: str = Field(min_length=1, max_length=128)
    value: str = ""


class LogOut(ORMModel):
    id: int
    actor: str
    action: str
    target: str
    detail: str
    ip: str
    created_at: datetime


class SystemInfo(BaseModel):
    app_name: str
    version: str
    env: str
    langs: list[dict[str, Any]]
    categories: dict[str, dict[str, str]]
    knowledge: dict[str, Any]
    ai: dict[str, Any]
    upload_limit_mb: int


class HealthOut(BaseModel):
    status: str
    database: str
    knowledge: str
    ai_provider: str
    time: datetime
