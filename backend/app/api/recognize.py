"""拍照识病：接收上传图片、落盘、跑启发式视觉分析、入库并回传结果。

上传安全说明
------------
图片大小校验必须"边读边判"，不能先 read() 一次性读进内存 —— 否则一个
几百 MB 的大文件就能把终端机的内存打爆。这里按 1MB 分块累加，一旦越界
立即中断并删除已落盘的半截文件（try/except 兜底）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import ALLOWED_IMAGE_EXT, ALLOWED_IMAGE_MIME
from app.core import knowledge, records, vision
from app.core.auth import OptionalUser, is_guest
from app.core.exceptions import AppError
from app.db.database import get_db
from app.db.models import DetectionRecord
from app.schemas import RecognitionOut

router = APIRouter(prefix="/api/recognize", tags=["recognize"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

_CHUNK = 1024 * 1024  # 1MB
_VALID_CHANNELS = {"local", "qrcode"}

# 示例图：真实病叶照片，随仓库放在 backend/static/samples/ 下（已挂载为 /static）。
# 点"试试看"会把这四张图当成正常上传走一遍完整识别链 —— 看到的是模型真检出的结果，
# 不是预先写死在某处的答案。
_SAMPLES = [
    {
        "key": "corn_leaf_spots",
        "zh": "玉米叶斑病叶片",
        "en": "Corn leaf with brown spots",
        "crop": "玉米",
        "url": "/static/samples/corn-leaf-spots.jpg",
    },
    {
        "key": "aphid_leaf",
        "zh": "蚜虫危害的叶片",
        "en": "Leaf infested with aphids",
        "crop": "小麦",
        "url": "/static/samples/aphid-leaf.png",
    },
    {
        "key": "field_3",
        "zh": "田间叶片实拍",
        "en": "Leaf photo from the field",
        "crop": "通用",
        "url": "/static/samples/field-3.webp",
    },
    {
        "key": "field_4",
        "zh": "田间叶片实拍（二）",
        "en": "Leaf photo from the field (2)",
        "crop": "通用",
        "url": "/static/samples/field-4.webp",
    },
]


def _relative_image_path(target: Path) -> str:
    """存库用相对路径（uploads/xxx.png），换绝对路径部署时前端仍能取到图。"""
    try:
        rel = target.relative_to(settings.upload_path.parent)
    except ValueError:
        rel = target
    return str(rel).replace("\\", "/")


@router.post("", response_model=RecognitionOut)
async def recognize(
    db: DbSession,
    user: OptionalUser,
    file: UploadFile = File(...),
    lang: str = Form("zh-CN"),
    crop: str = Form(""),
    channel: str = Form("local"),
) -> RecognitionOut:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise AppError("只支持 JPG / PNG / WEBP / BMP 图片", 400, "bad_file_type")
    if file.content_type and file.content_type not in ALLOWED_IMAGE_MIME:
        raise AppError("只支持 JPG / PNG / WEBP / BMP 图片", 400, "bad_file_type")

    target = settings.upload_path / f"{uuid4().hex}{ext}"
    size = 0
    try:
        with target.open("wb") as fh:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise AppError(f"图片不能超过 {settings.max_upload_mb}MB", 413, "file_too_large")
                fh.write(chunk)

        # 识别是 CPU 密集的（ONNX 推理），后面还可能阻塞在联网的图片理解上，
        # 所以走线程池 —— 直接在事件循环里同步调用会把整台一体机的接口全卡住。
        result = await run_in_threadpool(vision.analyze, target, lang)
        rel_path = _relative_image_path(target)

        # 出参字段集中构造一次，游客与正式用户共用同一套映射 ——
        # 两条分支各写一遍的话，加字段时极易漏传（之前加 boxes 就是这么漏的）
        def _payload(record_no: str, created_at: datetime) -> dict:
            return {
                "record_no": record_no,
                "image_url": records.image_url(rel_path),
                "category": result.get("category", "unknown"),
                "class_key": result.get("class_key", ""),
                "name": result.get("name", ""),
                "crop": result.get("crop") or crop,
                "latin": result.get("latin", ""),
                "confidence": result.get("confidence", 0.0),
                "severity": result.get("severity", "info"),
                "symptoms": list(result.get("symptoms") or []),
                "cause": result.get("cause", ""),
                "treatment": list(result.get("treatment") or []),
                "pesticide": list(result.get("pesticide") or []),
                "boxes": list(result.get("boxes") or []),
                "engine": result.get("engine", "heuristic"),
                "matched": bool(result.get("matched")),
                "is_reference": bool(result.get("is_reference")),
                "reason": dict(result.get("reason") or {}),
                "created_at": created_at,
            }

        # 游客 / 匿名不落库：一体机摆在大厅等公共区域，这类身份不可追溯，
        # 记录留下来既无归属人、也无处可查，只会污染运营统计。
        # 给个临时单号供界面展示就够了。
        if is_guest(user):
            now = datetime.now(timezone.utc)
            return RecognitionOut(**_payload(f"T{now.strftime('%Y%m%d%H%M%S')}", now))

        # 正式用户落库：内容按 6 种语言快照，历史记录切语言时不串味
        snapshot = records.snapshot_from_result(result, lang)
        reason = dict(result.get("reason") or {})
        reason["is_reference"] = bool(result.get("is_reference"))
        # 检测框跟着 reason 一起存（reason 本来就是 JSON 列，不用改表结构）
        reason["boxes"] = result.get("boxes") or []
        record = DetectionRecord(
            record_no=await records.next_record_no(db),
            user_id=user.id if user else None,
            image_path=rel_path,
            category=result.get("category", "unknown"),
            class_key=result.get("class_key", ""),
            name_snapshot=snapshot["name_snapshot"],
            crop=result.get("crop") or crop,
            latin=result.get("latin", ""),
            confidence=result.get("confidence", 0.0),
            severity=result.get("severity", "info"),
            symptoms=snapshot["symptoms"],
            cause=snapshot["cause"],
            treatment=snapshot["treatment"],
            pesticide=snapshot["pesticide"],
            reason=reason,
            engine=result.get("engine", "heuristic"),
            lang=lang,
            source_channel=channel if channel in _VALID_CHANNELS else "local",
        )
        db.add(record)
        await db.flush()

        return RecognitionOut(**_payload(record.record_no, record.created_at))
    except Exception:
        # 任何失败都不留半截文件，避免 uploads 里堆垃圾
        if target.exists():
            target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/samples")
async def samples(lang: str = Query("zh-CN")) -> list[dict]:
    """内置示例图片元信息，供终端端"试试看"入口。"""
    return [
        {
            "key": s["key"],
            "name": knowledge.pick({"zh-CN": s["zh"], "en-US": s["en"]}, lang),
            "url": s["url"],
            "crop": s["crop"],
        }
        for s in _SAMPLES
    ]
