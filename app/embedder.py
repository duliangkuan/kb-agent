"""调用硅基流动的 bge-m3 embedding（OpenAI 兼容 /embeddings 接口）。

- passage（入库文档）与 query（检索词）都用同一模型；bge-m3 无需指令前缀。
- 批量入库时分批请求，避免单次过大。
"""
import requests

from . import config

_BATCH = 16


def _post(texts: list[str]) -> list[list[float]]:
    config.require_siliconflow()
    resp = requests.post(
        f"{config.SILICONFLOW_BASE_URL}/embeddings",
        headers={
            "Authorization": f"Bearer {config.SILICONFLOW_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": config.EMBEDDING_MODEL, "input": texts, "encoding_format": "float"},
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    data.sort(key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed_passages(texts) -> list[list[float]]:
    if isinstance(texts, str):
        texts = [texts]
    out: list[list[float]] = []
    for i in range(0, len(texts), _BATCH):
        out.extend(_post(texts[i : i + _BATCH]))
    return out


def embed_query(text: str) -> list[float]:
    q = (config.QUERY_PREFIX + text) if config.QUERY_PREFIX else text
    return _post([q])[0]
