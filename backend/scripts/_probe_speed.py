"""临时探针：对比几个文本模型的响应耗时，并试 GLM-4.5 的"关闭思考"开关。"""
import time

import httpx

KEY = "4c6318760d4b412983a34b6b7481260c.LelkLlczdjXYtGQi"
URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
Q = "番茄叶子发黄是怎么回事"

SYSTEM = (
    "你是一位服务中国农村的农业技术员，说话对象是老年农户。\n"
    "要求：\n"
    "1. 用大白话，短句，不用专业术语；必须用术语时顺手解释一句。\n"
    "2. 先给结论，再给 2~4 条能立刻照做的操作，每条不超过 40 字。\n"
    "3. 涉及农药时，必须写清「药剂名 + 稀释倍数 + 安全间隔期」，不确定就说不确定，不要编。\n"
    "4. 只回答问题本身，不要寒暄。\n"
)


def run(label: str, model: str, extra: dict | None = None) -> None:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": Q}],
        "temperature": 0.6,
        "max_tokens": 800,
    }
    if extra:
        payload.update(extra)
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=180, trust_env=False) as c:
            r = c.post(URL, headers={"Authorization": f"Bearer {KEY}"}, json=payload)
        cost = time.perf_counter() - t0
        if r.status_code != 200:
            print(f"{label:34s} HTTP {r.status_code}  {r.text[:120]}")
            return
        d = r.json()
        msg = (d.get("choices") or [{}])[0].get("message", {})
        txt = msg.get("content", "") or ""
        usage = d.get("usage") or {}
        print(f"{label:34s} {cost:6.1f}s  {len(txt):4d}字  tokens={usage.get('completion_tokens')}")
        print("      -> " + txt[:110].replace("\n", " "))
    except Exception as exc:
        print(f"{label:34s} 异常 {type(exc).__name__}: {exc}")


run("glm-4-flash", "glm-4-flash")
run("glm-4-flash（第二次，看波动）", "glm-4-flash")
run("glm-4.5-flash 默认", "glm-4.5-flash")
run("glm-4.5-flash 关闭思考", "glm-4.5-flash", {"thinking": {"type": "disabled"}})
run("glm-4.5-flash 关闭思考（第二次）", "glm-4.5-flash", {"thinking": {"type": "disabled"}})
