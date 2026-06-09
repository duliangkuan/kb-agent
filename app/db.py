"""SQLite 数据层：连接管理 + 建表 + 知识库/文档/分块的 CRUD。

三张表：
  knowledge_bases  知识库（集合）
  documents        知识内容（一篇文章 / 一个文档）
  chunks           分块及其 embedding（语义检索的最小单位）
"""
import os
import sqlite3
from datetime import datetime

from . import config


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS documents (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            kb_id       INTEGER NOT NULL,
            title       TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'text',
            char_count  INTEGER NOT NULL DEFAULT 0,
            content     TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id      INTEGER NOT NULL,
            kb_id       INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            text        TEXT NOT NULL,
            embedding   TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_kb ON chunks(kb_id);
        CREATE INDEX IF NOT EXISTS idx_docs_kb   ON documents(kb_id);
        """
    )
    # 迁移：为老库补 content 列（存原文，供「查看文件内容」用）
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(documents)").fetchall()]
    if "content" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN content TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()


# ---------------- 知识库 CRUD ----------------

def create_kb(name: str, description: str = "") -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO knowledge_bases (name, description, created_at) VALUES (?,?,?)",
            (name, description, now()),
        )
        conn.commit()
        return get_kb(cur.lastrowid)
    except sqlite3.IntegrityError:
        raise ValueError(f"知识库名称已存在：{name}")
    finally:
        conn.close()


def get_kb(kb_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM knowledge_bases WHERE id=?", (kb_id,)).fetchone()
    if not row:
        conn.close()
        return None
    doc_count = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE kb_id=?", (kb_id,)
    ).fetchone()["c"]
    conn.close()
    d = dict(row)
    d["doc_count"] = doc_count
    return d


def kb_exists(kb_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM knowledge_bases WHERE id=?", (kb_id,)).fetchone()
    conn.close()
    return row is not None


def list_kbs(page: int = 1, page_size: int = 10) -> dict:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) c FROM knowledge_bases").fetchone()["c"]
    rows = conn.execute(
        """SELECT k.*, (SELECT COUNT(*) FROM documents d WHERE d.kb_id=k.id) AS doc_count
           FROM knowledge_bases k ORDER BY k.id DESC LIMIT ? OFFSET ?""",
        (page_size, offset),
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [dict(r) for r in rows],
    }


def update_kb(kb_id: int, name: str = None, description: str = None):
    if not kb_exists(kb_id):
        return None
    conn = get_conn()
    if name is not None:
        conn.execute("UPDATE knowledge_bases SET name=? WHERE id=?", (name, kb_id))
    if description is not None:
        conn.execute("UPDATE knowledge_bases SET description=? WHERE id=?", (description, kb_id))
    conn.commit()
    conn.close()
    return get_kb(kb_id)


def delete_kb(kb_id: int) -> bool:
    if not kb_exists(kb_id):
        return False
    conn = get_conn()
    conn.execute("DELETE FROM knowledge_bases WHERE id=?", (kb_id,))
    conn.commit()
    conn.close()
    return True


# ---------------- 文档 ----------------

def list_documents(kb_id: int, page: int = 1, page_size: int = 10) -> dict:
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE kb_id=?", (kb_id,)
    ).fetchone()["c"]
    rows = conn.execute(
        """SELECT d.id, d.kb_id, d.title, d.source_type, d.char_count, d.created_at,
                  (SELECT COUNT(*) FROM chunks c WHERE c.doc_id=d.id) AS chunk_count
           FROM documents d WHERE d.kb_id=? ORDER BY d.id DESC LIMIT ? OFFSET ?""",
        (kb_id, page_size, offset),
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [dict(r) for r in rows],
    }


def get_document(doc_id: int):
    """返回单篇文档的元信息 + 完整原文（供「查看文件内容」）。找不到返回 None。"""
    conn = get_conn()
    doc = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not doc:
        conn.close()
        return None
    rows = conn.execute(
        "SELECT text FROM chunks WHERE doc_id=? ORDER BY chunk_index", (doc_id,)
    ).fetchall()
    conn.close()
    d = dict(doc)
    content = d.get("content") or ""
    if not content and rows:
        # 老文档无原文列：用分块重建，去掉块间重叠前缀
        ov = config.CHUNK_OVERLAP
        texts = [r["text"] for r in rows]
        content = texts[0] + "".join((t[ov:] if ov > 0 else t) for t in texts[1:])
    d["content"] = content
    d["chunk_count"] = len(rows)
    return d


def delete_document(doc_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    conn.commit()
    conn.close()
    return True
