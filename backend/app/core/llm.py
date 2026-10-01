"""大模型适配层：多厂商统一接入 + 无密钥时降级本地知识库。

设计取舍
--------
1. 除百度文心外，国内主流厂商都提供 OpenAI 兼容端点，所以主路径只写一套协议，
   百度单独一个分支（AK/SK 换 access_token）。新增厂商通常只需加一行配置。
2. 任何异常（超时、401、限流、网络不通）都不抛给前端，而是降级到本地知识库回答，
   并如实标记 `source="fallback"`。农村弱网场景下这比报错更有用。
3. 无论走哪条路，回答都先做"知识库接地"：把检索到的条目塞进提示词，
   减少大模型凭空编造农技建议（尤其是农药用量）。
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

from app.config import settings
from app.core import knowledge

PROVIDER_LABELS = {
    "zhipu": "智谱 GLM",
    "qwen": "阿里通义千问",
    "deepseek": "DeepSeek",
    "moonshot": "月之暗面 Kimi",
    "baidu": "百度文心一言",
    "custom": "自定义端点",
    "none": "本地知识库",
}

_LANG_NAMES = {
    "zh-CN": "简体中文",
    "en-US": "English",
    "ug-CN": "维吾尔语（ئۇيغۇرچە）",
    "kk-CN": "哈萨克语（قازاق تىلى）",
    "bo-CN": "藏语（བོད་སྐད།）",
    "mn-CN": "传统蒙古文（ᠮᠣᠩᠭᠣᠯ）",
}


# ==========================================================================
# 本地知识库回答（永远可用的兜底）
# ==========================================================================

def local_answer(question: str, lang: str = "zh-CN") -> str:
    """不调用大模型，直接用知识库拼一个回答。

    优先级：病虫害词条 → 缺素词条 → 农事日历 → 通用引导。
    """
    blocks: list[str] = []

    for cls in knowledge.search_classes(question, lang, limit=2):
        lines = [f"【{cls['name']}】"]
        if cls.get("crop"):
            lines.append(f"作物：{cls['crop']}　拉丁名：{cls.get('latin') or '-'}")
        if cls["symptoms"]:
            lines.append("症状：" + "；".join(cls["symptoms"][:3]))
        if cls["cause"]:
            lines.append("原因：" + cls["cause"])
        if cls["treatment"]:
            lines.append("防治：" + "；".join(cls["treatment"][:4]))
        if cls["pesticide"]:
            lines.append("用药参考：" + "；".join(cls["pesticide"][:3]))
        blocks.append("\n".join(lines))

    for nutrient in knowledge.find_nutrients(question, lang):
        lines = [f"【{nutrient['name']}（{nutrient['symbol']}）】"]
        if nutrient["deficiency"]:
            lines.append("缺素表现：" + nutrient["deficiency"])
        if nutrient["advice"]:
            lines.append("施肥建议：" + "；".join(nutrient["advice"]))
        blocks.append("\n".join(lines))

    # 农事日历：按提问里出现的作物名匹配
    calendar = knowledge.crop_calendar().get("crops", [])
    for entry in calendar:
        crop_zh = (entry.get("crop") or {}).get("zh-CN", "")
        crop_en = (entry.get("crop") or {}).get("en-US", "")
        if crop_zh and (crop_zh in question or (crop_en and crop_en.lower() in question.lower())):
            from datetime import datetime

            month = str(datetime.now().month)
            data = entry.get("months", {}).get(month)
            if data:
                crop_name = knowledge.pick(entry.get("crop"), lang)
                items = knowledge.pick_list(data, lang)
                blocks.append(f"【{crop_name} · {month} 月农事】\n" + "\n".join(f"· {x}" for x in items))
            break

    if blocks:
        return "\n\n".join(blocks)

    return knowledge.pick(
        {
            "zh-CN": (
                "这个问题我暂时没有把握。\n"
                "建议您换个说法再问一次，例如带上作物名和现象：「番茄叶子发黄怎么办」。\n"
                "也可以直接点「拍照识病」上传叶子照片，我先帮您看看是什么问题。"
            ),
            "en-US": (
                "I am not confident about this one yet.\n"
                "Try rephrasing with the crop and the symptom, e.g. \"tomato leaves turning yellow\".\n"
                "You can also use Photo Diagnosis to upload a leaf photo first."
            ),
        },
        lang,
    )


# ==========================================================================
# 提示词组装
# ==========================================================================

def build_messages(question: str, lang: str, context: str = "") -> list[dict[str, str]]:
    lang_name = _LANG_NAMES.get(lang, "简体中文")
    system = (
        "你是一位服务中国农村的农业技术员，说话对象是老年农户。\n"
        "要求：\n"
        "1. 用大白话，短句，不用专业术语；必须用术语时顺手解释一句。\n"
        "2. 先给结论，再给 2~4 条能立刻照做的操作，每条不超过 40 字。\n"
        "3. 涉及农药时，必须写清「药剂名 + 稀释倍数 + 安全间隔期」，不确定就说不确定，不要编。\n"
        "4. 不推荐国家禁用农药；能靠栽培措施解决时优先给非化学方案。\n"
        "5. 只回答问题本身，不要寒暄，不要重复用户的话。\n"
        f"6. 必须使用 {lang_name} 回答。\n"
    )
    if context:
        system += (
            "\n以下是本系统知识库检索到的相关资料，请优先依据它回答；"
            "资料未覆盖的内容可以补充，但不要与资料矛盾：\n" + context
        )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]


def build_context(question: str, lang: str) -> str:
    """把检索结果压成提示词里的上下文块。"""
    chunks: list[str] = []
    for cls in knowledge.search_classes(question, lang, limit=3):
        parts = [f"【{cls['name']}】作物：{cls.get('crop') or '-'}"]
        if cls["symptoms"]:
            parts.append("症状：" + "；".join(cls["symptoms"][:3]))
        if cls["treatment"]:
            parts.append("防治：" + "；".join(cls["treatment"][:4]))
        if cls["pesticide"]:
            parts.append("用药：" + "；".join(cls["pesticide"][:3]))
        chunks.append("\n".join(parts))

    for nutrient in knowledge.find_nutrients(question, lang):
        chunks.append(f"【{nutrient['name']}】{nutrient['deficiency']}\n建议：" + "；".join(nutrient["advice"][:3]))

    return "\n\n".join(chunks)


# ==========================================================================
# 厂商调用
# ==========================================================================

class LlmResult:
    def __init__(self, answer: str, source: str, provider: str, model: str, tokens: int, latency_ms: int) -> None:
        self.answer = answer
        self.source = source
        self.provider = provider
        self.model = model
        self.tokens = tokens
        self.latency_ms = latency_ms

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "source": self.source,
            "provider": self.provider,
            "provider_label": PROVIDER_LABELS.get(self.provider, self.provider),
            "model": self.model,
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
        }


async def _call_openai_compatible(base_url: str, api_key: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """OpenAI 兼容协议（智谱 / 通义 / DeepSeek / Kimi / 自定义）。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": settings.ai_temperature,
        "max_tokens": settings.ai_max_tokens,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage") or {}
    return {"content": content, "tokens": int(usage.get("total_tokens") or 0)}


async def _call_baidu(api_key: str, secret_key: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """百度文心：先 AK/SK 换 access_token，再走自有协议。"""
    async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
        token_resp = await client.post(
            "https://aip.baidubce.com/oauth/2.0/token",
            params={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key},
        )
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise RuntimeError("百度 access_token 获取失败")

        url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/{model}"
        payload = {
            "messages": messages,
            "temperature": max(0.01, min(settings.ai_temperature, 1.0)),
            "max_output_tokens": settings.ai_max_tokens,
        }
        resp = await client.post(url, params={"access_token": access_token}, json=payload)
        resp.raise_for_status()
        data = resp.json()

    if data.get("error_code"):
        raise RuntimeError(f"百度返回错误 {data.get('error_code')}: {data.get('error_msg')}")

    usage = data.get("usage") or {}
    return {
        "content": data.get("result", ""),
        "tokens": int(usage.get("total_tokens") or 0),
    }


# ==========================================================================
# 对外入口
# ==========================================================================

async def ask(question: str, lang: str = "zh-CN", context: str | None = None) -> LlmResult:
    """农事问答主入口。永不抛异常：失败即降级。"""
    started = time.perf_counter()
    provider = settings.active_provider

    if provider == "none":
        answer = local_answer(question, lang)
        return LlmResult(answer, "local", "none", "local-knowledge", 0, _ms(started))

    ctx = build_context(question, lang) if context is None else context
    messages = build_messages(question, lang, ctx)
    cred = settings.provider_credentials(provider)

    try:
        if provider == "baidu":
            data = await _call_baidu(settings.baidu_api_key, settings.baidu_secret_key, cred["model"], messages)
        else:
            data = await _call_openai_compatible(cred["base_url"], cred["api_key"], cred["model"], messages)

        content = (data.get("content") or "").strip()
        if not content:
            raise RuntimeError("大模型返回空内容")

        return LlmResult(content, "llm", provider, cred["model"], data.get("tokens", 0), _ms(started))

    except Exception as exc:
        logger.warning("调用 {} 失败，降级本地知识库：{}", provider, exc)
        answer = local_answer(question, lang)
        # 降级时把原因带回，便于后台排查密钥/网络问题
        return LlmResult(answer, "fallback", provider, cred["model"], 0, _ms(started))


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def healthcheck() -> dict[str, Any]:
    """后台"测试连通性"用：发一句最短的话，看能不能通。"""
    provider = settings.active_provider
    if provider == "none":
        return {"ok": False, "provider": "none", "message": "未配置大模型，当前使用本地知识库"}

    cred = settings.provider_credentials(provider)
    try:
        probe = [{"role": "user", "content": "回复两个字：正常"}]
        if provider == "baidu":
            await _call_baidu(settings.baidu_api_key, settings.baidu_secret_key, cred["model"], probe)
        else:
            await _call_openai_compatible(cred["base_url"], cred["api_key"], cred["model"], probe)
        return {"ok": True, "provider": provider, "model": cred["model"], "message": "连接正常"}
    except Exception as exc:
        return {"ok": False, "provider": provider, "model": cred["model"], "message": f"连接失败：{exc}"}
