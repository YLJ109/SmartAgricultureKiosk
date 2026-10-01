"""农业知识库：加载 JSON、按语言取值、关键词检索。

设计要点：
- 知识库是"读多写少"的静态数据，启动时一次性载入内存，之后只读。
- 所有多语言字段形如 {"zh-CN": ..., "en-US": ...}，统一走 pick() 做兜底，
  避免每个调用点自己写 `d.get(lang) or d.get('zh-CN')`。
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from loguru import logger

from app.config import KNOWLEDGE_DIR
from app.constants import FALLBACK_CHAIN

# ---------- 加载 ----------


def _read_json(name: str) -> dict[str, Any]:
    path = KNOWLEDGE_DIR / name
    if not path.exists():
        logger.warning("知识库文件缺失：{}", path)
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def pest_disease() -> dict[str, Any]:
    return _read_json("pest_disease.json")


@lru_cache
def fertilizer() -> dict[str, Any]:
    return _read_json("fertilizer.json")


@lru_cache
def crop_calendar() -> dict[str, Any]:
    return _read_json("crop_calendar.json")


@lru_cache
def class_index() -> dict[str, dict[str, Any]]:
    """{class_key: class_dict}，供按 key 直查。"""
    return {c["key"]: c for c in pest_disease().get("classes", [])}


@lru_cache
def all_classes() -> list[dict[str, Any]]:
    return list(pest_disease().get("classes", []))


# ---------- 多语言取值 ----------


def pick(value: Any, lang: str, default: Any = "") -> Any:
    """从多语言字典里按兜底链取值。

    pick({"zh-CN": "番茄早疫病", "en-US": "..."}, "bo-CN") -> "番茄早疫病"
    非多语言字典（如 list / str）原样返回。
    """
    if not isinstance(value, dict):
        return value if value is not None else default
    for code in FALLBACK_CHAIN.get(lang, [lang, "zh-CN"]):
        v = value.get(code)
        if v:
            return v
    # 兜底链全空时，任取一个非空值，总比返回空串强
    for v in value.values():
        if v:
            return v
    return default


def pick_list(value: Any, lang: str) -> list[str]:
    got = pick(value, lang, [])
    if isinstance(got, list):
        return [str(x) for x in got]
    if isinstance(got, str) and got:
        return [got]
    return []


# ---------- 检索 ----------


def localize_class(cls: dict[str, Any], lang: str) -> dict[str, Any]:
    """把一条知识库记录转成"单一语言"的扁平结构，直接给前端用。"""
    return {
        "key": cls.get("key", ""),
        "category": cls.get("category", "unknown"),
        "crop": cls.get("crop", ""),
        "latin": cls.get("latin", ""),
        "severity": cls.get("severity", "info"),
        "name": pick(cls.get("name"), lang),
        "symptoms": pick_list(cls.get("symptoms"), lang),
        "cause": pick(cls.get("cause"), lang),
        "treatment": pick_list(cls.get("treatment"), lang),
        "pesticide": pick_list(cls.get("pesticide"), lang),
    }


def search_classes(query: str, lang: str = "zh-CN", limit: int = 5) -> list[dict[str, Any]]:
    """关键词检索：先匹配 keywords，再匹配各语言名称。

    本系统不引入向量库，因为类别只有十几条 —— 分词+子串匹配已经足够，
    而且完全离线、零依赖、结果可解释（能说清"为什么命中这一条"）。
    """
    q = (query or "").strip().lower()
    if not q:
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for cls in all_classes():
        score = 0.0
        for kw in cls.get("keywords", []):
            if kw and kw.lower() in q:
                score += 3.0
        # 名称命中（任意语言）
        for name in (cls.get("name") or {}).values():
            if name and str(name).lower() in q:
                score += 4.0
        # 作物命中
        crop = cls.get("crop", "")
        if crop and crop != "通用" and crop in q:
            score += 1.0
        if score > 0:
            scored.append((score, cls))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [localize_class(c, lang) for _, c in scored[:limit]]


def find_nutrients(query: str, lang: str = "zh-CN") -> list[dict[str, Any]]:
    """按缺素关键词找营养元素词条。"""
    q = (query or "").strip()
    if not q:
        return []
    hit: list[dict[str, Any]] = []
    for n in fertilizer().get("nutrients", []):
        names = [str(v) for v in (n.get("name") or {}).values() if v]
        if any(nm in q for nm in names) or n.get("symbol", "") in q:
            hit.append(
                {
                    "key": n.get("key"),
                    "symbol": n.get("symbol"),
                    "name": pick(n.get("name"), lang),
                    "deficiency": pick(n.get("deficiency"), lang),
                    "excess": pick(n.get("excess"), lang),
                    "advice": pick_list(n.get("advice"), lang),
                    "sources": [
                        {"name": pick(s.get("name"), lang), "content": s.get("content", "")}
                        for s in n.get("sources", [])
                    ],
                }
            )
    return hit


def calendar_for(crop: str, month: int, lang: str = "zh-CN") -> dict[str, Any] | None:
    """取某作物某月的农事安排。crop 支持中英文模糊命中。"""
    for entry in crop_calendar().get("crops", []):
        crop_name = pick(entry.get("crop"), lang)
        crop_zh = (entry.get("crop") or {}).get("zh-CN", "")
        if crop and crop not in (crop_name, crop_zh):
            continue
        month_data = entry.get("months", {}).get(str(month))
        if not month_data:
            return None
        return {
            "crop": crop_name,
            "region": pick(entry.get("region"), lang),
            "month": month,
            "items": pick_list(month_data, lang),
        }
    return None


def current_month_tips(lang: str = "zh-CN", limit: int = 3) -> list[dict[str, Any]]:
    """当月全部作物的农事提醒，供终端端首页/看板展示。"""
    from datetime import datetime

    month = datetime.now().month
    out: list[dict[str, Any]] = []
    for entry in crop_calendar().get("crops", []):
        month_data = entry.get("months", {}).get(str(month))
        if not month_data:
            continue
        out.append(
            {
                "crop": pick(entry.get("crop"), lang),
                "region": pick(entry.get("region"), lang),
                "month": month,
                "items": pick_list(month_data, lang),
            }
        )
        if len(out) >= limit:
            break
    return out


# ---------- 统计口径 ----------


def stats() -> dict[str, Any]:
    classes = all_classes()
    by_cat: dict[str, int] = {}
    for c in classes:
        by_cat[c.get("category", "unknown")] = by_cat.get(c.get("category", "unknown"), 0) + 1
    return {
        "class_total": len(classes),
        "by_category": by_cat,
        "crops": sorted({c.get("crop", "") for c in classes if c.get("crop")}),
        "nutrient_total": len(fertilizer().get("nutrients", [])),
        "calendar_crops": len(crop_calendar().get("crops", [])),
        "i18n_status": pest_disease().get("i18n_status", {}),
    }
