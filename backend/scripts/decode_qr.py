"""解码 measure-layout.cjs 截下的二维码，证明它是真能扫的码。

只断言页面上有一个 <svg> 是证明不了什么的：之前的占位图形也有 svg。
这里用 OpenCV 的 QRCodeDetector 把截图解一次，解得出来才算数。

用法（在 backend 目录下，或直接给绝对路径）：
    python scripts/decode_qr.py ../frontend/scripts/qr-shot.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../frontend/scripts/qr-shot.png")
    if not target.exists():
        print(f"找不到截图：{target}")
        return 2

    img = cv2.imread(str(target))
    if img is None:
        print("截图读不出来")
        return 2

    print(f"截图尺寸：{img.shape[1]}x{img.shape[0]}")
    # 二值化一下更容易解：截图是黑码白底，OTSU 足够
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    detector = cv2.QRCodeDetector()
    for label, source in (("原图", gray), ("二值化", binary)):
        data, points, _ = detector.detectAndDecode(source)
        if data:
            print(f"[{label}] 解码成功：{data}")
            if data.startswith("http://") or data.startswith("https://"):
                print("结论：这是一个指向手机上传页的可扫二维码。")
                return 0
            print("警告：解码出来了，但不是预期中的 URL。")
            return 1
        print(f"[{label}] 没解出内容")

    print("结论：这张二维码解不出来，不是可用的码。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
