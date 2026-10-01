"""临时探针：确认智谱当前可用的免费模型，以及它们在同一张病叶图上的实际表现。"""
import base64
import io

import httpx
from PIL import Image

KEY = "4c6318760d4b412983a34b6b7481260c.LelkLlczdjXYtGQi"
URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
IMG = r"D:\front-back\AgriculturalScience\backend\uploads\d663a337f32c_test_leaf.jpg"


def data_url(path: str) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def probe(model: str, content, tag: str) -> None:
    payload = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.2}
    try:
        with httpx.Client(timeout=180, trust_env=False) as c:
            r = c.post(URL, headers={"Authorization": f"Bearer {KEY}"}, json=payload)
        if r.status_code != 200:
            print(f"[{tag:10s}] {model:26s} HTTP {r.status_code}  {r.text[:160]}")
            return
        d = r.json()
        txt = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = d.get("usage") or {}
        print(f"[{tag:10s}] {model:26s} OK  {len(txt)}字  tokens={usage.get('total_tokens')}")
        print("             -> " + txt[:160].replace("\n", " "))
    except Exception as exc:
        print(f"[{tag:10s}] {model:26s} 异常 {type(exc).__name__}: {exc}")


print("===== 文本模型（农事问答）=====")
probe("glm-4-flash", "用一句话说明番茄晚疫病怎么防治", "当前")
probe("glm-4.5-flash", "用一句话说明番茄晚疫病怎么防治", "候选")

print("\n===== 视觉模型（图片理解）=====")
image_part = [
    {"type": "text", "text": "这是农作物叶片的什么病害？只回一个中文病名，不要解释。"},
    {"type": "image_url", "image_url": {"url": data_url(IMG)}},
]
probe("glm-4v-flash", image_part, "当前")
probe("glm-4.6v-flash", image_part, "候选")
probe("glm-4.1v-thinking-flash", image_part, "候选-推理")
