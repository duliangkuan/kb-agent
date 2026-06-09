"""检索内核：入库（分块→embedding→存储）+ 两阶段语义检索（向量召回→reranker 精排）。

main.py（HTTP）和 mcp_server.py（MCP）共享这一份检索逻辑——单一数据源，单一真相。
"""
import json

import numpy as np
import requests

from . import config, db, embedder
from .chunking import chunk_text


def index_document(kb_id: int, title: str, text: str, source_type: str = "text") -> dict:
    """把一段文本切块、向量化并写入指定知识库。返回 {doc_id, chunks}。"""
    if not db.kb_exists(kb_id):
        raise ValueError(f"知识库不存在：id={kb_id}")
    chunks = chunk_text(text, config.CHUNK_MAX_CHARS, config.CHUNK_OVERLAP)
    if not chunks:
        raise ValueError("文档内容为空，无法入库")

    embeddings = embedder.embed_passages(chunks)

    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO documents (kb_id, title, source_type, char_count, content, created_at) VALUES (?,?,?,?,?,?)",
        (kb_id, title, source_type, len(text), text, db.now()),
    )
    doc_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO chunks (doc_id, kb_id, chunk_index, text, embedding) VALUES (?,?,?,?,?)",
        [(doc_id, kb_id, i, c, json.dumps(e)) for i, (c, e) in enumerate(zip(chunks, embeddings))],
    )
    conn.commit()
    conn.close()
    return {"doc_id": doc_id, "title": title, "chunks": len(chunks)}


def _cosine_scores(query_vec: list[float], matrix: np.ndarray) -> np.ndarray:
    q = np.asarray(query_vec, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-8)
    m = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8)
    return m @ q


def _rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """调用硅基流动 reranker 精排；失败则原样返回（降级，不让检索崩）。"""
    try:
        resp = requests.post(
            f"{config.SILICONFLOW_BASE_URL}/rerank",
            headers={"Authorization": f"Bearer {config.SILICONFLOW_API_KEY}"},
            json={
                "model": config.RERANKER_MODEL,
                "query": query,
                "documents": [c["text"] for c in candidates],
                "top_n": top_k,
            },
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        out = []
        for r in results:
            c = dict(candidates[r["index"]])
            c["rerank_score"] = float(r["relevance_score"])
            out.append(c)
        return out
    except Exception:
        return candidates[:top_k]


def search(query: str, kb_id: int | None = None, top_k: int | None = None) -> list[dict]:
    """两阶段语义检索。返回 [{text, title, doc_id, chunk_index, kb_name, score, rerank_score?}]。"""
    query = (query or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    top_k = top_k or config.TOP_K_RERANK

    query_vec = embedder.embed_query(query)

    conn = db.get_conn()
    sql = (
        "SELECT c.text, c.chunk_index, c.embedding, d.title, d.id AS doc_id, k.name AS kb_name "
        "FROM chunks c JOIN documents d ON c.doc_id=d.id JOIN knowledge_bases k ON c.kb_id=k.id"
    )
    params: tuple = ()
    if kb_id is not None:
        sql += " WHERE c.kb_id=?"
        params = (kb_id,)
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        return []

    matrix = np.asarray([json.loads(r["embedding"]) for r in rows], dtype=np.float32)
    scores = _cosine_scores(query_vec, matrix)

    order = np.argsort(-scores)[: config.TOP_K_RETRIEVE]
    candidates = []
    for i in order:
        i = int(i)
        if float(scores[i]) < config.SIM_THRESHOLD:
            continue
        candidates.append(
            {
                "text": rows[i]["text"],
                "title": rows[i]["title"],
                "doc_id": rows[i]["doc_id"],
                "chunk_index": rows[i]["chunk_index"],
                "kb_name": rows[i]["kb_name"],
                "score": round(float(scores[i]), 4),
            }
        )

    if not candidates:
        return []

    # 精排：对全部候选分块重排（不在此截断），以便随后按文档去重后仍有足够文章。
    if config.USE_RERANKER and len(candidates) > 1:
        ranked = _rerank(query, candidates, len(candidates))
        # 精排相关度下限：低于阈值视为不相关，既不展示也不作答（与拒答行为保持一致）。
        ranked = [c for c in ranked if c.get("rerank_score", 0.0) >= config.RERANK_MIN_SCORE]
    else:
        ranked = candidates

    # 按文档去重：同一篇文章可能有多个分块命中，只保留最相关的一块。
    # 这样 top_k 是「top_k 篇不同文章」，避免长文用多个分块霸占名额，
    # 也让「命中来源」呈现为彼此不同的文章。
    seen: set = set()
    deduped = []
    for c in ranked:
        if c["doc_id"] in seen:
            continue
        seen.add(c["doc_id"])
        deduped.append(c)
    return deduped[:top_k]
