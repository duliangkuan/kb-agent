"""请求/响应数据模型（Pydantic v2）。"""
from pydantic import BaseModel, Field


class KBCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""


class KBUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None


class TextDocIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)


class SearchIn(BaseModel):
    query: str = Field(..., min_length=1)
    kb_id: int | None = None
    top_k: int = Field(default=3, ge=1, le=20)
