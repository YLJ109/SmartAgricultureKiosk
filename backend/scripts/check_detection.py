"""真实检测链路自检。

在 backend 目录下运行：

    python scripts/check_detection.py                  # 抽查 uploads 里最新的 3 张
    python scripts/check_detection.py a.jpg b.jpg      # 指定图片

它回答三个问题：模型到底加载上没有、每张图最终结论来自检测链的哪一级、
以及有没有把启发式结果冒充成模型检出。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import settings         # noqa: E402
from app.core import vision             # noqa: E402
from app.core.detector import detector  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def show_status() -> None:
    st = detector.status()
    print("=" * 72)
    print("模型状态")
    print("=" * 72)
    for key, label in (("plant_model", "叶部病害模型"), ("pest_model", "农田昆虫模型")):
        m = st[key]
        print(f"  {label}  {m['file']:<30} 文件就绪={m['ready']}  可映射类别={m['classes']}")
    print(f"  知识库可映射类别共 {len(st['mapped_knowledge_classes'])} 个")
    print()

    cred = settings.provider_credentials("zhipu")
    print(f"  大模型厂商：{settings.active_provider}")
    print(f"  农事问答模型：{cred['model']}")
    print(f"  图片理解模型：{settings.zhipu_vision_model}（启用={settings.vision_llm_enabled}）")
    print()


def pick_images(argv: list[str], limit: int = 3) -> list[Path]:
    if argv:
        return [Path(a) for a in argv]
    uploads = settings.upload_path
    if not uploads.exists():
        return []
    files = [p for p in uploads.iterdir() if p.is_file() and p.suffix.lower() in EXTS]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def run_one(path: Path) -> None:
    started = time.perf_counter()
    result = vision.analyze(path, "zh-CN")
    cost = (time.perf_counter() - started) * 1000

    reason = result.get("reason") or {}
    print("-" * 72)
    print(f"图片：{path.name}")
    print(f"  结论     {result.get('name') or '（未识别）'}    大类={result.get('category')}")
    print(f"  置信度   {result.get('confidence')}    风险={result.get('severity')}")
    print(f"  来源     engine={result.get('engine')}    耗时={cost:.0f}ms")
    print(f"  检测框   {len(result.get('boxes') or [])} 个    参考方案={result.get('is_reference')}")
    if reason.get("model_label"):
        print(f"  模型类名 {reason['model_label']}  conf={reason.get('model_confidence')}")
    if reason.get("vision_name"):
        print(f"  视觉判断 {reason['vision_name']}  ({reason.get('vision_model')})")
    if reason.get("gate"):
        extra = {k: reason[k] for k in ("green", "yellow", "edge") if k in reason}
        print(f"  域检查   {reason['gate']}  {extra}")


def main() -> int:
    show_status()
    images = pick_images(sys.argv[1:])
    if not images:
        print("uploads 下没有可用图片，请显式传入图片路径。")
        return 1
    for path in images:
        if not path.exists():
            print(f"跳过不存在的文件：{path}")
            continue
        try:
            run_one(path)
        except Exception as exc:  # 单张出错不影响其余
            print(f"处理 {path.name} 出错：{type(exc).__name__}: {exc}")
    print("-" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
