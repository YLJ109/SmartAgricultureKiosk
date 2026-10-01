"""记录序列化：把库里存的"多语言快照"按当前语言还原成前端可直接渲染的结构。

为什么单独抽一个模块：
识别记录入库时会把当时的知识库内容按 6 种语言整体快照下来（见 db/models.py 的说明）。
读取时"按语言取哪一份"的逻辑如果散落在各路由里，很容易出现某个接口漏了兜底、
返回空字段的情况。集中在这里，只有一处需要保证正确。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import knowledge
from app.db.models import DetectionRecord


def image_url(path: str) -> str:
    """把磁盘相对路径转成前端可访问的 URL。"""
    if not path:
        return ""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return f"/uploads/{name}"


async def next_record_no(db: AsyncSession) -> str:
    """生成 D + 年月日 + 4 位序号 的记录号。"""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"D{today}-"
    count = (
        await db.execute(
            select(func.count()).select_from(DetectionRecord).where(DetectionRecord.record_no.like(f"{prefix}%"))
        )
    ).scalar_one()
    return f"{prefix}{count + 1:04d}"


def localize(record: DetectionRecord, lang: str) -> dict[str, Any]:
    """把一条记录还原成单一语言的扁平结构。"""
    name = knowledge.pick(record.name_snapshot or {}, lang, "")
    return {
        "id": record.id,
        "record_no": record.record_no,
        "image_url": image_url(record.image_path),
        "category": record.category,
        "class_key": record.class_key,
        "crop": record.crop,
        "latin": record.latin,
        "confidence": record.confidence,
        "severity": record.severity,
        "name": name,
        "symptoms": knowledge.pick_list(record.symptoms or {}, lang),
        "cause": knowledge.pick(record.cause or {}, lang),
        "treatment": knowledge.pick_list(record.treatment or {}, lang),
        "pesticide": knowledge.pick_list(record.pesticide or {}, lang),
        "engine": record.engine,
        "is_reference": bool((record.reason or {}).get("is_reference")),
        # 检测框存在 reason 里，出参时提到顶层方便前端直接画
        "boxes": (record.reason or {}).get("boxes") or [],
        "reason": record.reason or {},
        "lang": lang,
        "created_at": record.created_at,
    }


def to_brief(record: DetectionRecord, lang: str) -> dict[str, Any]:
    """列表用的精简结构。"""
    return {
        "id": record.id,
        "record_no": record.record_no,
        "image_url": image_url(record.image_path),
        "category": record.category,
        "class_key": record.class_key,
        "crop": record.crop,
        "confidence": record.confidence,
        "severity": record.severity,
        "name": knowledge.pick(record.name_snapshot or {}, lang, ""),
        "created_at": record.created_at,
    }


def snapshot_from_result(result: dict[str, Any], lang: str) -> dict[str, Any]:
    """把 vision.analyze 的结果落成入库字段。

    name/symptoms/cause/treatment/pesticide 都要变成"多语言快照"。
    启发式分析只产出当前语言，所以这里先取知识库原文补齐其他语言，
    保证用户之后切到别的语言翻历史记录时不会看到空白。
    """
    cls = knowledge.class_index().get(result.get("class_key") or "")

    def multi(value: Any, key: str) -> dict[str, str]:
        if cls and key in cls:
            return dict(cls[key]) if isinstance(cls[key], dict) else {}
        # 知识库没有该条目（大类结果 / 未识别）时，至少保住当前语言
        if isinstance(value, list):
            return {lang: value}
        if isinstance(value, str):
            return {lang: value}
        return {}

    return {
        "name_snapshot": multi(result.get("name"), "name") or {lang: result.get("name", "")},
        "symptoms": multi(result.get("symptoms"), "symptoms"),
        "cause": multi(result.get("cause"), "cause"),
        "treatment": multi(result.get("treatment"), "treatment"),
        "pesticide": multi(result.get("pesticide"), "pesticide"),
    }
