"""农事问答：接入大模型（失败自动降级本地知识库），并留下可追溯的记录。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
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


@router.get("/quicks", response_model=list[QuickAsk])
async def quicks(lang: str = Query("zh-CN")) -> list[QuickAsk]:
    texts = _QUICK_ASKS.get(lang) or _QUICK_ASKS["zh-CN"]
    return [QuickAsk(key=k, text=t) for k, t in zip(_QUICK_KEYS, texts)]
