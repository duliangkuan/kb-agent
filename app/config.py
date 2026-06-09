"""集中配置：所有可调参数从 .env 读取，带合理默认值。"""
import os
from dotenv import load_dotenv

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 按项目根目录的绝对路径加载 .env —— 保证被 MCP 宿主（Claude Code/Desktop）以任意 cwd 启动时也能读到密钥
load_dotenv(os.path.join(_BASE, ".env"))

# ---- 硅基流动 ----
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V3")
EMBEDDING_DIM = 1024  # bge-m3 固定输出 1024 维

# ---- TextIn 通用文档解析 ----
TEXTIN_APP_ID = os.getenv("TEXTIN_APP_ID", "")
TEXTIN_SECRET_CODE = os.getenv("TEXTIN_SECRET_CODE", "")
TEXTIN_API_URL = os.getenv("TEXTIN_API_URL", "https://api.textin.com/ai/service/v1/pdf_to_markdown")

# ---- 检索参数 ----
CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "400"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))
TOP_K_RETRIEVE = int(os.getenv("TOP_K_RETRIEVE", "10"))   # 向量召回数
TOP_K_RERANK = int(os.getenv("TOP_K_RERANK", "3"))         # 精排后喂给大模型的数量
SIM_THRESHOLD = float(os.getenv("SIM_THRESHOLD", "0.3"))   # 余弦相似度下限（召回阶段过滤无关内容）
RERANK_MIN_SCORE = float(os.getenv("RERANK_MIN_SCORE", "0.1"))  # 精排相关度下限：低于此视为不相关，不展示也不作答（支撑拒答的一致性）
USE_RERANKER = os.getenv("USE_RERANKER", "true").lower() == "true"
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))

# bge-m3 是 instruction-free 模型，查询不需要加指令前缀（与 bge-large-zh 不同）。
# 若改用 bge-large-zh-v1.5，请把下面设为 "为这个句子生成表示以用于检索相关文章："
QUERY_PREFIX = os.getenv("QUERY_PREFIX", "")

# ---- 存储 ----
DB_PATH = os.getenv("DB_PATH", os.path.join(_BASE, "data", "kb.db"))


def require_siliconflow():
    if not SILICONFLOW_API_KEY:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY，请在 .env 中填写硅基流动的 API key")
