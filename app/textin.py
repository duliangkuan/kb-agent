"""TextIn 通用文档解析：把 PDF / 图片 / 扫描件 / 带复杂表格的文档解析成 Markdown。

底层是版面分析 + 表格识别 + OCR（多模态文档识别能力）。这是「上传知识内容」的
加分路径——题目最低只要求 txt/文本，这里支持任意复杂文档。
"""
import requests

from . import config


def configured() -> bool:
    return bool(config.TEXTIN_APP_ID and config.TEXTIN_SECRET_CODE)


def parse_document(file_bytes: bytes, filename: str = "") -> str:
    """返回解析出的 Markdown 文本。失败抛 RuntimeError。"""
    if not configured():
        raise RuntimeError("未配置 TextIn 凭证（TEXTIN_APP_ID / TEXTIN_SECRET_CODE）")
    if not file_bytes:
        raise RuntimeError("文件内容为空")

    resp = requests.post(
        config.TEXTIN_API_URL,
        headers={
            "x-ti-app-id": config.TEXTIN_APP_ID,
            "x-ti-secret-code": config.TEXTIN_SECRET_CODE,
            "Content-Type": "application/octet-stream",
        },
        params={"markdown_details": 1, "get_image": "none", "page_count": 50},
        data=file_bytes,
        timeout=120,
    )
    resp.raise_for_status()
    j = resp.json()
    if j.get("code") not in (200, 0):
        raise RuntimeError(f"TextIn 解析失败：code={j.get('code')} msg={j.get('message')}")
    result = j.get("result", {}) or {}
    md = result.get("markdown") or result.get("detail") or ""
    if isinstance(md, list):  # 兼容 detail 为分块列表的情况
        md = "\n".join(str(x.get("text", "")) for x in md)
    if not md.strip():
        raise RuntimeError("TextIn 未解析出任何文本内容")
    return md
