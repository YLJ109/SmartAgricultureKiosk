"""把知识库内容翻译成 4 种少数民族语言，写回 pest_disease.json。

为什么离线预翻译，而不是运行时调模型
------------------------------------
一体机摆在村口，断网是常态。识别报告要能在任何网络条件下都是当地语言，
所以译文必须已经躺在 JSON 里 —— 运行时翻译一旦断网就会退回中文，
而"少数民族语言下看到中文"正是要解决的那个问题。

只翻 zh-CN -> ug/kk/bo/mn 四种；en-US 是原有校对内容，不动。

用法（backend 目录下）：
    python scripts/translate_knowledge.py            # 翻译缺译文的条目
    python scripts/translate_knowledge.py --force    # 全部重译
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

TARGETS = ["ug-CN", "kk-CN", "bo-CN", "mn-CN"]
LANG_HINT = {
    "ug-CN": "维吾尔语（阿拉伯字母书写）",
    "kk-CN": "哈萨克语（阿拉伯字母书写）",
    "bo-CN": "藏文",
    "mn-CN": "传统蒙古文",
}
FIELDS = ("name", "symptoms", "cause", "treatment", "pesticide")


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return text


def translate(client: httpx.Client, url: str, headers: dict, item: dict, lang: str) -> dict | None:
    """翻一条条目的一种语言。

    为什么一次只翻一种语言：4 种语言一次性生成时输出太长，模型会在中途被截断，
    返回的 JSON 直接不合法（实测报 "Expecting ',' delimiter"）。拆开之后每次输出
    只有几百个字符，稳定得多，代价只是多几次调用。
    """
    zh = {}
    for f in FIELDS:
        block = item.get(f) or {}
        value = block.get("zh-CN")
        if value:
            zh[f] = value
    if not zh:
        return None

    prompt = (
        f"你是专业的农业技术翻译。把下面的中文农业内容翻译成{LANG_HINT[lang]}。\n"
        "要求：\n"
        "1. 保持 JSON 结构完全一致，数组元素个数与顺序不变。\n"
        "2. 农药名称与稀释倍数必须保留原数字；药剂名用当地通用译名，没有通用译名时保留原文。\n"
        "3. 只输出 JSON，不要 markdown 代码块，不要任何解释文字。\n"
        "4. 字符串内不要出现未转义的英文双引号。\n\n"
        "待翻译内容：\n" + json.dumps(zh, ensure_ascii=False)
    )
    payload = {
        "model": settings.zhipu_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 2000,
        "thinking": {"type": "disabled"},
    }
    for attempt in (0, 1, 2):
        try:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 429:
                time.sleep(3 + attempt * 3)
                continue
            resp.raise_for_status()
            content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
            data = json.loads(_strip_fence(content))
            if isinstance(data, dict) and data.get("name"):
                return data
            print(f"      返回结构不对：{str(data)[:80]}")
        except Exception as exc:
            print(f"      第 {attempt + 1} 次失败：{type(exc).__name__} {exc}")
            time.sleep(2)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已有译文的也重新翻")
    ap.add_argument("--only", default="", help="只翻指定 key（逗号分隔），便于补漏")
    args = ap.parse_args()

    path = Path("knowledge/pest_disease.json")
    backup = path.with_suffix(".json.bak")
    backup.write_bytes(path.read_bytes())  # 翻译过程中随时可回滚
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["classes"]

    only = {k.strip() for k in args.only.split(",") if k.strip()}
    if only:
        items = [it for it in items if it["key"] in only]

    cred = {
        "api_key": settings.zhipu_api_key,
        "base_url": settings.zhipu_base_url,
        "model": settings.zhipu_model,
    }
    if not cred["api_key"]:
        print("未配置 ZHIPU_API_KEY，无法翻译")
        return 1
    url = cred["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cred['api_key']}", "Content-Type": "application/json"}

    done = skipped = failed = 0
    with httpx.Client(timeout=180, trust_env=False) as client:
        for it in items:
            missing = [
                lang
                for lang in TARGETS
                if args.force or any(lang not in (it.get(f) or {}) for f in FIELDS)
            ]
            if not missing:
                skipped += 1
                continue
            print(f"[{it['key']}] {it['name']['zh-CN']}  待补：{', '.join(missing)}")
            for lang in missing:
                data = translate(client, url, headers, it, lang)
                if not data:
                    failed += 1
                    print(f"      ✗ {lang}")
                    continue
                for f in FIELDS:
                    if f in data:
                        it[f][lang] = data[f]
                done += 1
                print(f"      ✓ {lang}")
                path.write_text(
                    json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                time.sleep(0.8)  # 免费档别打太密

    print(f"\n完成 {done} 条，跳过 {skipped} 条（已有译文），失败 {failed} 条")
    print(f"备份在 {backup.name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
