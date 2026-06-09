"""FastAPI 应用：知识库 CRUD（分页）、知识内容上传、相关性检索、SSE 流式返回。

接口总览：
  知识库 CRUD
    POST   /api/kb                  新建知识库
    GET    /api/kb?page=&page_size= 列表（分页）
    GET    /api/kb/{id}             详情
    PUT    /api/kb/{id}             修改
    DELETE /api/kb/{id}             删除（级联删文档/分块）
  知识内容
    POST   /api/kb/{id}/documents/text    直接输入文本入库
    POST   /api/kb/{id}/documents/upload  上传文件入库（.txt 直读 / 其他走 TextIn 解析）
    GET    /api/kb/{id}/documents?page=   文档列表（分页）
    DELETE /api/documents/{doc_id}        删除文档
  检索
    POST   /api/search              相关性检索（一次性返回 JSON）
    GET    /api/search/stream?q=&kb_id=   RAG 流式返回（SSE，逐字蹦出）
"""
import json
import logging

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, llm, retriever, textin
from .schemas import KBCreate, KBUpdate, SearchIn, TextDocIn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("kb-agent")

app = FastAPI(title="知识库 Agent", description="语义检索知识库 + 流式返回 + MCP 工具", version="1.0")


@app.on_event("startup")
def _startup():
    db.init_db()
    logger.info("DB 初始化完成：%s", config.DB_PATH)


# ---------------- 知识库 CRUD ----------------

@app.post("/api/kb")
def create_kb(body: KBCreate):
    try:
        return db.create_kb(body.name.strip(), body.description)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/kb")
def list_kbs(page: int = 1, page_size: int = 10):
    return db.list_kbs(page, page_size)


@app.get("/api/kb/{kb_id}")
def get_kb(kb_id: int):
    kb = db.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库不存在：id={kb_id}")
    return kb


@app.put("/api/kb/{kb_id}")
def update_kb(kb_id: int, body: KBUpdate):
    kb = db.update_kb(kb_id, body.name, body.description)
    if not kb:
        raise HTTPException(status_code=404, detail=f"知识库不存在：id={kb_id}")
    return kb


@app.delete("/api/kb/{kb_id}")
def delete_kb(kb_id: int):
    if not db.delete_kb(kb_id):
        raise HTTPException(status_code=404, detail=f"知识库不存在：id={kb_id}")
    return {"deleted": True, "kb_id": kb_id}


# ---------------- 知识内容上传 ----------------

@app.post("/api/kb/{kb_id}/documents/text")
def add_text(kb_id: int, body: TextDocIn):
    if not db.kb_exists(kb_id):
        raise HTTPException(status_code=404, detail=f"知识库不存在：id={kb_id}")
    try:
        return retriever.index_document(kb_id, body.title.strip(), body.content, "text")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("入库失败")
        raise HTTPException(status_code=500, detail=f"入库失败：{e}")


@app.post("/api/kb/{kb_id}/documents/upload")
async def upload_doc(kb_id: int, file: UploadFile = File(...)):
    if not db.kb_exists(kb_id):
        raise HTTPException(status_code=404, detail=f"知识库不存在：id={kb_id}")
    raw = await file.read()
    name = file.filename or "uploaded"
    try:
        if name.lower().endswith((".txt", ".md")):
            text = raw.decode("utf-8", errors="ignore")
            source = "txt"
        else:
            # PDF / Word / 图片 / 扫描件等 → TextIn 多模态文档解析（版面分析+表格识别+OCR）
            text = textin.parse_document(raw, name)
            source = "textin"
        if not text.strip():
            raise HTTPException(status_code=400, detail="未能从文件中提取到文本")
        return retriever.index_document(kb_id, name, text, source)
    except HTTPException:
        raise
    except RuntimeError as e:  # TextIn 相关错误
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("上传入库失败")
        raise HTTPException(status_code=500, detail=f"上传入库失败：{e}")


@app.get("/api/kb/{kb_id}/documents")
def list_docs(kb_id: int, page: int = 1, page_size: int = 10):
    if not db.kb_exists(kb_id):
        raise HTTPException(status_code=404, detail=f"知识库不存在：id={kb_id}")
    return db.list_documents(kb_id, page, page_size)


@app.get("/api/documents/{doc_id}")
def get_doc(doc_id: int):
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档不存在：id={doc_id}")
    return {
        "id": doc["id"], "title": doc["title"], "source_type": doc["source_type"],
        "char_count": doc["char_count"], "chunk_count": doc["chunk_count"],
        "created_at": doc["created_at"], "content": doc["content"],
    }


@app.delete("/api/documents/{doc_id}")
def delete_doc(doc_id: int):
    if not db.delete_document(doc_id):
        raise HTTPException(status_code=404, detail=f"文档不存在：id={doc_id}")
    return {"deleted": True, "doc_id": doc_id}


# ---------------- 检索 ----------------

@app.post("/api/search")
def search(body: SearchIn):
    if body.kb_id is not None and not db.kb_exists(body.kb_id):
        raise HTTPException(status_code=404, detail=f"知识库不存在：id={body.kb_id}")
    try:
        results = retriever.search(body.query, body.kb_id, body.top_k)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("检索失败")
        raise HTTPException(status_code=500, detail=f"检索失败：{e}")
    return {"query": body.query, "count": len(results), "results": results}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/search/stream")
def search_stream(q: str = "", kb_id: int | None = None):
    """SSE 流式返回：先发 sources 事件（命中来源），再逐 token 发 answer。"""

    def gen():
        if not q or not q.strip():
            yield _sse("error", {"message": "query 不能为空"})
            return
        if kb_id is not None and not db.kb_exists(kb_id):
            yield _sse("error", {"message": f"知识库不存在：id={kb_id}"})
            return
        try:
            results = retriever.search(q, kb_id)
        except Exception as e:
            logger.exception("检索失败")
            yield _sse("error", {"message": f"检索失败：{e}"})
            return

        yield _sse(
            "sources",
            [
                {
                    "title": r["title"],
                    "score": r.get("rerank_score", r["score"]),
                    "doc_id": r["doc_id"],
                    "snippet": r["text"],  # 命中的原文片段，供前端展开显示
                }
                for r in results
            ],
        )
        if not results:
            for ch in "知识库中未找到与该问题相关的内容。":
                yield _sse("token", ch)
            yield _sse("done", "[DONE]")
            return
        try:
            for tok in llm.stream_answer(q, results):
                yield _sse("token", tok)
        except Exception as e:
            logger.exception("生成失败")
            yield _sse("error", {"message": f"生成失败：{e}"})
            return
        yield _sse("done", "[DONE]")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ---------------- 前端演示页 ----------------
import os

_STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.isdir(_STATIC):
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(_STATIC, "index.html"))
