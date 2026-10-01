"""整图分类器：MobileNetV2（PlantVillage 38 类），ONNX、纯 CPU、离线。

与 detector.py 里 YOLO 的分工
------------------------------
YOLO 回答"病灶在哪"，这个回答"整片叶子像是什么病"。YOLO 检不出时（病斑不典型、
拍得远、画面乱），分类器往往仍能给出靠谱判断，而且不联网、比图片理解快一个数量级 ——
所以它在识别链里排在图片理解之前。

为什么吃整图、不做裁剪
----------------------
PlantVillage 数据集本身就是"一片叶子居中占满画面"的构图，训练分布如此，推理时也照做。
硬塞裁剪出来的小图反而偏离训练分布，还不如不裁。

模型文件
--------
`data/models/plant_classifier.onnx`（8.8MB）+ `plant_classifier_config.json`（含 38 类标签）。
两者都不进版本库；缺失时返回 None，由上层继续降级，服务照常启动。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from app.config import settings

#: 分类器的 38 类 → 本知识库的 key。空字符串表示知识库还没有对应条目，
#: 上层只报大类、不硬套病名去开药。
#:
#: 白粉病跨作物通用（黄瓜 / 南瓜 / 樱桃），所以复用到同一份方案 —— 但这属于「通用建议」，
#: 结果里会照常带 is_reference 提示，不会被当成针对该作物的精确诊断。
CLASS_TO_KNOWLEDGE: dict[str, str] = {
    "Apple Scab": "apple_scab",
    "Apple with Black Rot": "apple_black_rot",
    "Cedar Apple Rust": "apple_cedar_rust",
    "Cherry with Powdery Mildew": "cucumber_powdery_mildew",
    "Corn (Maize) with Cercospora and Gray Leaf Spot": "maize_gray_leaf_spot",
    "Corn (Maize) with Common Rust": "maize_common_rust",
    "Corn (Maize) with Northern Leaf Blight": "maize_leaf_blight",
    "Grape with Black Rot": "grape_black_rot",
    "Grape with Esca (Black Measles)": "grape_esca",
    "Grape with Isariopsis Leaf Spot": "grape_leaf_spot",
    "Orange with Citrus Greening": "citrus_greening",
    "Peach with Bacterial Spot": "peach_bacterial_spot",
    "Bell Pepper with Bacterial Spot": "pepper_bacterial_spot",
    "Potato with Early Blight": "potato_early_blight",
    "Potato with Late Blight": "potato_late_blight",
    "Squash with Powdery Mildew": "cucumber_powdery_mildew",
    "Strawberry with Leaf Scorch": "strawberry_leaf_scorch",
    "Tomato with Bacterial Spot": "tomato_bacterial_spot",
    "Tomato with Early Blight": "tomato_early_blight",
    "Tomato with Late Blight": "tomato_late_blight",
    "Tomato with Leaf Mold": "tomato_leaf_mold",
    "Tomato with Septoria Leaf Spot": "tomato_septoria",
    "Tomato with Spider Mites or Two-spotted Spider Mite": "red_spider_mite",
    "Tomato with Target Spot": "tomato_target_spot",
    "Tomato Yellow Leaf Curl Virus": "tomato_yellow_leaf_curl",
    "Tomato Mosaic Virus": "tomato_mosaic_virus",
}

#: 模型自带的预处理参数（取自 preprocessor_config.json，不是猜的）：
#: 短边缩到 256 → 中心裁 224 → /255 → (x-0.5)/0.5。
#: 写死成常量是因为它就跟着这一个模型走，换模型时应连这套参数一起换。
_SHORT_EDGE = 256
_CROP = 224
_MEAN = 0.5
_STD = 0.5


class Classifier:
    def __init__(self) -> None:
        base = Path(settings.models_dir)
        if not base.is_absolute():
            base = Path(__file__).resolve().parents[2] / base
        self.path = base / "plant_classifier.onnx"
        self.config_path = base / "plant_classifier_config.json"
        self.labels: dict[int, str] = {}
        self._session: Any = None
        self._failed = False
        self._lock = threading.Lock()
        self._load_labels()

    def _load_labels(self) -> None:
        if not self.config_path.exists():
            return
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.labels = {int(k): str(v) for k, v in (raw.get("id2label") or {}).items()}
        except Exception as exc:
            logger.warning("分类器标签读取失败：{}", exc)

    @property
    def available(self) -> bool:
        return self.path.exists() and bool(self.labels) and not self._failed

    def _ensure_session(self) -> Any:
        if self._session is not None or self._failed:
            return self._session
        with self._lock:
            if self._session is not None or self._failed:
                return self._session
            try:
                import onnxruntime as ort

                opts = ort.SessionOptions()
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self._session = ort.InferenceSession(
                    str(self.path), opts, providers=["CPUExecutionProvider"]
                )
                logger.info("分类器已加载：{}（{} 类）", self.path.name, len(self.labels))
            except Exception as exc:
                self._failed = True
                logger.warning("分类器加载失败，跳过这一级：{}", exc)
        return self._session

    def _preprocess(self, image_bgr: np.ndarray) -> np.ndarray:
        import cv2

        h, w = image_bgr.shape[:2]
        scale = _SHORT_EDGE / float(min(h, w))
        resized = cv2.resize(
            image_bgr,
            (max(_CROP, int(round(w * scale))), max(_CROP, int(round(h * scale)))),
            interpolation=cv2.INTER_LINEAR,
        )
        rh, rw = resized.shape[:2]
        top = (rh - _CROP) // 2
        left = (rw - _CROP) // 2
        cropped = resized[top : top + _CROP, left : left + _CROP]
        rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        rgb = (rgb - _MEAN) / _STD
        return np.transpose(rgb, (2, 0, 1))[None, ...].astype(np.float32)

    def classify(self, image_bgr: np.ndarray) -> dict[str, Any] | None:
        """返回 {label, key, score, healthy, top3}；模型不可用时返回 None。"""
        session = self._ensure_session()
        if session is None:
            return None
        try:
            tensor = self._preprocess(image_bgr)
            logits = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
            exp = np.exp(logits - logits.max())
            probs = exp / exp.sum()
            order = np.argsort(probs)[::-1][:3]
            best = int(order[0])
            label = self.labels.get(best, "")
            if not label:
                return None
            healthy = label.startswith("Healthy")
            return {
                "label": label,
                "key": "healthy" if healthy else CLASS_TO_KNOWLEDGE.get(label, ""),
                "score": float(probs[best]),
                "healthy": healthy,
                "top3": [
                    {"label": self.labels.get(int(i), ""), "score": float(probs[int(i)])}
                    for i in order
                ],
            }
        except Exception as exc:
            logger.warning("分类器推理失败：{}", exc)
            return None

    def warmup(self) -> None:
        """开机预热：首次加载 + 图优化有几百毫秒到数秒，别让第一位农户等。"""
        if not self.available:
            return
        try:
            started = time.perf_counter()
            self.classify(np.zeros((_CROP, _CROP, 3), dtype=np.uint8))
            logger.info("分类器预热完成，耗时 {:.1f}s", time.perf_counter() - started)
        except Exception as exc:
            logger.warning("分类器预热失败：{}", exc)


classifier = Classifier()
