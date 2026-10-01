"""全局常量：语言、角色、严重度、作物、上传限制。

注意：语言代码必须与前端 i18n 包一一对应，改动请同步两边。
"""

from __future__ import annotations

# ---------- 语言 ----------
LANGS: list[dict[str, str | None]] = [
    {"code": "zh-CN", "name": "简体中文", "native": "简体中文", "font": None},
    {"code": "en-US", "name": "英语", "native": "English", "font": None},
    {
        "code": "ug-CN",
        "name": "维吾尔语",
        "native": "ئۇيغۇرچە",
        # 优先项目自带的 ALKATIP Basma Tom（前端 @font-face 注册），再退回系统字体
        "font": '"ALKATIP Basma Tom", Microsoft Uighur, Noto Naskh Arabic, serif',
    },
    {
        "code": "kk-CN",
        "name": "哈萨克语",
        "native": "قازاق تىلى",
        "font": "Microsoft Uighur, Noto Naskh Arabic, serif",
    },
    {
        "code": "bo-CN",
        "name": "藏语",
        "native": "བོད་སྐད།",
        "font": "Microsoft Himalaya, Noto Serif Tibetan, serif",
    },
    {
        "code": "mn-CN",
        "name": "蒙古语",
        "native": "ᠮᠣᠩᠭᠣᠯ ᠬᠡᠯᠡ",
        "font": "Mongolian Baiti, Noto Sans Mongolian, serif",
    },
]
LANG_CODES: list[str] = [x["code"] for x in LANGS]  # type: ignore[misc]

# 内容缺失时的兜底顺序：先本语言，再中文
FALLBACK_CHAIN: dict[str, list[str]] = {
    "zh-CN": ["zh-CN"],
    "en-US": ["en-US", "zh-CN"],
    "ug-CN": ["ug-CN", "zh-CN"],
    "kk-CN": ["kk-CN", "zh-CN"],
    "bo-CN": ["bo-CN", "zh-CN"],
    "mn-CN": ["mn-CN", "zh-CN"],
}

# ---------- 角色 ----------
ROLES: dict[str, str] = {
    "farmer": "农户",
    "guest": "游客",
    "operator": "农技员",
    "admin": "管理员",
}
ADMIN_ROLES: set[str] = {"admin", "operator"}

# ---------- 严重度 ----------
SEVERITY_LABEL: dict[str, dict[str, str]] = {
    "info": {"zh-CN": "提示", "en-US": "Info"},
    "low": {"zh-CN": "低风险", "en-US": "Low risk"},
    "medium": {"zh-CN": "中风险", "en-US": "Medium risk"},
    "high": {"zh-CN": "高风险", "en-US": "High risk"},
}

# ---------- 问题大类 ----------
CATEGORIES: dict[str, dict[str, str]] = {
    "disease": {"zh-CN": "病害", "en-US": "Disease"},
    "pest": {"zh-CN": "虫害", "en-US": "Pest"},
    "nutrient": {"zh-CN": "缺素", "en-US": "Nutrient deficiency"},
    "phyto": {"zh-CN": "药害 / 环境胁迫", "en-US": "Phytotoxicity / stress"},
    "healthy": {"zh-CN": "未见明显异常", "en-US": "No obvious issue"},
    "unknown": {"zh-CN": "未能识别", "en-US": "Unrecognized"},
}

# ---------- 作物 ----------
CROPS: list[str] = ["番茄", "玉米", "黄瓜", "苹果", "柑橘", "水稻", "小麦", "棉花", "马铃薯", "葡萄"]

# ---------- 上传 ----------
ALLOWED_IMAGE_EXT: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
ALLOWED_IMAGE_MIME: set[str] = {"image/jpeg", "image/png", "image/webp", "image/bmp"}

# ---------- 分页 ----------
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
