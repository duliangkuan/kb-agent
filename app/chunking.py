"""中文友好的文本分块。

策略：优先按自然段落切；段落过长再按句子切；相邻 chunk 之间保留重叠窗口，
避免「少年闰土」这类语义被切断在两个 chunk 边界而检索不到。
"""
import re


def chunk_text(text: str, max_chars: int = 400, overlap_chars: int = 80) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    raw_chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            raw_chunks.append(para)
            continue
        # 段落太长：按中文句末标点切句后再贪心打包
        sentences = re.split(r"(?<=[。！？!?；;\n])", para)
        cur = ""
        for sent in sentences:
            if not sent:
                continue
            if len(cur) + len(sent) <= max_chars:
                cur += sent
            else:
                if cur:
                    raw_chunks.append(cur)
                # 单句就超长，硬切
                while len(sent) > max_chars:
                    raw_chunks.append(sent[:max_chars])
                    sent = sent[max_chars:]
                cur = sent
        if cur:
            raw_chunks.append(cur)

    # 加重叠：把上一块结尾的 overlap_chars 字符拼到当前块开头
    if overlap_chars <= 0 or len(raw_chunks) <= 1:
        return raw_chunks
    result = [raw_chunks[0]]
    for i in range(1, len(raw_chunks)):
        tail = raw_chunks[i - 1][-overlap_chars:]
        result.append(tail + raw_chunks[i])
    return result
