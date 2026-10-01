"""农事问答：接入大模型（失败自动降级本地知识库），并留下可追溯的记录。

两条出口：
- `POST /api/chat/ask`    非流式，一次返回完整 JSON（后台与第三方按这个消费）
- `POST /api/chat/stream` 流式 SSE，逐字吐给一体机大屏用
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import knowledge, llm
from app.core.auth import OptionalUser, is_guest
from app.db.database import get_db
from app.db.models import ChatRecord
from app.schemas import ChatIn, ChatOut, QuickAsk

router = APIRouter(prefix="/api/chat", tags=["chat"])

DbSession = Annotated[AsyncSession, Depends(get_db)]

# 常见问题快捷提问：6 种语言文案与前端 i18n 的 chat.q1~q4 保持一致
_QUICK_KEYS = ["q1", "q2", "q3", "q4"]
_QUICK_ASKS: dict[str, list[str]] = {
    "zh-CN": [
        "番茄叶片发黄是怎么回事？",
        "玉米什么时间追肥最好？",
        "棉花蚜虫怎么防治？",
        "小麦越冬前需要浇冻水吗？",
    ],
    "en-US": [
        "Why are my tomato leaves turning yellow?",
        "When is the best time to top-dress corn?",
        "How do I control cotton aphids?",
        "Do wheat fields need winter irrigation?",
    ],
    "ug-CN": [
        "پەمىدۇر ياپرىقى نېمە ئۈچۈن سارغىيىدۇ؟",
        "قوناققا قاچان ئوغۇت بېرىش ياخشى؟",
        "پاختا بىتىنى قانداق يوقىتىش كېرەك؟",
        "بۇغداي قىشتىن ئىلگىرى سۇغىرىش كېرەكمۇ؟",
    ],
    "kk-CN": [
        "قىزاناق جاپىراعى نەگە سارعايادى؟",
        "جۇگەرىگە قاشان تىڭايتقىش بەرگەن دۇرىس؟",
        "ماقتا سيرەكەسىن قالاي جويۋ كەرەك؟",
        "بيەداي قىس الدىندا سۥعارۋ كەرەك پە؟",
    ],
    "bo-CN": [
        "རྒྱ་ཤིང་གི་ལོ་མ་སེར་པོ་ཆགས་པའི་རྒྱུ་མཚན་གང་ཡིན།",
        "མ་ཧེ་ལ་ལུད་རྫས་ནམ་སྤྲོད་ན་ལེགས།",
        "སྤུག་ལ་བུ་རིགས་ཇི་ལྟར་བཀག་དགོས།",
        "གྲོ་ལ་དགུན་གྱི་སྔོན་ལ་ཆུ་སྤྲོད་དགོས་སམ།",
    ],
    "mn-CN": [
        "ᠤᠯᠠᠭᠠᠨ ᠨᠣᠭᠣᠭᠠᠨ ᠤ ᠨᠠᠪᠴᠢ ᠶᠠᠭᠠᠭᠠᠳᠤ ᠰᠢᠷᠠ ᠪᠣᠯᠤᠭᠰᠠᠨ ᠪᠣᠢ?",
        "ᠡᠷᠳᠡᠨᠢ ᠲᠠᠷᠢᠶᠠᠨ ᠳᠤ ᠬᠡᠳᠦᠢ ᠴᠠᠭ ᠲᠤ ᠲᠡᠵᠢᠭᠡᠯ ᠥᠭᠭᠦᠬᠦ ᠨᠢ ᠳᠡᠭᠡᠳᠦ?",
        "ᠬᠥᠪᠦᠩ ᠨᠣᠣᠰᠤᠨ ᠤ ᠪᠥᠭᠡᠰᠦᠨ ᠢ ᠶᠠᠭᠠᠬᠢᠵᠤ ᠳᠠᠷᠤᠬᠤ ᠨᠢ ᠳᠡᠭᠡᠳᠦ?",
        "ᠪᠤᠭᠤᠳᠠᠢ ᠡᠪᠦᠯ ᠤᠨ ᠡᠮᠨᠡ ᠤᠰᠤᠯᠠᠬᠤ ᠬᠡᠷᠡᠭᠲᠡᠢ ᠤᠤ?",
    ],
}


@router.post("/ask", response_model=ChatOut)
async def ask(payload: ChatIn, db: DbSession, user: OptionalUser) -> ChatOut:
    result = await llm.ask(payload.question, payload.lang)
    data = result.as_dict()

    # intent 记下命中的知识库条目，后台看"用户到底在问什么"
    hits = knowledge.search_classes(payload.question, payload.lang, 1)
    intent = hits[0]["key"] if hits else ""

    # 游客 / 匿名不落库：公共区域的不可追溯身份，记录留下来没有归属人，
    # 只会把后台的"用户到底在问什么"统计带偏。仍然照常回答，只是不留痕。
    if is_guest(user):
        return ChatOut(
            answer=data["answer"],
            source=data["source"],
            provider=data["provider"],
            provider_label=data["provider_label"],
            model=data["model"],
            tokens=data["tokens"],
            latency_ms=data["latency_ms"],
            record_id=None,
        )

    record = ChatRecord(
        user_id=user.id if user else None,
        question=payload.question,
        answer=data["answer"],
        answer_source=data["source"],
        intent=intent,
        provider=data["provider"],
        model=data["model"],
        tokens=data["tokens"],
        latency_ms=data["latency_ms"],
        lang=payload.lang,
    )
    db.add(record)
    await db.flush()

    return ChatOut(
        answer=data["answer"],
        source=data["source"],
        provider=data["provider"],
        provider_label=data["provider_label"],
        model=data["model"],
        tokens=data["tokens"],
        latency_ms=data["latency_ms"],
        record_id=record.id,
    )


def _sse(obj: dict) -> str:
    """把一条事件编成 SSE 帧。ensure_ascii=False 是为了维/哈/藏/蒙文原样传输。"""
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@router.post("/stream")
async def stream(payload: ChatIn, db: DbSession, user: OptionalUser) -> StreamingResponse:
    """流式问答（SSE）。

    单独开一条接口而不是给 /ask 加参数：/ask 还在被后台与第三方按 JSON 消费，
    改它的响应类型会直接破坏那些调用方。
    """

    async def event_gen():
        # 先把响应头和一帧注释推出去：让浏览器与 Vite 代理马上确认"这是流式响应"。
        # 智谱免费档的首字延迟实测在 0.4~15 秒之间剧烈波动，中间层在长时间
        # 收不到任何字节时会把连接判死，前端表现就是"一个字都没等到"。
        yield ": open\n\n"

        queue: asyncio.Queue = asyncio.Queue()

        async def pump() -> None:
            try:
                async for evt in llm.ask_stream(payload.question, payload.lang):
                    await queue.put(evt)
            except Exception as exc:  # ask_stream 内部已兜底，这里只防未预期异常
                logger.warning("流式生成出现未预期异常：{}", exc)
            finally:
                await queue.put(None)

        task = asyncio.create_task(pump())
        meta: dict = {}
        answer = ""

        while True:
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                # 10 秒没有新内容就发一次心跳注释帧，把连接吊住
                yield ": keep-alive\n\n"
                continue
            if evt is None:
                break
            if evt["type"] == "delta":
                yield _sse({"type": "delta", "text": evt["text"]})
            else:
                meta = evt
                answer = evt.get("answer", "")

        await task

        # 落库放在流结束后：答案这时候才是完整的。
        # 游客 / 匿名不落库，理由与非流式一致（公共区域的不可追溯身份）。
        record_id = None
        if not is_guest(user):
            hits = knowledge.search_classes(payload.question, payload.lang, 1)
            record = ChatRecord(
                user_id=user.id if user else None,
                question=payload.question,
                answer=answer,
                answer_source=meta.get("source", ""),
                intent=hits[0]["key"] if hits else "",
                provider=meta.get("provider", ""),
                model=meta.get("model", ""),
                tokens=meta.get("tokens", 0),
                latency_ms=meta.get("latency_ms", 0),
                lang=payload.lang,
            )
            db.add(record)
            await db.flush()
            record_id = record.id

        yield _sse({
            "type": "meta",
            "source": meta.get("source"),
            "provider": meta.get("provider"),
            "provider_label": meta.get("provider_label"),
            "model": meta.get("model"),
            "latency_ms": meta.get("latency_ms"),
            "record_id": record_id,
        })
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # 让 nginx 之类的反向代理不要缓冲，否则流式会被攒成一坨再发，白改了
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/quicks", response_model=list[QuickAsk])
async def quicks(lang: str = Query("zh-CN")) -> list[QuickAsk]:
    texts = _QUICK_ASKS.get(lang) or _QUICK_ASKS["zh-CN"]
    return [QuickAsk(key=k, text=t) for k, t in zip(_QUICK_KEYS, texts)]
