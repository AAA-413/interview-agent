"""
选择性重跑图谱相关策略

复用已有的 vector_only / vector_rerank 结果，只重跑图谱相关策略。
用于图谱数据更新后重新评估，避免重复跑纯向量策略。

用法：
    python scripts/rag_eval_rerun_graph.py --dataset tests/rag_eval_dataset.json --results tests/rag_eval_results.json --user-id 1
"""

import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.database as database_module
from app.database import close_db, init_db, init_engine
from app.modules.knowledge_base.cross_kb_rag_service import cross_kb_rag_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ── 需要重跑的策略 ────────────────────────────────────────────────────────────

GRAPH_STRATEGIES = [
    {
        "name": "graph_only",
        "use_vector": False,
        "use_graph": True,
        "use_rerank": False,
        "top_k": 4,
        "graph_weight": 0.5,
    },
    {
        "name": "hybrid_no_rerank",
        "use_vector": True,
        "use_graph": True,
        "use_rerank": False,
        "top_k": 4,
        "graph_weight": 0.5,
    },
    {
        "name": "hybrid_rerank",
        "use_vector": True,
        "use_graph": True,
        "use_rerank": True,
        "top_k": 4,
        "graph_weight": 0.5,
    },
]

TOP_K_VARIANTS = [2, 4, 6, 8, 10]
GRAPH_WEIGHT_VARIANTS = [0.3, 0.5, 0.7]


# ── 指标计算（与 rag_eval_runner.py 相同）────────────────────────────────────


def compute_metrics(retrieved_ids: list[int], ground_truth_id: int, k: int) -> dict:
    top_k_ids = retrieved_ids[:k]
    hit = ground_truth_id in top_k_ids
    recall = 1.0 if hit else 0.0
    precision = 1.0 / k if hit else 0.0
    mrr = 0.0
    for i, rid in enumerate(retrieved_ids):
        if rid == ground_truth_id:
            mrr = 1.0 / (i + 1)
            break
    hit_at_1 = 1.0 if (len(retrieved_ids) >= 1 and retrieved_ids[0] == ground_truth_id) else 0.0
    hit_at_3 = 1.0 if ground_truth_id in retrieved_ids[:3] else 0.0
    hit_at_5 = 1.0 if ground_truth_id in retrieved_ids[:5] else 0.0
    return {
        "recall": recall,
        "mrr": mrr,
        "precision": precision,
        "hit@1": hit_at_1,
        "hit@3": hit_at_3,
        "hit@5": hit_at_5,
    }


def aggregate_metrics(results: list[dict]) -> dict:
    if not results:
        return {}
    n = len(results)
    keys = ["recall", "mrr", "precision", "hit@1", "hit@3", "hit@5"]
    agg = {}
    for key in keys:
        agg[key] = round(sum(r[key] for r in results) / n, 4)
    agg["avg_latency_ms"] = round(sum(r["latency_ms"] for r in results) / n, 1)
    agg["count"] = n
    return agg


# ── 评估逻辑 ─────────────────────────────────────────────────────────────────

MAX_CONCURRENCY = 1  # SQLAlchemy async session 不支持并发，只能串行


async def evaluate_strategy(db, questions, user_id, strategy, scope):
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def eval_one(q):
        gt = q["ground_truth"]
        scope_kb_id = gt["kb_id"] if scope == "single_kb" else None
        async with sem:
            try:
                references, latency_ms = await cross_kb_rag_service.retrieve_with_config(
                    db,
                    user_id=user_id,
                    question=q["question"],
                    top_k=strategy["top_k"],
                    use_vector=strategy["use_vector"],
                    use_graph=strategy["use_graph"],
                    use_rerank=strategy["use_rerank"],
                    graph_weight=strategy["graph_weight"],
                    scope_kb_id=scope_kb_id,
                )
                retrieved_ids = [r.chunk_id for r in references]
            except Exception as e:
                logger.warning("策略 %s 评估问题 '%s' 失败: %s", strategy["name"], q["question"][:30], e)
                retrieved_ids = []
                latency_ms = 0
        metrics = compute_metrics(retrieved_ids, gt["chunk_id"], strategy["top_k"])
        metrics["latency_ms"] = latency_ms
        return q.get("question_type", "factual"), metrics

    tasks = [eval_one(q) for q in questions]
    pairs = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    per_type = defaultdict(list)
    for pair in pairs:
        if isinstance(pair, Exception):
            logger.warning("评估任务异常: %s", pair)
            continue
        qtype, metrics = pair
        results.append(metrics)
        per_type[qtype].append(metrics)

    aggregated = aggregate_metrics(results)
    per_type_agg = {qtype: aggregate_metrics(trs) for qtype, trs in per_type.items()}
    return {"config": {**strategy, "scope": scope}, "metrics": aggregated, "per_type": per_type_agg}


async def pre_warm_entity_cache(questions):
    """预热实体提取缓存：对所有问题提取一次实体，后续策略复用"""
    logger.info("预热实体提取缓存: %d 个问题...", len(questions))
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def extract_one(q):
        async with sem:
            await cross_kb_rag_service._extract_entities(q["question"])

    await asyncio.gather(*[extract_one(q) for q in questions])
    logger.info("实体缓存预热完成: %d 个条目", len(cross_kb_rag_service._entity_cache))


async def main():
    parser = argparse.ArgumentParser(description="选择性重跑图谱相关策略")
    parser.add_argument("--dataset", type=str, required=True, help="测试数据集路径")
    parser.add_argument("--results", type=str, required=True, help="已有评估结果路径（会被原地更新）")
    parser.add_argument("--user-id", type=int, required=True, help="用户 ID")
    args = parser.parse_args()

    with open(args.dataset, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    with open(args.results, "r", encoding="utf-8") as f:
        results_data = json.load(f)

    questions = dataset["questions"]
    logger.info("加载数据集: %d 个问题", len(questions))

    init_engine()
    await init_db()

    async with database_module.async_session_factory() as db:
        # 预热实体提取缓存（同一问题在不同策略/场景下实体相同）
        await pre_warm_entity_cache(questions)
        for scope in ["single_kb", "cross_kb"]:
            logger.info("=== 评估场景: %s ===", scope)
            strategies = results_data["scopes"][scope]["strategies"]

            # 保留 vector_only 和 vector_rerank
            for keep in ["vector_only", "vector_rerank"]:
                if keep in strategies:
                    logger.info("  复用: %s (recall=%.3f)", keep, strategies[keep]["metrics"]["recall"])

            # 重跑基础图谱策略
            for strategy in GRAPH_STRATEGIES:
                logger.info("  重跑: %s", strategy["name"])
                result = await evaluate_strategy(db, questions, args.user_id, strategy, scope)
                strategies[strategy["name"]] = result
                logger.info(
                    "    Recall@%d=%.3f, MRR=%.3f",
                    strategy["top_k"],
                    result["metrics"]["recall"],
                    result["metrics"]["mrr"],
                )

            # 重跑 top_k 变量
            for k in TOP_K_VARIANTS:
                name = f"hybrid_rerank_top{k}"
                strategy = {
                    "name": name,
                    "use_vector": True,
                    "use_graph": True,
                    "use_rerank": True,
                    "top_k": k,
                    "graph_weight": 0.5,
                }
                logger.info("  重跑: %s", name)
                result = await evaluate_strategy(db, questions, args.user_id, strategy, scope)
                strategies[name] = result
                logger.info("    Recall@%d=%.3f, MRR=%.3f", k, result["metrics"]["recall"], result["metrics"]["mrr"])

            # 重跑 graph_weight 变量
            for w in GRAPH_WEIGHT_VARIANTS:
                name = f"hybrid_rerank_weight{w}"
                strategy = {
                    "name": name,
                    "use_vector": True,
                    "use_graph": True,
                    "use_rerank": True,
                    "top_k": 4,
                    "graph_weight": w,
                }
                logger.info("  重跑: %s", name)
                result = await evaluate_strategy(db, questions, args.user_id, strategy, scope)
                strategies[name] = result
                logger.info("    Recall@4=%.3f, MRR=%.3f", result["metrics"]["recall"], result["metrics"]["mrr"])

    # 更新元数据
    results_data["evaluated_at"] = datetime.now().isoformat()

    output_path = Path(args.results)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)

    logger.info("评估结果已更新到 %s", output_path)

    # 打印对比摘要
    print("\n=== 图谱策略效果对比（旧 vs 新）===")
    for scope in ["single_kb", "cross_kb"]:
        print(f"\n--- {scope} ---")
        s = results_data["scopes"][scope]["strategies"]
        for name in ["graph_only", "hybrid_no_rerank", "hybrid_rerank"]:
            old = {
                "graph_only": 0.0,
                "hybrid_no_rerank": 0.797 if scope == "single_kb" else 0.649,
                "hybrid_rerank": 0.797 if scope == "single_kb" else 0.635,
            }
            new_recall = s[name]["metrics"]["recall"]
            print(f"  {name}: {old[name]:.3f} → {new_recall:.3f}")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
