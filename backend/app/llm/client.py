"""LLM 调用封装（LangChain ChatOpenAI，OpenAI 兼容协议）。

三件事：
1. 结构化输出：从回复里抽 JSON，再用 pydantic 校验。字段缺失、枚举越界都判失败，不带病入库。
2. 失败重试一次，仍失败抛 LLMError，由调用方降级（批改降级到规则引擎，并在界面标注）。
3. 提示注入防护：考生答案是不可信输入，一律包在 <answer> 标签里，system 提示明确它不是指令。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any, Literal, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from app.core.config import settings

T = TypeVar("T", bound=BaseModel)
Tier = Literal["medium", "large", "vision"]


class LLMError(Exception):
    pass


@lru_cache(maxsize=16)
def _chat(model: str, max_tokens: int = 8192, temperature: float = 0.0):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "not-set",
        temperature=temperature,
        timeout=settings.llm_timeout,
        max_tokens=max_tokens,
        max_retries=1,
    )


def chat_model(tier: "Tier" = "medium", max_tokens: int = 8192, temperature: float = 0.0):
    """给智能体（工具调用）用的聊天模型实例。"""
    return _chat(model_for(tier), max_tokens, temperature)


def model_for(tier: Tier) -> str:
    return {"medium": settings.llm_model_medium, "large": settings.llm_model_large,
            "vision": settings.llm_model_vision}[tier]


# 中文字符之间的英文双引号（如 说"系统上线了"就），是正文里的引语，不是 JSON 字符串边界。
# 合法 JSON 里字符串的边界引号两侧总有一侧是 : , [ { } ] 或空白，所以只替换两侧都是中文的引号。
_CJK = r"[一-鿿　-〿＀-￯]"
_INNER_QUOTE = re.compile(rf"(?<={_CJK})\"(?={_CJK})")


def _loads(t: str) -> Any:
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return json.loads(_INNER_QUOTE.sub("”", t))


def extract_json(text: str) -> Any:
    """模型常把 JSON 包在说明文字或代码块里，这里容错抽取。"""
    if not text:
        raise LLMError("空响应")
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return _loads(t)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = t.find(opener), t.rfind(closer)
        if 0 <= i < j:
            try:
                return _loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("响应中没有合法 JSON")


async def complete_text(*, system: str, user: str, tier: Tier = "medium",
                        max_tokens: int = 4000, temperature: float = 0.0) -> str:
    """纯文本输出，给长篇中文（出题的材料正文）用。失败重试一次。"""
    if not settings.llm_enabled:
        raise LLMError("未配置模型网关")
    llm = _chat(model_for(tier), max_tokens, temperature)
    last = ""
    for _ in range(2):
        try:
            resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
            text = resp.content if isinstance(resp.content, str) else "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in resp.content)
            if text.strip():
                return text
            last = "空响应"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:200]}"
    raise LLMError(last)


async def complete_json(
    *,
    system: str,
    user: str,
    schema: type[T],
    tier: Tier = "medium",
    images: list[str] | None = None,
    max_tokens: int = 8192,
    temperature: float = 0.0,
) -> tuple[T, str]:
    """返回 (校验后的对象, 实际使用的模型名)。images 是 data URL 列表。"""
    if not settings.llm_enabled:
        raise LLMError("未配置模型网关")
    model = model_for(tier)
    llm = _chat(model, max_tokens, temperature)
    content: list[dict[str, Any]] | str = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": u}} for u in images]
    messages = [SystemMessage(content=system), HumanMessage(content=content)]

    last = ""
    for _ in range(3):
        try:
            resp = await llm.ainvoke(messages)
            if (resp.response_metadata or {}).get("finish_reason") == "length":
                raise LLMError(f"输出超过 max_tokens={max_tokens} 被截断")
            data = extract_json(str(resp.content))
            return schema.model_validate(data), model
        except (LLMError, ValidationError) as e:
            last = f"{type(e).__name__}: {str(e)[:200]}"
            # 第二次把错误告诉模型，让它按格式重答
            messages = messages[:2] + [HumanMessage(
                content=f"上次输出不符合要求（{last}）。只输出符合要求的 JSON，不要任何解释。"
                        "字符串里的引号一律用中文引号「」，不要用英文双引号。")]
        except Exception as e:  # noqa: BLE001 — 网络、鉴权、限流
            last = f"{type(e).__name__}: {str(e)[:200]}"
            break
    raise LLMError(last)


async def ping() -> tuple[bool, str]:
    """连通性测试，给设置页用。"""
    if not settings.llm_enabled:
        return False, "未配置 LLM_BASE_URL 与 LLM_API_KEY"
    try:
        resp = await _chat(settings.llm_model_medium).ainvoke([HumanMessage(content="回复 ok")])
        return True, f"{settings.llm_model_medium} 可用：{str(resp.content)[:20]}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:200]}"
