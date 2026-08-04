"""
dataset01 评测共享设施：路径常量、配置引导、数据集加载/聚合/抽样、指标计算。

本模块同时是脚本所在包：以独立脚本方式运行（uv run python test/dataset01/eval/xxx.py），
因此需在导入项目模块前把项目根注入 sys.path。各阶段脚本按需调用：
- build_corpus / build_gold：不依赖 CFG（仅 ENV + PG/Qdrant），不强制加载配置快照；
- run_queries / report：依赖 CFG（候选池/最终 top-k/模型角色），入口先 ensure_cfg()。
"""

import hashlib
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

# ---- 路径常量 ---------------------------------------------------------------
DATASET_ROOT = Path(__file__).resolve().parents[1]  # test/dataset01
DATA_DIR = DATASET_ROOT / "data"
EVAL_DIR = DATASET_ROOT / "eval"
GOLD_DIR = DATASET_ROOT / "gold"
RESULTS_DIR = DATASET_ROOT / "results"
CSV_PATH = DATA_DIR / "agriculture_wiki_qa_full.csv"
CORPUS_STATS_PATH = GOLD_DIR / "corpus_stats.json"
GOLD_STRICT_PATH = GOLD_DIR / "gold_strict.json"
GOLD_RELAXED_PATH = GOLD_DIR / "gold_relaxed.json"
SAMPLE_QUERIES_PATH = GOLD_DIR / "sample_queries.json"
EVAL_RESULTS_PATH = RESULTS_DIR / "eval_results.json"
REPORT_PATH = RESULTS_DIR / "report.md"

# 评测知识库标识（PG 行与 Qdrant 集合均由此派生，删除时按名字定位）
KB_NAME = "dataset01-agriculture"
KB_DESCRIPTION = "RAG 检索评测语料库：农业维基 QA 110K（按维基页面聚合）"

# 抽样与评测默认参数
DEFAULT_SEED = 42
DEFAULT_SAMPLE_SIZE = 1000
# 指标 K 集合：固定档位 + 系统最终 top-k（run_queries/report 按 CFG 扩充）
BASE_K_VALUES = (1, 3, 5, 10)

PROJECT_ROOT = DATASET_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 数据集字段（与 agriculture_wiki_qa_full.csv 表头一致）
CSV_COLUMNS = ["pageid", "title", "question", "thinking", "answer", "content", "url"]


def ensure_dirs() -> None:
    """确保生成物目录存在（幂等）。"""
    for directory in (DATA_DIR, GOLD_DIR, RESULTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def ensure_csv() -> Path:
    """校验数据文件存在，缺失时给出下载指引并退出。"""
    if not CSV_PATH.exists():
        raise SystemExit(
            f"缺少数据文件: {CSV_PATH}\n"
            "请先下载（约 566MB，见 test/dataset01/README.md）：\n"
            f'  curl -L -o {CSV_PATH} \\\n'
            '    "https://modelscope.cn/api/v1/datasets/chal1ce/Agricultrue_Wiki_QA_110K'
            '/repo?Revision=master&FilePath=agriculture_wiki_qa_full.csv"'
        )
    return CSV_PATH


def sha256_of_file(path) -> str:
    """流式计算文件 sha256（大文件不整体读入内存；str/Path 均可）。"""
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# ---- 配置引导 ---------------------------------------------------------------
_CFG_LOADED = False


def ensure_cfg() -> None:
    """同步上下文引导：加载配置快照（幂等，重复调用直接返回）。

    依赖 sys.sys_model_config 四行与 sys.sys_config 标量参数（fail-fast）；
    失败会抛出 ValueError，提示先初始化数据库种子数据。
    注意：只能在无事件循环的同步上下文调用（内部用 asyncio.run）；
    async 上下文请用 ensure_cfg_async()。
    """
    global _CFG_LOADED
    if _CFG_LOADED:
        return
    from core.config_snapshot import CFG

    CFG.load_blocking()
    _CFG_LOADED = True


async def ensure_cfg_async() -> None:
    """异步上下文引导：await CFG.load()（幂等；供 async main 的脚本使用）。"""
    global _CFG_LOADED
    if _CFG_LOADED:
        return
    from core.config_snapshot import CFG

    await CFG.load()
    _CFG_LOADED = True


def final_top_k() -> int:
    """当前系统配置的 RAG 最终 top-k（报告指标 K 集合的一部分）。"""
    ensure_cfg()
    from core.config_snapshot import CFG

    return CFG.rag_final_top_k


# ---- 文本规范化 ---------------------------------------------------------------
def normalize(text: str | None) -> str:
    """折叠空白（含全角空格/换行/制表）并去首尾，用于 gold 包含判定。"""
    if not text:
        return ""
    return " ".join(str(text).replace("\u3000", " ").split())


# ---- 数据集加载与聚合 ---------------------------------------------------------------
def load_dataset(limit: int | None = None) -> "Any":
    """pandas 读取 CSV（全列 str 保持原文，NaN 补空串；limit 取前 N 条记录）。"""
    import pandas as pd

    df = pd.read_csv(
        ensure_csv(),
        dtype=str,
        na_filter=False,
        usecols=CSV_COLUMNS,
        low_memory=False,
        nrows=limit,
    )
    return df


def aggregate_by_page(df: "Any") -> list[dict]:
    """把原始记录按 pageid 聚合为页面文档列表（保持页面首次出现顺序）。

    每页产出：
    - text：该页全部 content 按原序以换行连接（聚合文档正文）
    - qa_pairs：该页原始记录 [{row_index, question, content, url}]
      row_index 为 CSV 行号（0-based，抽样与 gold 表以此对齐）
    """
    pages: dict[str, dict] = {}
    order: list[str] = []
    for row_index, row in enumerate(df.itertuples(index=False)):
        pageid = str(row.pageid)
        page = pages.get(pageid)
        if page is None:
            page = {
                "pageid": pageid,
                "title": str(row.title or ""),
                "url": str(row.url or ""),
                "contents": [],
                "qa_pairs": [],
            }
            pages[pageid] = page
            order.append(pageid)
        content = str(row.content or "")
        if content:
            page["contents"].append(content)
        page["qa_pairs"].append(
            {
                "row_index": row_index,
                "question": str(row.question or ""),
                "content": content,
            }
        )
    result = []
    for pageid in order:
        page = pages[pageid]
        page["text"] = "\n".join(page["contents"])
        result.append(page)
    return result


# ---- 分层抽样 ---------------------------------------------------------------
def stratified_sample(df: "Any", seed: int = DEFAULT_SEED, size: int = DEFAULT_SAMPLE_SIZE) -> list[dict]:
    """按 pageid 分层（页内打乱后轮转）抽样 size 条 question，保证页面均衡。

    页面数 >= size 时每页至多 1 条；页面数 < size 时轮转多轮。返回抽样清单
    （含 row_index/title/question/content），可落盘复现。
    """
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = {}
    for row in df.itertuples():
        pageid = str(row.pageid)
        buckets.setdefault(pageid, []).append(
            {
                "row_index": row.Index,
                "pageid": pageid,
                "title": str(row.title or ""),
                "question": str(row.question or ""),
                "content": str(row.content or ""),
            }
        )
    for items in buckets.values():
        rng.shuffle(items)

    sampled: list[dict] = []
    cursor = 0
    while len(sampled) < size and cursor < max(len(v) for v in buckets.values()):
        for items in buckets.values():
            if len(sampled) >= size:
                break
            if cursor < len(items):
                sampled.append(items[cursor])
        cursor += 1
    return sampled


def load_json(path) -> dict:
    """读取 JSON 产物；缺失时给出阶段指引并退出（str/Path 均可）。"""
    import json

    path = Path(path)
    if not path.exists():
        raise SystemExit(f"缺少产物文件: {path}（请按 README 顺序先运行前置阶段脚本）")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, data: Any) -> None:
    """落盘 JSON（ensure_ascii=False 保留中文，便于人工检查；str/Path 均可）。"""
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


# ---- 指标计算 ---------------------------------------------------------------
def _dedupe_ranked(ranked: list[dict], mode: str) -> list[dict]:
    """文档级口径按 document_id 去重（保留首次出现顺序）。

    chunk 级 point_id 天然唯一无需去重；doc 级若不去重，同一文档的多个叶块
    会重复计入命中，导致 Recall 可超 1。
    """
    if mode != "doc":
        return ranked
    seen: set = set()
    out: list[dict] = []
    for cand in ranked:
        did = cand.get("document_id")
        if did is None or did in seen:
            continue
        seen.add(did)
        out.append(cand)
    return out


def hit_positions(
    ranked: Iterable[dict], gold: Iterable[str], mode: str = "chunk"
) -> list[int]:
    """返回候选列表中被 gold 命中的 1-based 位置列表。

    - mode='chunk'：候选 point_id ∈ gold（chunk 级）
    - mode='doc'：候选 document_id ∈ gold（文档级，宽松口径；先按文档去重）
    ranked 元素须含 point_id/document_id；gold 为 id 字符串集合。
    """
    gold_set = set(gold)
    ranked = _dedupe_ranked(list(ranked), mode)
    positions: list[int] = []
    for rank, cand in enumerate(ranked, start=1):
        hit_id = cand.get("point_id") if mode == "chunk" else cand.get("document_id")
        if hit_id is not None and str(hit_id) in gold_set:
            positions.append(rank)
    return positions


def compute_metrics(
    ranked: list[dict],
    gold: Iterable[str],
    ks: Iterable[int],
    mode: str = "chunk",
) -> dict | None:
    """单条 query 的 Recall@K / Precision@K / MRR；gold 为空返回 None。

    返回 {k: {"recall": r, "precision": p}, "mrr": m, "first_hit_rank": rank|None}；
    Precision 分母恒为 K（候选不足 K 时按实际命中数 / K）。
    """
    gold_list = [g for g in gold if g]
    if not gold_list:
        return None
    gold_set = set(gold_list)
    ranked = _dedupe_ranked(ranked, mode)
    positions = hit_positions(ranked, gold_set, mode)
    first = positions[0] if positions else None
    out: dict = {"mrr": (1.0 / first) if first else 0.0, "first_hit_rank": first}
    for k in ks:
        topk = ranked[:k]
        hits = sum(
            1
            for cand in topk
            if (cand.get("point_id") if mode == "chunk" else cand.get("document_id"))
            in gold_set
        )
        out[int(k)] = {
            "recall": hits / len(gold_set),
            "precision": hits / int(k) if int(k) > 0 else 0.0,
        }
    return out


def mean_std(values: Iterable[float | None]) -> tuple[float, float] | None:
    """宏平均 mean ± std；空序列或全 None 返回 None。"""
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    if len(clean) == 1:
        return (clean[0], 0.0)
    return (statistics.fmean(clean), statistics.stdev(clean))
