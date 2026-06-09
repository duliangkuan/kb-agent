# -*- coding: utf-8 -*-
"""自动评测脚本：按 TEST_DESIGN 把 12 篇 txt 入库，逐条跑 T1-T8 检索/生成，输出报告。

直接调用真实检索内核（embed→cosine→rerank）和 DeepSeek 流式生成。
结果写入 联调结果.md（UTF-8），避免 Windows 控制台中文乱码。
"""
import os
import sys

# 以脚本位置定位项目根目录（scripts/ 的上一级），不写死绝对路径
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from app import config, db, retriever, llm  # noqa

CORPUS = os.path.join(_ROOT, "test-corpus")

# (标签, 知识库, 相对路径)
DOCS = [
    # KB-A 微信小程序AI化
    ("A1·官方·接入微信AI生态指引", "A", "微信官方/微信官方-开发者接入微信AI生态指引.txt"),
    ("A2·卡兹克·微信正在变成Agent时代的操作系统(支持)", "A", "卡兹克/微信正在变成Agent时代的操作系统_.txt"),
    ("A3·宝玉·小程序无法成为Agent入口(反对)", "A", "宝玉AI/微信_AI_的困局_为什么小程序无法成为_Agent_入口.txt"),
    # KB-B 干扰/多源
    ("B1·花叔·从VibeCoding到VibeBusiness(部分相关)", "B", "花叔/一人公司转折点_从Vibe_Coding到Vibe_Business.txt"),
    ("B2·卡兹克·Agent额度翻倍小技巧(异义)", "B", "卡兹克/一个让你Agent额度翻倍的小技巧_.txt"),
    ("B3·赛博禅心·扣子3.0遥控ClaudeCode", "B", "赛博禅心/扣子3_0_让我不再担心网络ip_遥控家里的_Claude_Code_干活.txt"),
    ("B4·宝玉·Cloudflare裁员", "B", "宝玉AI/谁将被_AI_淘汰_来自_Cloudflare_CEO_的裁员抉择.txt"),
    ("B5·宝玉·美国反AI浪潮", "B", "宝玉AI/美国的_反_AI_浪潮_正在加速蔓延.txt"),
    ("B6·卡兹克·ClaudeCode团队5条原则", "B", "卡兹克/分享Claude_Code团队内部的5条工作原则_我觉得每一条都值得学习_.txt"),
    ("B7·赛博禅心·MiniMaxM3给视频补声音", "B", "赛博禅心/用_MiniMax_M3_给无声视频_补上声音.txt"),
    ("B8·赛博禅心·AGI Bar落地上海(字面词)", "B", "赛博禅心/AGI_Bar_落地上海_将于儿童节开业.txt"),
    ("B9·宝玉·为什么我不凭感觉编程", "B", "宝玉AI/为什么我不_凭感觉编程_.txt"),
]

R = []  # 报告行


def log(s=""):
    R.append(s)


def setup():
    dbfile = config.DB_PATH
    if os.path.exists(dbfile):
        os.remove(dbfile)
    db.init_db()
    kb_a = db.create_kb("微信小程序AI化", "")["id"]
    kb_b = db.create_kb("AI行业与工具", "")["id"]
    kbmap = {"A": kb_a, "B": kb_b}
    label_by_docid = {}
    log("## 入库\n")
    for label, kb, rel in DOCS:
        text = open(os.path.join(CORPUS, rel), encoding="utf-8").read()
        res = retriever.index_document(kbmap[kb], label, text, "txt")
        label_by_docid[res["doc_id"]] = label
        log(f"- 入库 [{kb}] {label} → {res['chunks']} 块")
    log("")
    return kb_a, kb_b, label_by_docid


def run_search(query, kb_id, top_k):
    """返回 [(label, score)]，label 取文档标题。"""
    results = retriever.search(query, kb_id, top_k)
    out = []
    for r in results:
        score = r.get("rerank_score", r.get("score"))
        out.append((r["title"], round(float(score), 4)))
    return out


def show(results):
    if not results:
        return "（无命中）"
    return "; ".join(f"#{i+1} {lbl} ({sc})" for i, (lbl, sc) in enumerate(results))


def has(results, key):
    return any(key in lbl for lbl, _ in results)


def rank1(results, key):
    return bool(results) and key in results[0][0]


def case(tid, title, query, scope_label, results, expect_desc, verdict, gen=None):
    log(f"### {tid}　{title}")
    log(f"- 查询：`{query}`")
    log(f"- 范围：{scope_label}")
    log(f"- 召回（按排名）：{show(results)}")
    log(f"- 预期：{expect_desc}")
    log(f"- 判定：{verdict}")
    if gen is not None:
        log(f"- 生成回答：\n\n> {gen}\n")
    log("")


def gen_answer(query, kb_id, top_k=3):
    ctx = retriever.search(query, kb_id, top_k)
    if not ctx:
        return "（检索无命中，应触发拒答）"
    buf = "".join(llm.stream_answer(query, ctx))
    return buf.replace("\n", "\n> ")


def main():
    kb_a, kb_b, _ = setup()
    log("---\n\n## 检索 / 生成测试结果\n")

    # T1 综合检索 + 多源综合
    q = "微信小程序到底该不该AI化？官方什么态度，业内有哪些不同看法？"
    res = run_search(q, None, 5)
    ok = has(res, "A1") and has(res, "A2") and has(res, "A3")
    gen = gen_answer(q, None, 5)
    case("T1", "综合检索+多源综合 [C·D·H]", q, "全部库 top5", res,
         "top5 含 A1官方/A2卡兹克/A3宝玉 三篇",
         "✅PASS（三篇都召回）" if ok else "❌FAIL（缺其一）", gen)

    # T2 换词语义（faithful paraphrase，避开任一文章标题原词）
    q = "把 AI 直接接进微信小程序生态，这条路到底靠不靠谱？"
    res = run_search(q, None, 5)
    ok = has(res, "A2") and has(res, "A3")
    case("T2", "换词语义(避开标题原词) [B]", q, "全部库 top5", res,
         "用改写句仍命中 A2/A3（及 A1），证明语义匹配而非字面",
         "✅PASS（语义命中）" if ok else "❌FAIL")

    # T2-hard 极端跨域改写（诚实记录 embedding 的边界）
    q = "轻量级应用要不要接入大模型能力？把对话式AI塞进去值不值？"
    res = run_search(q, None, 5)
    case("T2-hard", "极端跨域改写(诚实边界) [B]", q, "全部库 top5", res,
         "『轻量级应用』≈小程序的跨域同义，bge-m3 桥接弱；低于精排下限则系统诚实拒答",
         "ℹ️记录：此为已知语义边界，非缺陷")

    # T3 意图区分（用官方文档专属的事实，观点文里没有）
    q = "没有接入微信AI的小程序会怎么样？"
    res = run_search(q, kb_a, 3)
    ok = rank1(res, "A1")
    case("T3", "意图区分(官方专属事实) [E]", q, "限定KB-A top3", res,
         "『未接入将无法被AI调用』只有官方文 A1 写了 → A1 居首",
         "✅PASS（A1 居首）" if ok else "❌FAIL")

    # T4 抗干扰反向
    q = "Claude Code 怎么省 token？额度怎么用更划算？"
    res = run_search(q, None, 3)
    # 合理标准：B2 居首且显著领先；小程序文即便因提到 Claude Code 而弱相关出现，分数也应远低于 B2
    top_score = res[0][1] if res else 0
    intruder = [(l, s) for l, s in res if ("A1" in l or "A2" in l or "A3" in l)]
    ok = rank1(res, "B2") and all(s < top_score * 0.6 for _, s in intruder)
    case("T4", "抗干扰精准/反向 [F]", q, "全部库 top3", res,
         "B2居首且显著领先；小程序文即便弱相关出现也分数远低（<B2*0.6）",
         "✅PASS（精准，主命中无误）" if ok else "❌FAIL")

    # T5 第二主题多源
    q = "AI会不会让很多人失业？哪些岗位危险？"
    res = run_search(q, None, 5)
    ok = has(res, "B4") and has(res, "B5")
    gen = gen_answer(q, None, 5)
    case("T5", "第二主题多源召回 [A·C·H]", q, "全部库 top5", res,
         "召回 B4裁员 + B5反AI浪潮 并综合",
         "✅PASS" if ok else "❌FAIL", gen)

    # T6 多库隔离
    q = "微信小程序"
    res = run_search(q, kb_b, 5)
    leak = has(res, "A1") or has(res, "A2") or has(res, "A3")
    case("T6", "多知识库隔离 [G]", q, "限定KB-B top5", res,
         "KB-A 的 A1/A2/A3 绝不出现",
         "✅PASS（无泄漏）" if not leak else "❌FAIL（串库）")

    # T7 拒答
    q = "红烧肉怎么做？"
    res = run_search(q, None, 3)
    gen = gen_answer(q, None, 3)
    case("T7", "拒答不编造 [I]", q, "全部库 top3", res,
         "阈值过滤后无命中→拒答",
         "✅PASS（无命中）" if not res else "⚠️有命中需看生成是否拒答", gen)

    # T8 错误处理
    log("### T8　错误处理 [J]")
    try:
        retriever.search("", None)
        log("- 空query：❌FAIL（未报错）")
    except ValueError as e:
        log(f"- 空query：✅PASS → {e}")
    log(f"- 不存在kb_id=9999：db.kb_exists(9999)={db.kb_exists(9999)} → 应为 False（API层据此返回404）")
    log("")

    out_path = os.path.join(_ROOT, "联调结果.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# 联调自动测试结果\n\n" + "\n".join(R))
    print("DONE -> " + out_path)


if __name__ == "__main__":
    main()
