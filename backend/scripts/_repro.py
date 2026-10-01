"""复现 measure 的合成病叶图，直接看后端识别返回什么。用完即删。"""
import httpx
from PIL import Image, ImageDraw

# 与 measure-layout.cjs 里 canvas 画的完全一致
img = Image.new("RGB", (640, 640), "#ffffff")
d = ImageDraw.Draw(img)
d.ellipse([320 - 285, 320 - 300, 320 + 285, 320 + 300], fill="#40803a")
for x, y, r in [(220, 240, 48), (380, 300, 40), (300, 410, 44), (430, 210, 32), (200, 400, 30), (350, 180, 26)]:
    d.ellipse([x - r, y - r, x + r, y + r], fill="#683e20")
img.save("_tmp_leaf.jpg", quality=92)
print("合成图已生成")

BASE = "http://127.0.0.1:8002"
with httpx.Client(timeout=180, trust_env=False) as c:
    r = c.post(f"{BASE}/api/auth/guest", json={"display_name": "t", "lang": "zh-CN"})
    token = (r.json() or {}).get("access_token", "")
    with open("_tmp_leaf.jpg", "rb") as fh:
        r = c.post(
            f"{BASE}/api/recognize",
            files={"file": ("leaf.jpg", fh, "image/jpeg")},
            data={"lang": "zh-CN", "crop": "", "channel": "local"},
            headers={"Authorization": f"Bearer {token}"},
        )
    print("HTTP", r.status_code)
    if r.status_code != 200:
        print(r.text[:500])
        raise SystemExit(1)
    data = r.json()
    for k in ("name", "category", "class_key", "confidence", "engine", "matched", "is_reference"):
        print(f"  {k}: {data.get(k)}")
    print("  boxes 数量:", len(data.get("boxes") or []))
    print("  image_url:", data.get("image_url"))
    print("  reason:", str(data.get("reason"))[:400])
