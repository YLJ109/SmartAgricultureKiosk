"""本地真实检测引擎：YOLOv8 ONNX 双模型（叶部病害 / 农田昆虫）。

模型文件
--------
- plant_disease_yolov8n.onnx   叶部病害 55 类（YOLOv8n）
- insect_best.onnx             农田昆虫 21 类（YOLOv8m）

两者都放在 `backend/data/models/` 下。该目录已在 .gitignore 中，不进版本库。
文件缺失或加载失败时引擎返回空结果，由上层继续降级，不会让服务起不来。

为什么用 ONNX 而不是 ultralytics + torch
-----------------------------------------
一体机要能"离线装、离线跑"。onnxruntime CPU 包只有十几 MB，而 torch +
torchvision + ultralytics 装完是几百 MB，还要联网拉权重。代价是 YOLOv8 的后处理
得自己写，见 `_postprocess`。

类别映射原则
------------
模型输出的是它自己训练时的英文类名（如 `Corn leaf blight`），本项目对外要用的是
知识库里的条目（`knowledge/pest_disease.json` 的 key，如 `maize_leaf_blight`），
所以必须有一张显式映射表：

- 症状与作物对得上的，映射到对应条目；
- 叶片健康（`* healthy`）映射到 `healthy` 条目 —— 这是模型真实的判断结果，
  比强行报一个病名有用；
- 昆虫模型里的**益虫/中性昆虫**（瓢虫、蜜蜂、蜻蜓、草蛉、螳螂、蜘蛛、蚂蚁…）
  一律映射为 `None`：把益虫报成虫害会直接误导农户去打药；
- 确属害虫但知识库暂无对应条目的（蝗虫、象甲、蝽…）映射为 `GENERIC_PEST`，
  上层只报「虫害」大类并给通用处置建议，不硬套成别的虫名去开药。
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from loguru import logger

from app.config import settings

# ==========================================================================
# 叶部病害模型（55 类）—— 类别名 -> 本项目知识库 key
# ==========================================================================
PLANT_MODEL_NAMES: list[str] = [
    "Apple black rot", "Apple cedar rust", "Apple healthy", "Apple scab",
    "Bell pepper bacterial_spot", "Bell pepper healthy", "Blueberry healthy",
    "Cassava bacterial blight", "Cassava brown leaf spot", "Cassava healthy", "Cassava mosaic", "Cassava root rot",
    "Cherry healthy", "Cherry powdery mildew",
    "Citrus haunglongbing",
    "Corn brown spots", "Corn charcoal", "Corn chlorotic leaf spot", "Corn gray leaf spot", "Corn healthy",
    "Corn insects damages", "Corn leaf blight", "Corn mildew", "Corn purple discoloration", "Corn rust leaf",
    "Corn smut", "Corn streak", "Corn stripe", "Corn violet decoloration", "Corn yellow spots", "Corn yellowing",
    "Grape Esca -Black_Measles-", "Grape black rot", "Grape healthy", "Grape leaf blight",
    "Peach bacterial spot", "Peach healthy",
    "Potato early blight", "Potato healthy", "Potato late blight",
    "Raspberry healthy", "Soybean healthy",
    "Squash powdery mildew",
    "Strawberry healthy", "Strawberry leaf scorch",
    "Tomato bacterial wilt", "Tomato blight leaf", "Tomato brown spots", "Tomato healthy", "Tomato late blight leaf",
    "Tomato leaf mosaic virus", "Tomato leaf yellow virus", "Tomato septoria leaf spot", "Tomato spider mites", "Tomato target spot",
]

PLANT_CLASS_MAP: dict[str, str | None] = {
    # ---- 苹果：黑腐/锈病/疮痂都归到苹果疮痂病（知识库现有条目）----
    "Apple black rot": "apple_scab",
    "Apple cedar rust": "apple_scab",
    "Apple scab": "apple_scab",
    "Apple healthy": "healthy",
    # ---- 甜椒细菌性斑点：症状与番茄早疫病（叶斑类）最接近，归此条 ----
    "Bell pepper bacterial_spot": "tomato_early_blight",
    "Bell pepper healthy": "healthy",
    "Blueberry healthy": "healthy",
    # ---- 木薯：细菌性枯萎/褐斑/花叶都表现为叶斑，归番茄早疫病；根腐归晚疫病 ----
    "Cassava bacterial blight": "tomato_early_blight",
    "Cassava brown leaf spot": "tomato_early_blight",
    "Cassava healthy": "healthy",
    "Cassava mosaic": "tomato_early_blight",
    "Cassava root rot": "tomato_late_blight",
    "Cherry healthy": "healthy",
    "Cherry powdery mildew": "cucumber_powdery_mildew",
    # ---- 柑橘黄龙病：知识库有柑橘溃疡病这一柑橘类条目 ----
    "Citrus haunglongbing": "citrus_canker",
    # ---- 玉米：各类叶斑/霉层/锈病/黑粉统一归玉米大斑病 ----
    "Corn brown spots": "maize_leaf_blight",
    "Corn charcoal": "maize_leaf_blight",
    "Corn chlorotic leaf spot": "maize_leaf_blight",
    "Corn gray leaf spot": "maize_leaf_blight",
    "Corn healthy": "healthy",
    "Corn insects damages": "corn_borer",
    "Corn leaf blight": "maize_leaf_blight",
    "Corn mildew": "maize_leaf_blight",
    # 玉米紫化 = 缺磷导致花青素累积
    "Corn purple discoloration": "phosphorus_deficiency",
    "Corn rust leaf": "maize_leaf_blight",
    "Corn smut": "maize_leaf_blight",
    "Corn streak": "maize_leaf_blight",
    "Corn stripe": "maize_leaf_blight",
    "Corn violet decoloration": "phosphorus_deficiency",
    "Corn yellow spots": "maize_leaf_blight",
    # 整体黄化 = 缺氮
    "Corn yellowing": "nitrogen_deficiency",
    # ---- 葡萄：黑腐/黑麻疹/叶枯都归晚疫病（均可致叶部褐枯）----
    "Grape Esca -Black_Measles-": "tomato_late_blight",
    "Grape black rot": "tomato_late_blight",
    "Grape healthy": "healthy",
    "Grape leaf blight": "tomato_late_blight",
    "Peach bacterial spot": "tomato_early_blight",
    "Peach healthy": "healthy",
    # ---- 马铃薯：早疫 -> 早疫病条目，晚疫 -> 晚疫病条目（同属茄科，症状一致）----
    "Potato early blight": "tomato_early_blight",
    "Potato healthy": "healthy",
    "Potato late blight": "tomato_late_blight",
    "Raspberry healthy": "healthy",
    "Soybean healthy": "healthy",
    "Squash powdery mildew": "cucumber_powdery_mildew",
    "Strawberry healthy": "healthy",
    "Strawberry leaf scorch": "tomato_late_blight",
    # ---- 番茄 ----
    "Tomato bacterial wilt": "tomato_early_blight",
    "Tomato blight leaf": "tomato_late_blight",
    "Tomato brown spots": "tomato_early_blight",
    "Tomato healthy": "healthy",
    "Tomato late blight leaf": "tomato_late_blight",
    "Tomato leaf mosaic virus": "tomato_early_blight",
    "Tomato leaf yellow virus": "tomato_early_blight",
    "Tomato septoria leaf spot": "tomato_early_blight",
    # 叶螨是蜱螨目，不是昆虫，用药是杀螨剂而非杀虫剂，单列条目
    "Tomato spider mites": "red_spider_mite",
    "Tomato target spot": "tomato_early_blight",
}

# ==========================================================================
# 农田昆虫模型（21 类）—— 类别名 -> 本项目知识库 key
# ==========================================================================
INSECT_MODEL_NAMES: list[str] = [
    "ant", "aphid", "bees", "butterfly", "caterpillar", "cicada", "dragonfly",
    "grasshopper", "green_lacewing", "ladybug", "leafhopper", "mantis",
    "mole_cricket", "planthopper", "rhino_beetle", "rice_bug", "spider",
    "stem_borer", "stink_bug", "undefined", "weevil",
]

#: 确属害虫、但知识库暂无对应条目时的归类标记。
#: 上层只报「虫害」大类并给通用建议，不硬套到别的虫名上开药。
GENERIC_PEST = "__generic_pest__"

INSECT_CLASS_MAP: dict[str, str | None] = {
    "ant": None,             # 中性：常与蚜虫共生，本身不直接危害作物
    "aphid": "aphid",
    "bees": None,            # 传粉益虫
    "butterfly": None,       # 传粉/中性
    "caterpillar": "corn_borer",            # 鳞翅目幼虫 -> 螟虫类
    "cicada": GENERIC_PEST,
    "dragonfly": None,       # 捕食性益虫
    "grasshopper": GENERIC_PEST,
    "green_lacewing": None,  # 草蛉：捕食性益虫
    "ladybug": None,         # 瓢虫：捕食性益虫
    "leafhopper": "brown_planthopper",      # 叶蝉与飞虱近缘，防治用药一致
    "mantis": None,          # 捕食性益虫
    "mole_cricket": GENERIC_PEST,
    "planthopper": "brown_planthopper",
    "rhino_beetle": GENERIC_PEST,
    "rice_bug": "brown_planthopper",
    "spider": None,          # 蜘蛛：捕食性，田间益虫
    "stem_borer": "corn_borer",
    "stink_bug": GENERIC_PEST,
    "undefined": None,
    "weevil": GENERIC_PEST,
}

#: 两个模型合计能产出细分类（自动算，避免写死数字造成"过度宣称"）
MODEL_CLASS_KEYS: frozenset[str] = frozenset(
    v for v in list(PLANT_CLASS_MAP.values()) + list(INSECT_CLASS_MAP.values())
    if v and v != GENERIC_PEST
)


# ==========================================================================
# 单个模型的检测结果
# ==========================================================================

@dataclass
class Box:
    """一个检测框，相对坐标 0~1（前端按渲染尺寸换算，与图片实际像素无关）。"""

    x: float
    y: float
    w: float
    h: float
    score: float
    label: str

    def as_dict(self, kind: str = "lesion") -> dict:
        return {
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "w": round(self.w, 4),
            "h": round(self.h, 4),
            "kind": kind,
            "score": round(self.score, 3),
        }


@dataclass
class ModelHit:
    """一个模型的推理结论。"""

    class_key: str          # 知识库 key，或 GENERIC_PEST，或 ""（无可信检出）
    label: str              # 模型原始类名
    confidence: float       # 0~1
    boxes: list[Box] = field(default_factory=list)
    source: str = ""        # plant_model | insect_model


# ==========================================================================
# 推理引擎
# ==========================================================================

class _YoloModel:
    """一个 YOLOv8 ONNX 模型。懒加载 + 结果缓存。"""

    def __init__(self, path: Path, names: list[str], class_map: dict[str, str | None],
                 conf: float, max_boxes: int, tag: str) -> None:
        self.path = path
        self.names = names
        self.class_map = class_map
        self.conf = conf
        self.max_boxes = max_boxes
        self.tag = tag
        self._session = None
        self._failed = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.path.exists() and not self._failed

    def load(self) -> None:
        """加载 ONNX。失败只记一次，之后直接跳过 —— 不能让每次请求都重试 100MB 的加载。"""
        if self._session is not None or self._failed:
            return
        with self._lock:
            if self._session is not None or self._failed:
                return
            if not self.path.exists():
                logger.warning("模型文件不存在，跳过 {}：{}", self.tag, self.path)
                self._failed = True
                return
            try:
                import onnxruntime as ort

                opts = ort.SessionOptions()
                # 默认 intra_op 线程 = 物理核数，多请求并发时会线程超订、吞吐反而下降
                opts.intra_op_num_threads = max(1, int(settings.onnx_intra_threads))
                opts.inter_op_num_threads = max(1, int(settings.onnx_inter_threads))
                self._session = ort.InferenceSession(
                    str(self.path), sess_options=opts, providers=["CPUExecutionProvider"]
                )
                logger.info("已加载 {} 模型：{}", self.tag, self.path.name)
            except Exception as exc:
                logger.warning("{} 模型加载失败，将跳过该模型：{}", self.tag, exc)
                self._failed = True

    def predict(self, image_bgr: np.ndarray) -> ModelHit:
        self.load()
        if self._session is None:
            return ModelHit("", "", 0.0, [], self.tag)

        tensor, transform = _letterbox(image_bgr, settings.detect_img_size)
        inp = self._session.get_inputs()[0].name
        out = self._session.run(None, {inp: tensor})[0]
        return _postprocess(
            out, image_bgr.shape, transform,
            names=self.names, class_map=self.class_map,
            threshold=self.conf, max_boxes=self.max_boxes, tag=self.tag,
        )


def _letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, tuple[float, float, float]]:
    """等比缩放 + 灰边填充到 size×size（对齐 ultralytics 的推理方式）。

    返回 (NCHW 张量, (scale, pad_x, pad_y))，后者用来把框还原回原图坐标。
    """
    import cv2

    h, w = image.shape[:2]
    scale = min(size / h, size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(image, (nw, nh))
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x, pad_y = (size - nw) / 2.0, (size - nh) / 2.0
    canvas[int(pad_y):int(pad_y) + nh, int(pad_x):int(pad_x) + nw] = resized
    canvas = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    tensor = canvas.astype(np.float32) / 255.0
    return tensor.transpose(2, 0, 1)[None, ...], (scale, pad_x, pad_y)


def _postprocess(
    output: np.ndarray,
    orig_shape: tuple,
    transform: tuple[float, float, float],
    names: list[str],
    class_map: dict[str, str | None],
    threshold: float,
    max_boxes: int,
    tag: str,
) -> ModelHit:
    """YOLOv8 输出后处理，输出形状 (1, 4+NC, 8400)。

    这里有个容易踩的坑：YOLOv8 的输出**没有独立的 objectness 通道**，
    布局是 [cx, cy, w, h, cls0, cls1, ...]。如果按 v5 的格式去解析
    （obj=[:,4]、cls=[:,5:]），会漏掉第 0 类、类别索引整体错位、
    置信度还会被错误地乘一次，最后所有框都被阈值抹平。
    """
    output = np.asarray(output).squeeze(0).transpose(1, 0)  # (8400, 4+NC)
    xywh = output[:, :4]
    probs = output[:, 4:]
    ncls = probs.shape[1]

    # 只保留有映射的类别：益虫、中性目标、未覆盖类别一律置零，避免误报
    valid = np.array(
        [class_map.get(names[c]) is not None if c < len(names) else False for c in range(ncls)],
        dtype=bool,
    )
    probs = probs * valid
    conf = probs.max(axis=1)          # 无 objectness，类别分即置信度
    mask = conf > threshold
    if not np.any(mask):
        return ModelHit("", "", 0.0, [], tag)

    order = np.argsort(-conf[mask])[: max_boxes * 4]
    scale, pad_x, pad_y = transform
    h_img, w_img = orig_shape[:2]

    picked: list[Box] = []
    best_key, best_label, best_conf = "", "", 0.0
    for idx in order:
        box = xywh[mask][idx]
        score = float(conf[mask][idx])
        cls = int(np.argmax(probs[mask][idx]))
        name = names[cls] if cls < len(names) else ""
        key = class_map.get(name)
        if key is None:
            continue

        cx, cy, bw, bh = box
        x1 = float(max(0.0, (cx - bw / 2 - pad_x) / scale))
        y1 = float(max(0.0, (cy - bh / 2 - pad_y) / scale))
        x2 = float(min(w_img, (cx + bw / 2 - pad_x) / scale))
        y2 = float(min(h_img, (cy + bh / 2 - pad_y) / scale))
        if x2 <= x1 or y2 <= y1:
            continue

        # 中心距去重：同一条虫/同一块病斑被相邻候选重复框出时只留一个
        ccx, ccy = (x1 + x2) / 2, (y1 + y2) / 2
        dup = any(
            abs(ccx - (b.x + b.w / 2) * w_img) < 0.4 * b.w * w_img
            and abs(ccy - (b.y + b.h / 2) * h_img) < 0.4 * b.h * h_img
            for b in picked
        )
        if dup:
            continue

        picked.append(
            Box(x1 / w_img, y1 / h_img, (x2 - x1) / w_img, (y2 - y1) / h_img, score, name)
        )
        if score > best_conf:
            best_conf, best_key, best_label = score, key, name
        if len(picked) >= max_boxes:
            break

    if not picked:
        return ModelHit("", "", 0.0, [], tag)
    return ModelHit(best_key, best_label, best_conf, picked, tag)


# ==========================================================================
# 对外单例
# ==========================================================================

class Detector:
    """病害 + 虫害双模型的对外入口。"""

    def __init__(self) -> None:
        base = Path(settings.models_dir)
        if not base.is_absolute():
            base = Path(__file__).resolve().parents[2] / base
        # 病害模型小（约 12MB），随服务一起用；虫害模型近 90MB，首次真正需要时才加载
        self.plant = _YoloModel(
            base / settings.plant_model_file, PLANT_MODEL_NAMES, PLANT_CLASS_MAP,
            settings.plant_conf_threshold, 3, "病害",
        )
        self.pest = _YoloModel(
            base / settings.pest_model_file, INSECT_MODEL_NAMES, INSECT_CLASS_MAP,
            settings.pest_conf_threshold, 5, "虫害",
        )
        self._cache: dict[str, tuple[ModelHit, ModelHit]] = {}
        self._cache_max = 64

    def detect_plant(self, image_bgr: np.ndarray) -> ModelHit:
        return self.plant.predict(image_bgr)

    def detect_pest(self, image_bgr: np.ndarray) -> ModelHit:
        return self.pest.predict(image_bgr)

    def detect_cached(self, image_bgr: np.ndarray) -> tuple[ModelHit, ModelHit]:
        """先跑病害；病害没检出才跑虫害。带内容缓存，同一张图重复上传不重复推理。"""
        key = hashlib.md5(image_bgr.tobytes()).hexdigest()
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        plant = self.detect_plant(image_bgr)
        pest = ModelHit("", "", 0.0, [], "虫害")
        if not plant.boxes and self.pest.available:
            pest = self.detect_pest(image_bgr)

        if len(self._cache) >= self._cache_max:
            self._cache.clear()
        self._cache[key] = (plant, pest)
        return plant, pest

    def warmup(self) -> None:
        """把两个模型都加载进来，并各跑一次空推理。

        为什么要预热：虫害模型有 88MB，onnxruntime 首次加载 + 图优化实测要十几秒。
        如果留到第一次识别时才懒加载，第一个来用的农户就得对着"识别中"干等 ——
        而一体机开机到有人用之间本来就有大段空闲，正好把这步做掉。
        """
        blank = np.zeros((settings.detect_img_size, settings.detect_img_size, 3), dtype=np.uint8)
        for model in (self.plant, self.pest):
            if not model.available:
                continue
            try:
                started = time.perf_counter()
                model.predict(blank)
                logger.info("{} 模型预热完成，耗时 {:.1f}s", model.tag, time.perf_counter() - started)
            except Exception as exc:
                logger.warning("{} 模型预热失败（不影响使用，届时按需加载）：{}", model.tag, exc)

    def status(self) -> dict:
        """给 /api/system/info 用：说清楚当前到底有没有真模型在跑。"""
        return {
            "plant_model": {
                "file": self.plant.path.name,
                "ready": self.plant.path.exists() and not self.plant._failed,
                "classes": len([v for v in PLANT_CLASS_MAP.values() if v]),
            },
            "pest_model": {
                "file": self.pest.path.name,
                "ready": self.pest.path.exists() and not self.pest._failed,
                "classes": len([v for v in INSECT_CLASS_MAP.values() if v]),
            },
            "mapped_knowledge_classes": sorted(MODEL_CLASS_KEYS),
        }


detector = Detector()
