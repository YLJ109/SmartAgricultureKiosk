"""启发式视觉分析：不依赖任何深度学习模型，纯 CPU、离线可用。

为什么这么做
------------
完整方案里的 YOLOv8 病害/虫害双模型权重合计约 226MB，需要 torch + onnxruntime，
不适合作为"开箱即跑"的默认路径。所以本项目默认走启发式：
用颜色与纹理特征先落到「问题大类」，再与知识库的特征指纹做匹配，给出细分类候选。

它不假装自己是深度学习模型 —— 返回结果里带 `engine="heuristic"` 与 `reason`，
前端会明确标注"参考方案"，避免把启发式结果当处方用。

特征定义（全部归一到 0~1）
--------------------------
green_ratio     绿色像素占比（健康叶肉）
chlorosis_ratio 黄/橙失绿像素占比（缺氮、病毒病、早衰）
necrosis_ratio  褐/黑坏死像素占比（病斑、焦枯）
whitish_ratio   白/灰粉状像素占比（白粉病、药害白化、白色背景）
purple_ratio    紫红像素占比（缺磷、低温胁迫）
spot_density    小面积暗斑连通块密度（点状病斑 / 虫体群集）
edge_density    相邻像素灰度跳变比例（纹理复杂度）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from app.core import knowledge

# ---------- 阈值 ----------
_MAX_SIDE = 160            # 分析分辨率，越大越慢；160 已足够稳定
_EDGE_THRESHOLD = 32       # 灰度跳变阈值
_EDGE_REFERENCE = 0.35     # 归一化参考值：边缘密度达到 35% 视为 1.0
_SPOT_MAX_AREA_RATIO = 0.03  # 连通块面积小于整体 3% 才算"斑点"
_PLANT_MIN_RATIO = 0.18    # 植物像素低于此值判定为"非作物照片"
_REPORT_MIN_SCORE = 0.70   # 达到此分才报出具体病名
_HINT_MIN_SCORE = 0.52     # 达到此分给"最接近"的候选与参考方案


# ==========================================================================
# 像素分类
# ==========================================================================

def _classify(r: int, g: int, b: int) -> str:
    mx, mn = max(r, g, b), min(r, g, b)

    # 白 / 灰：亮且低饱和（白粉霉层、药害白化、白色背景纸）
    if mn > 165 and (mx - mn) < 42:
        return "whitish"

    # 紫红：红>蓝>绿，且与绿色有明显区分（缺磷、低温）
    if r > 78 and b > 62 and r > b > g and (r - g) > 18 and (b - g) > 8:
        return "purple"

    # 绿：绿通道显著占优（健康叶肉）
    if g > 58 and g >= r * 1.06 and g >= b * 1.10:
        return "green"

    # 黄 / 橙：红绿接近且都明显高于蓝（失绿黄化）
    if r > 110 and g > 100 and b < 125 and (mx - b) > 42 and abs(r - g) < 72:
        return "chlorosis"

    # 暗：整体很暗（黑斑、坏死中心）
    if mx < 92:
        return "necrosis"

    # 褐：红>绿>蓝 的中间调（病斑、焦边）
    if r > 78 and r > g > b and (r - b) > 26:
        return "necrosis"

    return "other"


def _blobs(mask: list[bool], w: int, h: int) -> list[dict[str, float]]:
    """4-邻域连通标记，返回每个连通块的外接框（相对坐标 0~1）与面积占比。

    同时服务于两个用途：
    - spot_density：小面积连通块的数量 = 点状病斑密度
    - 检测框：大面积连通块的外接框 = 病斑位置
    纯 Python 在 160×160 上跑是毫秒级，不需要引入 numpy/opencv。
    """
    seen = bytearray(w * h)
    out: list[dict[str, float]] = []
    total = w * h

    for start in range(total):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        minx = maxx = start % w
        miny = maxy = start // w
        area = 0

        while stack:
            idx = stack.pop()
            area += 1
            y, x = divmod(idx, w)
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
            for n in (idx - 1, idx + 1, idx - w, idx + w):
                if n < 0 or n >= total or seen[n] or not mask[n]:
                    continue
                # idx±1 会跨行串到上一行行尾，用曼哈顿距离挡掉
                ny, nx = divmod(n, w)
                if abs(nx - x) + abs(ny - y) != 1:
                    continue
                seen[n] = 1
                stack.append(n)

        out.append(
            {
                "x": minx / w,
                "y": miny / h,
                "w": (maxx - minx + 1) / w,
                "h": (maxy - miny + 1) / h,
                "area": area / total,
            }
        )
    return out


def _connected_blob_ratio(mask: list[bool], w: int, h: int, max_area: int) -> float:
    """小面积连通块密度，用于区分点状病斑与大片枯斑。"""
    small = sum(1 for b in _blobs(mask, w, h) if b["area"] * w * h <= max_area)
    return min(small / 100.0, 1.0)


def _estimate_background(pixels: list[tuple[int, int, int]], w: int, h: int) -> tuple[tuple[int, int, int], float]:
    """用最外一圈像素估计背景色，并返回背景像素占比。

    为什么必须做这件事
    ----------------
    一体机明确引导用户"把病叶平放在白纸上拍照"。如果不剔除背景，那一圈白纸会
    把 whitish_ratio 顶到很高，导致**每一张白底照片都被判成白粉病**。
    这是实测踩到的坑，不是理论担心。
    """
    border: list[tuple[int, int, int]] = []
    for x in range(w):
        border.append(pixels[x])
        border.append(pixels[(h - 1) * w + x])
    for y in range(h):
        border.append(pixels[y * w])
        border.append(pixels[y * w + w - 1])

    def median(channel: int) -> int:
        vals = sorted(p[channel] for p in border)
        return vals[len(vals) // 2]

    bg = (median(0), median(1), median(2))

    def near(c: tuple[int, int, int]) -> bool:
        return abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) < 96

    ratio = sum(1 for p in border if near(p)) / max(len(border), 1)
    return bg, ratio


def _load_pixels(image_path: str | Path) -> tuple[list[tuple[int, int, int]], int, int]:
    """读图并降采样。单独抽出来，是为了让 analyze() 只解码一次图片。"""
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    img.thumbnail((_MAX_SIDE, _MAX_SIDE))
    return list(img.getdata()), img.size[0], img.size[1]


def extract_features(image_path: str | Path) -> dict[str, float]:
    """抽取颜色/纹理特征（对外便捷入口）。"""
    pixels, w, h = _load_pixels(image_path)
    return _features_from_pixels(pixels, w, h)


def _features_from_pixels(pixels: list[tuple[int, int, int]], w: int, h: int) -> dict[str, float]:
    """真正的特征计算。

    所有比值都在"前景像素"上计算：先估背景色并剔除，避免白纸/桌面污染特征。
    若背景不占主导（例如田间实拍，画面被叶片填满），则跳过剔除，按全图统计。
    """
    total = len(pixels)

    bg_color, bg_border_ratio = _estimate_background(pixels, w, h)

    def is_bg(c: tuple[int, int, int]) -> bool:
        return abs(c[0] - bg_color[0]) + abs(c[1] - bg_color[1]) + abs(c[2] - bg_color[2]) < 96

    # 只有背景确实成片出现时才剔除；否则说明是田间实拍，剔了反而丢信息
    bg_count = sum(1 for p in pixels if is_bg(p))
    bg_ratio = bg_count / total
    strip_bg = bg_border_ratio > 0.6 and bg_ratio > 0.25

    fg_pixels = [p for p in pixels if not (strip_bg and is_bg(p))] if strip_bg else pixels
    fg_total = max(len(fg_pixels), 1)

    counts = {"green": 0, "chlorosis": 0, "necrosis": 0, "whitish": 0, "purple": 0, "other": 0}
    for r, g, b in fg_pixels:
        counts[_classify(r, g, b)] += 1

    # 边缘密度与斑点掩码在全图上算：它们是纹理量，不随背景位移而失真
    gray = [(r * 299 + g * 587 + b * 114) // 1000 for r, g, b in pixels]
    edge_hits = 0
    edge_total = 0
    for y in range(h):
        row = y * w
        for x in range(w - 1):
            if abs(gray[row + x] - gray[row + x + 1]) > _EDGE_THRESHOLD:
                edge_hits += 1
            edge_total += 1
    for y in range(h - 1):
        row = y * w
        for x in range(w):
            if abs(gray[row + x] - gray[row + w + x]) > _EDGE_THRESHOLD:
                edge_hits += 1
            edge_total += 1

    dark_mask = [1 if _classify(r, g, b) == "necrosis" else 0 for r, g, b in pixels]
    spot_raw = _connected_blob_ratio([bool(v) for v in dark_mask], w, h, int(total * _SPOT_MAX_AREA_RATIO))

    return {
        "green_ratio": round(counts["green"] / fg_total, 4),
        "chlorosis_ratio": round(counts["chlorosis"] / fg_total, 4),
        "necrosis_ratio": round(counts["necrosis"] / fg_total, 4),
        "whitish_ratio": round(counts["whitish"] / fg_total, 4),
        "purple_ratio": round(counts["purple"] / fg_total, 4),
        "spot_density": round(spot_raw, 4),
        "edge_density": round(min((edge_hits / max(edge_total, 1)) / _EDGE_REFERENCE, 1.0), 4),
        # 仅用于解释，不参与打分
        "bg_ratio": round(bg_ratio, 4),
    }


# ==========================================================================
# 与知识库指纹匹配
# ==========================================================================

def _score(features: dict[str, float], cls: dict[str, Any]) -> float:
    """加权区间匹配：落在指纹区间内得满分，越远衰减越快；负权重表示"越界反而加分"。"""
    signature = cls.get("signature", {})
    weights = cls.get("weights", {})
    got = 0.0
    total_w = 0.0
    for feat, rng in signature.items():
        if feat not in features:
            continue
        lo, hi = float(rng[0]), float(rng[1])
        value = features[feat]
        raw_w = float(weights.get(feat, 1))

        if lo <= value <= hi:
            part = 1.0
        else:
            span = max(hi - lo, 0.05)
            dist = (lo - value) if value < lo else (value - hi)
            part = max(0.0, 1.0 - dist / span)

        w = abs(raw_w)
        if raw_w < 0:
            part = 1.0 - part
        got += part * w
        total_w += w

    return got / total_w if total_w else 0.0


def _dominant_category(features: dict[str, float]) -> str:
    """大类判定：作为匹配失败时的兜底结论，也让结果具备可解释性。"""
    if features["whitish_ratio"] >= 0.10:
        return "disease"          # 白粉类
    if features["purple_ratio"] >= 0.04:
        return "nutrient"         # 缺磷
    if features["chlorosis_ratio"] >= 0.25 and features["necrosis_ratio"] < 0.10:
        return "nutrient"         # 缺氮
    if features["spot_density"] >= 0.55 and features["edge_density"] >= 0.45:
        return "pest"             # 点状密集 + 高纹理 → 虫体群集
    if features["necrosis_ratio"] >= 0.05:
        return "disease"
    return "unknown"


# 每类问题该把哪些像素算作"异常区域"（用来画检测框）
_ABNORMAL_KINDS: dict[str, set[str]] = {
    "disease": {"necrosis", "chlorosis"},
    "phyto": {"necrosis", "chlorosis", "whitish"},
    "nutrient": {"chlorosis", "purple"},
    "pest": {"necrosis", "chlorosis"},
}
_BOX_MIN_AREA = 0.002    # 小于整图 0.2% 的连通块按噪声丢掉
_BOX_MAX_AREA = 0.62     # 大于 62% 的多半是整片叶背景，不是病斑
_BOX_MAX_COUNT = 5


def _build_boxes(
    pixels: list[tuple[int, int, int]],
    w: int,
    h: int,
    category: str,
    confidence: float,
) -> list[dict[str, object]]:
    """在异常区域上画检测框。

    做法：把该问题类型对应的异常像素做连通标记，取面积最大的前 N 块作为"检出区域"，
    输出相对坐标（0~1），前端按渲染尺寸换算即可，不依赖图片实际像素大小。

    单框置信度的口径：以整图匹配分作为上限，再按该区域在全部异常区域里的占比做微调。
    这样弱匹配时不会画出 95% 的框 —— 宁可标低，也不给农户一个没把握的高分。
    """
    kinds = _ABNORMAL_KINDS.get(category)
    if not kinds:
        return []

    mask = [_classify(r, g, b) in kinds for r, g, b in pixels]
    blobs = [b for b in _blobs(mask, w, h) if _BOX_MIN_AREA <= b["area"] <= _BOX_MAX_AREA]
    if not blobs:
        return []

    blobs.sort(key=lambda b: b["area"], reverse=True)
    picked = blobs[:_BOX_MAX_COUNT]
    total_area = sum(b["area"] for b in picked) or 1.0

    ceiling = confidence / 100.0 if confidence > 0 else 0.70
    ceiling = min(max(ceiling, 0.35), 0.99)

    boxes: list[dict[str, object]] = []
    for b in picked:
        share = b["area"] / total_area
        score = ceiling * (0.78 + 0.22 * min(share / 0.5, 1.0))
        boxes.append(
            {
                "x": round(b["x"], 4),
                "y": round(b["y"], 4),
                "w": round(b["w"], 4),
                "h": round(b["h"], 4),
                "kind": "lesion",
                "score": round(min(score, 0.99), 3),
            }
        )
    return boxes


def analyze(image_path: str | Path, lang: str = "zh-CN") -> dict[str, Any]:
    """主入口：返回可直接入库/出参的结构化识别结果。

    无论成功与否都返回同一套字段，调用方不需要写分支。
    """
    try:
        # 只解码一次：特征和检测框都基于同一份像素
        pixels, w, h = _load_pixels(image_path)
        features = _features_from_pixels(pixels, w, h)
    except Exception as exc:  # 图片损坏 / 缺 Pillow / 路径不存在
        logger.warning("视觉分析失败：{}", exc)
        return _unknown_result(lang, reason={"error": str(exc)}, features={})

    plant_ratio = (
        features["green_ratio"]
        + features["chlorosis_ratio"]
        + features["necrosis_ratio"]
        + features["purple_ratio"]
    )

    # 域检查门：先挡掉截图、食物、人脸等非作物照片，避免高置信度误报
    if plant_ratio < _PLANT_MIN_RATIO:
        return _unknown_result(
            lang,
            reason={"gate": "non_plant", "plant_ratio": round(plant_ratio, 4)},
            features=features,
        )

    ranked: list[tuple[float, dict[str, Any]]] = []
    for cls in knowledge.all_classes():
        ranked.append((_score(features, cls), cls))
    ranked.sort(key=lambda x: x[0], reverse=True)

    best_score, best_cls = ranked[0]
    candidates = [{"key": c["key"], "score": round(s, 4)} for s, c in ranked[:3]]

    reason = {
        "features": features,
        "plant_ratio": round(plant_ratio, 4),
        "candidates": candidates,
        "engine": "heuristic",
    }

    if best_score < _HINT_MIN_SCORE:
        # 特征不明显时只给大类，不硬报病名
        cat = _dominant_category(features)
        if cat == "unknown":
            return _unknown_result(lang, reason=reason, features=features)
        return _category_only_result(cat, lang, reason, features, _build_boxes(pixels, w, h, cat, 0.0))

    localized = knowledge.localize_class(best_cls, lang)
    confidence = round(best_score * 100, 1)

    return {
        "category": localized["category"],
        "class_key": localized["key"],
        "name": localized["name"],
        "crop": localized["crop"],
        "latin": localized["latin"],
        "confidence": confidence,
        "severity": localized["severity"],
        "symptoms": localized["symptoms"],
        "cause": localized["cause"],
        "treatment": localized["treatment"],
        "pesticide": localized["pesticide"],
        "boxes": _build_boxes(pixels, w, h, localized["category"], confidence),
        "engine": "heuristic",
        "reason": reason,
        "matched": best_score >= _REPORT_MIN_SCORE,
        # 匹配分不足时前端会标注为"最接近的参考方案"
        "is_reference": best_score < _REPORT_MIN_SCORE,
    }


def _unknown_result(lang: str, reason: dict, features: dict) -> dict[str, Any]:
    """未能识别：不编造病名，只给下一步该怎么做。"""
    from app.core.knowledge import pest_disease  # 避免循环导入

    tips = {
        "zh-CN": [
            "把病叶平放在白色纸面上，让病斑占画面一半以上再拍一张",
            "光线要均匀，避免逆光和阴影",
            "先看叶背，很多虫害和霉层在叶背更明显",
            "如果拿不准，可以点右下角呼叫工作人员帮忙",
        ],
        "en-US": [
            "Place the leaf flat on white paper so the lesion fills over half the frame",
            "Use even lighting, avoid backlight and shadows",
            "Check the leaf underside - many pests and moulds show there first",
            "If unsure, tap the help button to call a staff member",
        ],
    }
    return {
        "category": "unknown",
        "class_key": "",
        "name": knowledge.pick({"zh-CN": "未能识别", "en-US": "Unrecognized"}, lang),
        "crop": "",
        "latin": "",
        "confidence": 0.0,
        "severity": "info",
        "symptoms": tips.get(lang, tips["zh-CN"]),
        "cause": "",
        "treatment": [],
        "pesticide": [],
        "boxes": [],
        "engine": "heuristic",
        "reason": reason,
        "matched": False,
        "is_reference": False,
    }


def _category_only_result(
    cat: str,
    lang: str,
    reason: dict,
    features: dict,
    boxes: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    """只确定大类、说不出具体病名时的结果。"""
    from app.constants import CATEGORIES

    cat_label = knowledge.pick(CATEGORIES.get(cat, {}), lang)
    by_cat_tips = {
        "disease": {
            "zh-CN": ["先把下部病叶摘掉带出田外，减少传染源", "改善通风、降低湿度", "尽快取样请农技员确认具体病名后再对症用药"],
            "en-US": ["Remove and dispose of lower infected leaves first", "Improve airflow and reduce humidity", "Have an agronomist confirm the exact disease before spraying"],
        },
        "pest": {
            "zh-CN": ["翻看叶背确认是否有虫体、虫粪或蜜露", "挂黄板诱杀，并保护瓢虫等天敌", "虫口密度高时先挑治中心虫株"],
            "en-US": ["Check leaf undersides for insects, frass or honeydew", "Hang yellow sticky boards and conserve predators", "Spot-treat hot spots when pressure is high"],
        },
        "nutrient": {
            "zh-CN": ["结合叶位判断：老叶先黄多为缺氮，新叶失绿多为缺铁", "取土样检测速效养分后再配方施肥", "叶面喷施可快速缓解，但不能替代土壤施肥"],
            "en-US": ["Use leaf position: old leaves first suggests N, new leaves suggests Fe", "Soil-test before making a fertiliser plan", "Foliar spray gives fast relief but cannot replace soil application"],
        },
        "phyto": {
            "zh-CN": ["回忆最近 3 天的用药品种与浓度", "立即喷清水冲洗叶面稀释残留", "暂停一切药剂，避免二次伤害"],
            "en-US": ["Review what was sprayed in the last 3 days and at what dose", "Rinse foliage with clean water to dilute residue", "Stop all sprays to avoid compounding the damage"],
        },
    }
    tips = by_cat_tips.get(cat, {}).get(lang) or by_cat_tips.get(cat, {}).get("zh-CN", [])

    return {
        "category": cat,
        "class_key": "",
        "name": cat_label,
        "crop": "",
        "latin": "",
        "confidence": 0.0,
        "severity": "medium",
        "symptoms": [],
        "cause": knowledge.pick(
            {
                "zh-CN": "照片特征不够典型，只能判断到问题大类。",
                "en-US": "Photo features are not distinctive enough to go beyond the broad category.",
            },
            lang,
        ),
        "treatment": tips,
        "pesticide": [],
        # 说不出具体病名，但异常区域还是圈出来，方便农户自己对照
        "boxes": boxes or [],
        "engine": "heuristic",
        "reason": reason,
        "matched": False,
        "is_reference": True,
    }
