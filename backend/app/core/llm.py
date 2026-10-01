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

import asyncio
import json
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


#: 值得重试一次的状态码。免费档在高峰期会成片返回 429，
#: 智谱实测会回 `{"code":"1305","message":"该模型当前访问量过大"}`，
#: 这种等一两秒再来一次往往就通了 —— 和"参数写错了、重试也没用"要区别对待。
_RETRYABLE = {429, 503}


async def _call_openai_compatible(base_url: str, api_key: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """OpenAI 兼容协议（智谱 / 通义 / DeepSeek / Kimi / 自定义）。限流时重试一次。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": settings.ai_temperature,
        "max_tokens": settings.ai_max_tokens,
    }
    # GLM-4.5/4.6 系列默认会先"想一遍"再答：同一道题实测 14.8s，关掉思考后 8.8s，
    # 而且质量没有下降（默认档反而更容易冒出禁用农药）。对站在一体机前的老人来说，
    # 等 15 秒和等 9 秒是两种体验，所以显式关掉。
    # 这个参数只有智谱的思考型模型认，其它厂商收到会报错，所以按模型名前缀判断。
    if model.startswith(("glm-4.5", "glm-4.6")):
        payload["thinking"] = {"type": "disabled"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for attempt in (0, 1):
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds, trust_env=False) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code in _RETRYABLE and attempt == 0:
            logger.info("上游 {} 限流，1.5 秒后重试一次", resp.status_code)
            await asyncio.sleep(1.5)
            continue
        resp.raise_for_status()
        data = resp.json()
        break

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
# 图片理解（智谱 GLM-4V，免费模型）
# ==========================================================================

#: 要求模型只回一个 JSON。病名要中文，是因为回头要拿它去知识库里检索对应条目，
#: 再由知识库按用户语言输出——模型自己的多语言农技术语不可靠，知识库的才经过校对。
_VISION_PROMPT = (
    "你是植物病害诊断专家。仔细看这张农作物叶片照片，"
    "只输出一个 JSON 对象，不要任何解释文字，不要 Markdown 代码块。字段如下：\n"
    '{"category": "disease" 或 "pest" 或 "nutrient" 或 "phyto" 或 "healthy" 或 "unknown",'
    ' "name": "最可能的中文病害或虫害名称，不要带作物名前缀",'
    ' "confidence": 0 到 100 的整数,'
    ' "symptoms": ["你实际看到的症状，最多 3 条"],'
    ' "treatment": ["农户能照着做的处置建议，最多 3 条"]}\n'
    "照片里不是农作物叶片时 category 填 unknown。"
    "拿不准就降低 confidence 或直接填 unknown，绝对不要编造病名。"
)


def _image_data_url(image_path) -> str:
    """读图 -> 缩到长边 1024 -> JPEG -> base64 data URL。

    必须缩图：原图动辄几 MB，base64 后还要再涨三分之一，既慢又容易撞上游的请求体积上限；
    而判断叶部病害根本不需要原始分辨率。
    """
    import base64
    import io

    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _extract_json(text: str) -> dict[str, Any] | None:
    """从模型回复里抠出 JSON 对象。

    模型经常把 JSON 包在 ```json 里、或前后带一句客套话，所以先整体试，
    失败再退化到"取第一个 { 到最后一个 }"。仍失败就返回 None，由调用方兜底。
    """
    import json as _json
    import re as _re

    text = (text or "").strip()
    # 部分视觉模型会在答案外面包一层控制标记（实测 GLM-4.1V-Thinking-Flash 会输出
    # <|begin_of_box|>…<|end_of_box|>），不去掉的话 JSON 永远解不出来。
    # 换模型时这行是必要的兜底，成本只有一次正则。
    text = _re.sub(r"<\|[^|]*\|>", "", text).strip()
    if not text:
        return None
    stripped = text
    for fence in ("```json", "```"):
        if stripped.startswith(fence):
            stripped = stripped[len(fence):]
    stripped = stripped.removesuffix("```").strip()

    for candidate in (text, stripped):
        try:
            data = _json.loads(candidate)
            if isinstance(data, dict):
                return data
        except _json.JSONDecodeError:
            continue

    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            data = _json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data
        except _json.JSONDecodeError:
            return None
    return None


def vision_analyze_sync(image_path, lang: str = "zh-CN") -> dict[str, Any] | None:
    """同步调用智谱视觉模型做图片理解。

    这里刻意用同步 httpx：它由 `vision.analyze()` 在 FastAPI 的 threadpool 里调用，
    于是 CPU 推理和这段网络等待都不会占住事件循环。

    返回 None 表示"不可用 / 调用失败"——调用方继续走下一级兜底，从不抛异常。
    """
    if not settings.vision_llm_enabled:
        return None
    cred = settings.provider_credentials("zhipu")
    if not cred["api_key"]:
        return None

    try:
        data_url = _image_data_url(image_path)
    except Exception as exc:
        logger.warning("图片读取失败，跳过图片理解：{}", exc)
        return None

    payload = {
        "model": settings.zhipu_vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {cred['api_key']}", "Content-Type": "application/json"}
    url = cred["base_url"].rstrip("/") + "/chat/completions"

    started = time.perf_counter()
    content = ""
    try:
        for attempt in (0, 1, 2):
            # trust_env=False 是必须的：本机 HTTPS_PROXY 指向随会话变化的本地端口，
            # 经它转发智谱时实测约一半请求会失败；直连稳定。
            with httpx.Client(timeout=settings.ai_timeout_seconds * 2, trust_env=False) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code in _RETRYABLE and attempt < 2:
                # 图片理解现在是识别链的主力，被上游限流（1305）时干等不如多试两次：
                # 退避 2s / 5s 实测能吃掉相当一部分瞬时限流。
                logger.info("图片理解遇 {} 限流，第 {} 次重试", resp.status_code, attempt + 1)
                time.sleep(2 if attempt == 0 else 5)
                continue
            if resp.status_code >= 400:
                logger.warning("图片理解失败 status={} body={}", resp.status_code, resp.text[:200])
                return None
            content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
            break
    except Exception as exc:
        logger.warning("图片理解请求异常：{}", exc)
        return None

    parsed = _extract_json(content)
    if not parsed:
        logger.warning("图片理解返回的不是 JSON：{}", (content or "")[:200])
        return None
    parsed["latency_ms"] = _ms(started)
    parsed["model"] = settings.zhipu_vision_model
    return parsed


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


async def ask_stream(question: str, lang: str = "zh-CN", context: str | None = None):
    """流式问答：逐块吐出增量文本，最后吐一条 meta（来源 / 模型 / 耗时 / 完整答案）。

    为什么要流式：一体机前站着的是老人，等 9 秒不出字和 0.5 秒开始出字，
    体感完全是两回事 —— 而且首字延迟远小于整段生成时间。

    降级行为与非流式完全一致：网络不通、429 限流、超时、返回空内容，
    一律退回本地知识库，只是把整段一次性吐出去，前端不会卡在空白气泡上。
    """
    started = time.perf_counter()
    provider = settings.active_provider

    if provider == "none":
        answer = local_answer(question, lang)
        yield {"type": "delta", "text": answer}
        yield {
            "type": "meta", "source": "local", "provider": "none",
            "provider_label": PROVIDER_LABELS["none"], "model": "local-knowledge",
            "tokens": 0, "latency_ms": _ms(started), "answer": answer,
        }
        return

    ctx = build_context(question, lang) if context is None else context
    messages = build_messages(question, lang, ctx)
    cred = settings.provider_credentials(provider)

    # 文心是另一套协议，不按 OpenAI 的 SSE 增量返回，整段取回来再吐一次即可
    if provider == "baidu":
        result = await ask(question, lang, ctx)
        yield {"type": "delta", "text": result.answer}
        yield {
            "type": "meta", "source": result.source, "provider": provider,
            "provider_label": PROVIDER_LABELS.get(provider, provider),
            "model": result.model, "tokens": result.tokens,
            "latency_ms": _ms(started), "answer": result.answer,
        }
        return

    payload = {
        "model": cred["model"],
        "messages": messages,
        "temperature": settings.ai_temperature,
        "max_tokens": settings.ai_max_tokens,
        "stream": True,
    }
    # 与非流式同样的处理：GLM-4.5/4.6 关掉思考，实测 14.8s -> 8.8s 且质量不降
    if cred["model"].startswith(("glm-4.5", "glm-4.6")):
        payload["thinking"] = {"type": "disabled"}

    headers = {"Authorization": f"Bearer {cred['api_key']}", "Content-Type": "application/json"}
    url = cred["base_url"].rstrip("/") + "/chat/completions"

    def _fallback(source: str, reason: str):
        logger.warning("流式调用 {} 失败（{}），降级本地知识库：{}", provider, reason, question[:30])
        text = local_answer(question, lang)
        return [
            {"type": "delta", "text": text},
            {
                "type": "meta", "source": source, "provider": provider,
                "provider_label": PROVIDER_LABELS.get(provider, provider),
                "model": cred["model"], "tokens": 0,
                "latency_ms": _ms(started), "answer": text,
            },
        ]

    pieces: list[str] = []
    # 限流重试：只在"还没吐出任何正文"时重试，避免把已经发给前端的半截答案再来一遍。
    # 429 是在建立连接阶段就能看到的，所以这个前提通常成立。
    for attempt in (0, 1):
        pieces.clear()
        try:
            # read 超时用 ai_timeout_seconds：首字之前模型在排队，之后是持续的小块输出，
            # 两者都不该按"整段必须在 N 秒内完成"来卡。
            timeout = httpx.Timeout(settings.ai_timeout_seconds, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code in _RETRYABLE:
                        body = (await resp.aread())[:200]
                        if attempt == 0:
                            logger.info("上游 {} 限流，1.5 秒后重试一次", resp.status_code)
                            await asyncio.sleep(1.5)
                            continue
                        raise RuntimeError(f"上游 {resp.status_code}: {body!r}")
                    if resp.status_code >= 400:
                        body = (await resp.aread())[:200]
                        raise RuntimeError(f"上游 {resp.status_code}: {body!r}")
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                        piece = delta.get("content") or ""
                        if piece:
                            pieces.append(piece)
                            yield {"type": "delta", "text": piece}
            break
        except Exception as exc:
            for evt in _fallback("fallback", f"{type(exc).__name__}"):
                yield evt
            return

    answer = "".join(pieces).strip()
    if not answer:
        # 上游 200 却一个字没回（偶发），同样兜到本地知识库，别给用户留一个空气泡
        for evt in _fallback("fallback", "empty"):
            yield evt
        return

    yield {
        "type": "meta", "source": "llm", "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "model": cred["model"], "tokens": 0,
        "latency_ms": _ms(started), "answer": answer,
    }


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
