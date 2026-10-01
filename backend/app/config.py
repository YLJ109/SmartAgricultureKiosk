"""配置中心：所有可变项集中在此，来源为环境变量 / .env。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BACKEND_DIR / "knowledge"
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 服务 ----------
    app_name: str = "智慧农业多语言一体机服务系统"
    host: str = "0.0.0.0"
    port: int = 8002
    debug: bool = True

    # ---------- 数据库 ----------
    database_url: str = "sqlite+aiosqlite:///./data/kiosk.db"

    # ---------- 认证 ----------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    # ---------- 上传 ----------
    upload_dir: str = "./uploads"
    max_upload_mb: int = 10

    # ---------- 语言 ----------
    default_lang: str = "zh-CN"

    # ---------- 大模型 ----------
    ai_provider: str = ""
    ai_timeout_seconds: int = 30
    ai_max_tokens: int = 800
    ai_temperature: float = 0.6

    zhipu_api_key: str = ""
    zhipu_model: str = "glm-4-flash"
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"

    qwen_api_key: str = ""
    qwen_model: str = "qwen-plus"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    moonshot_api_key: str = ""
    moonshot_model: str = "moonshot-v1-8k"
    moonshot_base_url: str = "https://api.moonshot.cn/v1"

    baidu_api_key: str = ""
    baidu_secret_key: str = ""
    baidu_model: str = "ernie-4.0-8k"

    custom_api_key: str = ""
    custom_model: str = ""
    custom_base_url: str = ""

    # ---------- 跨域 ----------
    cors_origins: str = "http://localhost:5189,http://127.0.0.1:5189"

    # ---------- 派生 ----------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def upload_path(self) -> Path:
        p = Path(self.upload_dir)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def provider_credentials(self, provider: str) -> dict[str, str]:
        """按厂商返回 {api_key, model, base_url}，未配置则为空串。"""
        table = {
            "zhipu": (self.zhipu_api_key, self.zhipu_model, self.zhipu_base_url),
            "qwen": (self.qwen_api_key, self.qwen_model, self.qwen_base_url),
            "deepseek": (self.deepseek_api_key, self.deepseek_model, self.deepseek_base_url),
            "moonshot": (self.moonshot_api_key, self.moonshot_model, self.moonshot_base_url),
            "custom": (self.custom_api_key, self.custom_model, self.custom_base_url),
            "baidu": (self.baidu_api_key, self.baidu_model, ""),
        }
        key, model, base = table.get(provider, ("", "", ""))
        return {"api_key": key, "model": model, "base_url": base}

    @property
    def active_provider(self) -> str:
        """真正可用的厂商：声明了 provider 且密钥齐全，否则返回 none。"""
        p = (self.ai_provider or "").strip().lower()
        if p in ("", "none"):
            return "none"
        cred = self.provider_credentials(p)
        if not cred["api_key"]:
            return "none"
        if p == "baidu" and not self.baidu_secret_key:
            return "none"
        if not cred["base_url"] and p != "baidu":
            return "none"
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
