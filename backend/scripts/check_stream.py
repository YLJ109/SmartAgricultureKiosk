"""验证流式问答：量首字延迟、总耗时、分块数，并确认降级路径也照常流式返回。

用法（backend 目录下）：
    python scripts/check_stream.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8002"
QUESTIONS = ["番茄叶子发黄是怎么回事", "玉米什么时间追肥最好"]


def main() -> int:
    with httpx.Client(timeout=120, trust_env=False) as c:
        r = c.post(f"{BASE}/api/auth/guest", json={"display_name": "流式验证", "lang": "zh-CN"})
        if r.status_code != 200:
            print("游客登录失败：", r.status_code, r.text[:200])
            return 1
        token = (r.json() or {}).get("access_token", "")
        headers = {"Authorization": f"Bearer {token}"}

        for q in QUESTIONS:
            t0 = time.perf_counter()
            first_at = None
            chunks = 0
            text = ""
            meta: dict = {}

            with c.stream(
                "POST", f"{BASE}/api/chat/stream",
                json={"question": q, "lang": "zh-CN"}, headers=headers,
            ) as resp:
                if resp.status_code != 200:
                    print(f"HTTP {resp.status_code}  {resp.read()[:200]}")
                    return 1
                ctype = resp.headers.get("content-type", "")
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        evt = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    if evt.get("type") == "delta":
                        if first_at is None:
                            first_at = time.perf_counter() - t0
                        chunks += 1
                        text += evt.get("text", "")
                    else:
                        meta = evt

            total = time.perf_counter() - t0
            print("-" * 68)
            print(f"问题      {q}")
            print(f"响应头    {ctype}")
            print(f"首字延迟  {first_at:.2f}s     总耗时 {total:.2f}s     分块数 {chunks}")
            print(f"来源      {meta.get('source')} / {meta.get('provider_label')} / {meta.get('model')}")
            print(f"答案      {text[:160]}")
    print("-" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
