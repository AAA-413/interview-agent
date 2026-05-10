"""
RAG 评估数据集生成脚本

从用户已有知识库的 chunks 中采样，调用 LLM 生成测试问题。
生成的问题包含 ground truth chunk_id，用于后续评估检索准确率。

用法：
    python scripts/rag_eval_dataset_generator.py --user-id 1 --samples-per-kb 10 --output tests/rag_eval_dataset.json
"""

import argparse
import asyncio
import json
import logging
import random
import sys
from datetime import datetime
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.common.ai.llm_provider import llm_registry
from app.common.model import AsyncTaskStatus
import app.database as database_module
from app.database import close_db, init_db, init_engine
from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

QUESTION_GEN_PROMPT_PATH = Path(__file__).resolve().parent.parent / "app" / "prompts" / "eval-question-gen-system.md"


def sample_chunks(chunks: list, n: int) -> list:
    """从 chunks 中均匀采样 n 个，过滤太短的。"""
    eligible = [c for c in chunks if len(c.content or "") > 200]
    if not eligible:
        return []
    if len(eligible) <= n:
        return eligible

    # 按 chunk_index 均匀分布采样
    step = len(eligible) / n
    indices = [int(i * step) for i in range(n)]
    return [eligible[i] for i in indices]


async def generate_question(chunk_content: str, system_prompt: str) -> dict | None:
    """调用 LLM 为一个 chunk 生成测试问题。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    user_prompt = f"请根据以下知识片段生成一个测试问题：\n\n{chunk_content[:1500]}"
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = await llm_registry.default.ainvoke(messages)
        content = (response.content or "").strip()

        # 清理 markdown 代码块
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            content = content[start:end + 1]

        data = json.loads(content)
        if isinstance(data, dict) and "question" in data:
            return data
    except Exception as e:
        logger.warning("LLM 生成问题失败: %s", e)
    return None


async def main():
    parser = argparse.ArgumentParser(description="RAG 评估数据集生成")
    parser.add_argument("--user-id", type=int, required=True, help="用户 ID")
    parser.add_argument("--samples-per-kb", type=int, default=10, help="每个知识库采样 chunk 数")
    parser.add_argument("--output", type=str, default="tests/rag_eval_dataset.json", help="输出文件路径")
    args = parser.parse_args()

    # 初始化数据库
    init_engine()
    await init_db()

    # 读取 prompt
    system_prompt = QUESTION_GEN_PROMPT_PATH.read_text(encoding="utf-8")

    async with database_module.async_session_factory() as db:
        # 查询用户所有已完成的知识库
        stmt = (
            select(KnowledgeBaseEntity)
            .where(KnowledgeBaseEntity.user_id == args.user_id)
            .where(KnowledgeBaseEntity.index_status == AsyncTaskStatus.COMPLETED)
        )
        result = await db.execute(stmt)
        kbs = list(result.scalars().all())

        if not kbs:
            logger.error("未找到用户 %d 的已完成知识库", args.user_id)
            return

        logger.info("找到 %d 个已完成知识库", len(kbs))

        questions = []
        q_id = 0

        for kb in kbs:
            # 查询该 KB 的所有 chunks
            chunk_stmt = (
                select(KnowledgeChunkEntity)
                .where(KnowledgeChunkEntity.knowledge_base_id == kb.id)
                .order_by(KnowledgeChunkEntity.chunk_index)
            )
            chunk_result = await db.execute(chunk_stmt)
            chunks = list(chunk_result.scalars().all())

            if not chunks:
                logger.warning("知识库 '%s' (id=%d) 没有 chunks，跳过", kb.name, kb.id)
                continue

            sampled = sample_chunks(chunks, args.samples_per_kb)
            logger.info("知识库 '%s' (id=%d): %d chunks, 采样 %d 个", kb.name, kb.id, len(chunks), len(sampled))

            for chunk in sampled:
                q_id += 1
                logger.info("  生成问题 %d/%d (chunk_id=%d)...", q_id, len(kbs) * args.samples_per_kb, chunk.id)

                result = await generate_question(chunk.content or "", system_prompt)
                if result is None:
                    logger.warning("    跳过 chunk_id=%d（生成失败）", chunk.id)
                    q_id -= 1
                    continue

                questions.append({
                    "id": f"q_{q_id:03d}",
                    "question": result["question"],
                    "question_type": result.get("question_type", "factual"),
                    "key_terms": result.get("key_terms", []),
                    "difficulty": result.get("difficulty", "medium"),
                    "ground_truth": {
                        "chunk_id": chunk.id,
                        "kb_id": kb.id,
                        "kb_name": kb.name,
                        "chunk_title": chunk.title or "",
                        "chunk_content_preview": (chunk.content or "")[:300],
                    },
                })

    # 保存
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dataset = {
        "generated_at": datetime.now().isoformat(),
        "user_id": args.user_id,
        "total_questions": len(questions),
        "kb_count": len(kbs),
        "samples_per_kb": args.samples_per_kb,
        "questions": questions,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    logger.info("数据集已保存到 %s，共 %d 个问题", output_path, len(questions))

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
