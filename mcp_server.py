"""MCP Server —— 把知识库语义检索能力封装成 Agent 可调用的工具。

用 FastMCP（官方 mcp Python SDK），stdio 传输，可被 Claude Desktop / Cursor 等客户端直接调用。

工具：
  search_knowledge_base(query, kb_id?, top_k?)  语义检索，返回相关内容+来源
  list_knowledge_bases()                         列出所有知识库
  add_text_to_kb(kb_id, title, content)          向知识库追加文本

错误处理：query 为空 / 知识库不存在 / 检索失败 / 调用超时 —— 均返回 Agent 可读的清晰错误文本，
不抛裸异常（保证 stdio 进程不被打断）。
"""
import asyncio

from mcp.server.fastmcp import FastMCP

from app import config, db, retriever

mcp = FastMCP("kb-agent")

_TIMEOUT = config.REQUEST_TIMEOUT + 15  # 检索整体超时上限


@mcp.tool()
async def search_knowledge_base(query: str, kb_id: int | None = None, top_k: int = 3) -> str:
    """在知识库中按语义检索最相关的内容片段。

    Args:
        query: 自然语言查询，不能为空。例如「春天」「小孩子」「AI 编程怎么入门」。
        kb_id: 指定知识库 ID；不传则在所有知识库中检索。
        top_k: 返回结果数量，1-20，默认 3。

    Returns:
        命中的内容片段，每条带来源文档标题与相关度分数；无结果或出错时返回说明文本。
    """
    # 1) 参数校验
    if not query or not query.strip():
        return "❌ 错误：query 不能为空，请提供检索内容。"
    if not (1 <= top_k <= 20):
        return "❌ 错误：top_k 必须在 1-20 之间。"
    if kb_id is not None and not db.kb_exists(kb_id):
        return f"❌ 错误：知识库不存在（kb_id={kb_id}）。可先调用 list_knowledge_bases 查看可用知识库。"

    # 2) 带超时的检索
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(retriever.search, query, kb_id, top_k),
            timeout=_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return f"❌ 错误：检索超时（>{_TIMEOUT:.0f}s），请稍后重试或缩小检索范围。"
    except Exception as e:
        return f"❌ 错误：检索失败 — {type(e).__name__}: {e}"

    # 3) 无结果
    if not results:
        return f"知识库中未找到与「{query}」相关的内容。"

    # 4) 成功——带引用溯源
    parts = []
    for i, r in enumerate(results, 1):
        score = r.get("rerank_score", r.get("score"))
        parts.append(f"【{i}】来源：《{r['title']}》（相关度 {score:.3f}）\n{r['text']}")
    return "\n\n---\n\n".join(parts)


@mcp.tool()
async def list_knowledge_bases() -> str:
    """列出当前所有知识库及其文档数量。"""
    try:
        data = await asyncio.to_thread(db.list_kbs, 1, 100)
    except Exception as e:
        return f"❌ 错误：读取知识库列表失败 — {e}"
    if not data["items"]:
        return "当前没有任何知识库。"
    lines = [f"- id={kb['id']} 《{kb['name']}》（{kb['doc_count']} 篇文档）" for kb in data["items"]]
    return "可用知识库：\n" + "\n".join(lines)


@mcp.tool()
async def add_text_to_kb(kb_id: int, title: str, content: str) -> str:
    """向指定知识库追加一段文本知识。

    Args:
        kb_id: 目标知识库 ID。
        title: 文档标题。
        content: 文本内容，不能为空。
    """
    if not content or not content.strip():
        return "❌ 错误：content 不能为空。"
    if not db.kb_exists(kb_id):
        return f"❌ 错误：知识库不存在（kb_id={kb_id}）。"
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(retriever.index_document, kb_id, title or "未命名", content, "mcp"),
            timeout=_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return "❌ 错误：入库超时，请稍后重试。"
    except Exception as e:
        return f"❌ 错误：入库失败 — {type(e).__name__}: {e}"
    return f"✅ 已入库：《{title}》（doc_id={res['doc_id']}，{res['chunks']} 个分块）"


if __name__ == "__main__":
    db.init_db()
    mcp.run(transport="stdio")
