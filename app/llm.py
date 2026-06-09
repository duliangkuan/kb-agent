"""调用硅基流动上的 DeepSeek-V3 做 RAG 答案生成（流式）。"""
from openai import OpenAI

from . import config

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        config.require_siliconflow()
        _client = OpenAI(api_key=config.SILICONFLOW_API_KEY, base_url=config.SILICONFLOW_BASE_URL)
    return _client


def build_messages(query: str, contexts: list[dict]) -> list[dict]:
    blocks = []
    for i, c in enumerate(contexts, 1):
        blocks.append(f"[资料{i}] 来源：《{c['title']}》\n{c['text']}")
    context_text = "\n\n".join(blocks)
    system = (
        "你是一个严谨的知识库问答助手。请严格依据下面提供的『参考资料』回答用户问题，"
        "用简体中文回答，简洁、准确。"
        "若参考资料中确实没有相关信息，直接回答「知识库中未找到相关内容」，绝不编造。\n\n"
        f"参考资料：\n{context_text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": query},
    ]


def stream_answer(query: str, contexts: list[dict]):
    """生成器：逐 token 产出答案文本。"""
    stream = _get_client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=build_messages(query, contexts),
        stream=True,
        temperature=0.3,
        max_tokens=2048,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
