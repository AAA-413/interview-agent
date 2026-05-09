"""
智能下载知识库路由 - 两阶段流程
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.modules.auth.dependencies import get_current_user_id
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.common.ai.llm_provider import llm_registry
from app.infrastructure.redis.redis_service import RedisService, get_redis
from app.modules.agent_orchestration.orchestrator import AgentOrchestrator
from app.modules.agent_orchestration.agents.planning_agent import PlanningAgent
from app.modules.knowledge_base.rag_service import KnowledgeBaseRagService
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service

logger = logging.getLogger(__name__)

REDIS_PLAN_PREFIX = "smart_download:plan:"
REDIS_TASK_PREFIX = "smart_download:task:"
STATE_TTL_SECONDS = 3600

router = APIRouter(prefix="/api/agent/smart-download")


# ============ 请求/响应模型 ============

class PlanDownloadRequest(BaseModel):
    """生成下载计划请求"""
    user_input: str = Field(..., description="用户需求描述", min_length=1, max_length=500)
    max_downloads: int = Field(10, description="最大下载数量", ge=1, le=20)
    kb_id: Optional[int] = Field(None, description="目标知识库ID（可选）")


class DownloadStep(BaseModel):
    """下载步骤"""
    step_id: int
    action: str  # fetch_url, search_web, fetch_blog
    params: Dict[str, Any]
    description: str
    source_type: str  # official, blog, github, arxiv, general


class DownloadPlan(BaseModel):
    """下载计划"""
    plan_id: str
    user_input: str
    intent: Dict[str, Any]
    steps: List[DownloadStep]
    estimated_time: str
    estimated_size: str
    total_steps: int


class ExecuteDownloadRequest(BaseModel):
    """执行下载请求"""
    plan_id: str = Field(..., description="计划ID")
    kb_id: Optional[int] = Field(None, description="目标知识库ID")
    kb_name: Optional[str] = Field(None, description="知识库名称（创建新库时）")
    kb_description: Optional[str] = Field(None, description="知识库描述")


class DownloadProgress(BaseModel):
    """下载进度"""
    task_id: str
    user_id: int = 0
    status: str  # planning, executing, quality_check, completed, failed, cancelled
    current_step: int
    total_steps: int
    progress_percent: int
    message: str
    retry_count: int
    downloaded_files: List[Dict[str, Any]]
    quality_score: Optional[float] = None
    quality_details: Optional[Dict[str, Any]] = None
    task_statuses: Dict[int, str] = {}  # step_id -> "success"/"retrying"/"failed"/"new"
    integrated_doc: Optional[Dict[str, Any]] = None
    kb_info: Optional[Dict[str, Any]] = None


# ============ Redis 状态管理 ============

def _plan_key(user_id: int, plan_id: str) -> str:
    return f"smart_download:{user_id}:plan:{plan_id}"

def _task_key(user_id: int, task_id: str) -> str:
    return f"smart_download:{user_id}:task:{task_id}"

async def _save_plan(user_id: int, plan_id: str, plan_data: dict) -> None:
    redis = await get_redis()
    svc = RedisService(redis)
    await svc.set(_plan_key(user_id, plan_id), json.dumps(plan_data, ensure_ascii=False), ex=STATE_TTL_SECONDS)

async def _get_plan(user_id: int, plan_id: str) -> dict | None:
    redis = await get_redis()
    svc = RedisService(redis)
    raw = await svc.get(_plan_key(user_id, plan_id))
    return json.loads(raw) if raw else None

async def _save_task_progress(user_id: int, task_id: str, progress: DownloadProgress) -> None:
    redis = await get_redis()
    svc = RedisService(redis)
    await svc.set(_task_key(user_id, task_id), json.dumps(progress.model_dump(), ensure_ascii=False, default=str), ex=STATE_TTL_SECONDS)

async def _get_task_progress(user_id: int, task_id: str) -> DownloadProgress | None:
    redis = await get_redis()
    svc = RedisService(redis)
    raw = await svc.get(_task_key(user_id, task_id))
    if not raw:
        return None
    return DownloadProgress(**json.loads(raw))


def _cancel_key(user_id: int, task_id: str) -> str:
    return f"smart_download:{user_id}:cancel:{task_id}"


async def _request_cancel(user_id: int, task_id: str) -> None:
    """标记任务为已请求取消（Redis flag，24h 过期）"""
    redis = await get_redis()
    svc = RedisService(redis)
    await svc.set(_cancel_key(user_id, task_id), "1", ex=86400)


async def _is_cancelled(user_id: int, task_id: str) -> bool:
    """检查任务是否已被请求取消"""
    redis = await get_redis()
    svc = RedisService(redis)
    return await svc.get(_cancel_key(user_id, task_id)) is not None


# ============ API 端点 ============

@router.post("/plan", response_model=DownloadPlan)
async def generate_download_plan(
    request: PlanDownloadRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    阶段1：生成下载计划

    使用 PlanningAgent 分析用户需求，生成详细的下载计划供用户确认
    """
    try:
        logger.info(f"[PLAN] Generate download plan: {request.user_input}")

        # 创建 PlanningAgent
        from app.common.ai.llm_adapter import LLMProviderAdapter
        chat_model = llm_registry.default
        llm_provider = LLMProviderAdapter(chat_model)
        planning_agent = PlanningAgent(
            llm_provider=llm_provider,
            knowledge_service=None,  # 计划阶段不需要知识库
        )

        # 生成下载计划
        plan_data = await planning_agent.plan_download(
            user_input=request.user_input,
            max_downloads=request.max_downloads,
            context={"kb_id": request.kb_id}
        )

        # 解析计划
        intent = plan_data.get("intent", {})
        tasks = plan_data.get("tasks", [])

        # 转换为下载步骤（限制数量）
        steps = []
        for i, task in enumerate(tasks[:request.max_downloads]):
            step = DownloadStep(
                step_id=i + 1,
                action=_map_task_to_action(task),
                params=_extract_task_params(task),
                description=task.get("description", ""),
                source_type=_detect_source_type(task),
            )
            steps.append(step)

        # 生成计划ID
        import uuid
        plan_id = str(uuid.uuid4())

        # 估算时间和大小
        estimated_time = f"{len(steps) * 30}秒"
        estimated_size = f"{len(steps) * 500}KB"

        # 保存计划
        plan = DownloadPlan(
            plan_id=plan_id,
            user_input=request.user_input,
            intent=intent,
            steps=steps,
            estimated_time=estimated_time,
            estimated_size=estimated_size,
            total_steps=len(steps),
        )

        await _save_plan(user_id, plan_id, plan.model_dump())

        logger.info(f"Plan generated successfully: {len(steps)} steps")
        return plan

    except Exception as e:
        logger.error(f"Failed to generate plan: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate plan: {str(e)}")


@router.post("/execute")
async def execute_download_plan(
    request: ExecuteDownloadRequest,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    阶段2：执行下载计划

    使用 AgentOrchestrator 执行完整的4步流程：
    Planning → Execution → Quality → Summary

    支持质量检查失败后重试（最多3times）
    """
    try:
        # 检查计划是否存在
        plan = await _get_plan(user_id, request.plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="计划不存在")

        # 创建任务ID
        import uuid
        task_id = str(uuid.uuid4())

        # 初始化进度
        progress = DownloadProgress(
            task_id=task_id,
            user_id=user_id,
            status="executing",
            current_step=0,
            total_steps=plan["total_steps"],
            progress_percent=0,
            message="开始执行下载...",
            retry_count=0,
            downloaded_files=[],
        )
        await _save_task_progress(user_id, task_id, progress)

        # 后台执行下载任务
        background_tasks.add_task(
            _execute_download_with_retry,
            task_id=task_id,
            plan=plan,
            kb_id=request.kb_id,
            kb_name=request.kb_name,
            kb_description=request.kb_description,
            user_id=user_id,
        )

        logger.info(f"[START] Start download task: {task_id}")

        return {
            "task_id": task_id,
            "message": "下载任务已启动",
            "plan_id": request.plan_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Failed to start download task: {e}")
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


@router.get("/progress/{task_id}", response_model=DownloadProgress)
async def get_download_progress(
    task_id: str,
    user_id: int = Depends(get_current_user_id),
):
    """
    查询下载进度

    前端可以轮询此接口获取实时进度
    """
    progress = await _get_task_progress(user_id, task_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    return progress


@router.post("/cancel/{task_id}")
async def cancel_download_task(
    task_id: str,
    user_id: int = Depends(get_current_user_id),
):
    """取消正在执行的下载任务"""
    progress = await _get_task_progress(user_id, task_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if progress.status in ("completed", "failed", "cancelled"):
        return {"message": f"任务已处于 {progress.status} 状态，无需取消"}

    await _request_cancel(user_id, task_id)

    progress.status = "cancelled"
    progress.message = "用户请求取消"
    await _save_task_progress(user_id, task_id, progress)

    return {"message": "取消请求已提交", "task_id": task_id}


# ============ 辅助函数 ============

def _map_task_to_action(task: Dict[str, Any]) -> str:
    """将任务类型映射到具体操作"""
    task_type = task.get("type", "").lower()

    if "search" in task_type:
        return "search_web"
    elif "fetch" in task_type or "download" in task_type:
        return "fetch_url"
    elif "blog" in task_type:
        return "fetch_blog"
    else:
        return "search_web"


def _extract_task_params(task: Dict[str, Any]) -> Dict[str, Any]:
    """提取任务参数"""
    params = {}

    # 提取URL
    if "url" in task:
        params["url"] = task["url"]

    # 提取搜索关键词
    if "query" in task or "keyword" in task:
        params["query"] = task.get("query") or task.get("keyword")

    # 提取数量限制
    if "num_results" in task:
        params["num_results"] = task["num_results"]
    else:
        params["num_results"] = 3

    return params


def _detect_source_type(task: Dict[str, Any]) -> str:
    """检测资源类型"""
    description = task.get("description", "").lower()

    if "官方" in description or "official" in description:
        return "official"
    elif any(blog in description for blog in ["csdn", "掘金", "知乎", "medium", "博客"]):
        return "blog"
    elif "github" in description:
        return "github"
    elif "arxiv" in description or "论文" in description:
        return "arxiv"
    else:
        return "general"


def _get_step_by_index(
    index: int,
    all_steps: List[Dict[str, Any]],
    expanded_steps: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """根据索引获取对应的步骤（支持原始步骤和扩展步骤）"""
    if index < len(all_steps):
        return all_steps[index]
    expanded_idx = index - len(all_steps)
    if expanded_idx < len(expanded_steps):
        return expanded_steps[expanded_idx]
    raise IndexError(f"Step index {index} out of range (all_steps={len(all_steps)}, expanded={len(expanded_steps)})")


async def _execute_download_with_retry(
    task_id: str,
    plan: Dict[str, Any],
    kb_id: Optional[int],
    kb_name: Optional[str],
    kb_description: Optional[str],
    max_retries: int = 3,
    user_id: int = 0,
):
    """
    Execute download task（支持重试和动态任务生成）

    流程：
    1. Execution: 执行下载（支持动态任务扩展）
    2. Quality: 质量检查
    3. 如果质量不合格：重试（最多3times）
    4. Summary: 生成报告
    """
    logger.info("后台任务开始: task_id=%s", task_id)
    progress = await _get_task_progress(user_id, task_id)
    if progress is None:
        logger.error("任务进度不存在: task_id=%s", task_id)
        return

    try:
        from app.common.mcp.mcp_service import MCPService
        from app.modules.knowledge_base.rag_service import KnowledgeBaseRagService
        from app.modules.agent_orchestration.agents.execution_agent import (
            DownloadExecutionAgent,
            GitHubExecutionAgent,
        )
        from app.modules.agent_orchestration.agents.quality_agent import QualityAgent
        from app.modules.agent_orchestration.agents.summary_agent import SummaryAgent
        from app.common.ai.llm_provider import llm_registry
        from app.common.ai.llm_adapter import LLMProviderAdapter
        from app.common.tools.github_service import github_service

        # 初始化服务
        chat_model = llm_registry.default
        llm_provider = LLMProviderAdapter(chat_model)
        mcp_service = MCPService()
        download_agent = DownloadExecutionAgent(llm_provider=llm_provider, mcp_service=mcp_service)
        github_agent = GitHubExecutionAgent(llm_provider=llm_provider, github_service=github_service)
        quality_agent = QualityAgent(llm_provider=llm_provider)
        summary_agent = SummaryAgent(llm_provider=llm_provider)

        # 执行下载（支持选择性重试）
        # all_steps_indexed: 记录每个步骤在 execution_results 中的索引位置
        # successful_results: 跨重试轮次保留成功结果，key=结果索引
        # expanded_keywords: Phase B 输出的扩展关键词，重试时传入提升匹配率
        all_steps = plan["steps"].copy()
        expanded_steps = []
        successful_results: Dict[int, Dict[str, Any]] = {}
        execution_results: List[Dict[str, Any]] = []
        expanded_keywords: List[str] = []

        for retry in range(max_retries):
            progress.retry_count = retry
            progress.message = f"执行下载（第 {retry + 1} 次尝试）..."

            try:
                if retry == 0:
                    # 第一轮：执行所有步骤
                    steps_to_execute = list(enumerate(all_steps))
                else:
                    # 重试轮：只执行失败的任务
                    failed_indices = quality_result.get("failed_task_indices", [])
                    if not failed_indices:
                        break
                    steps_to_execute = [
                        (idx, _get_step_by_index(idx, all_steps, expanded_steps))
                        for idx in failed_indices
                    ]
                    logger.info("[RETRY] 选择性重试: failed_indices=%s", failed_indices)
                    # 标记重试中的任务状态
                    for idx in failed_indices:
                        step_at_idx = _get_step_by_index(idx, all_steps, expanded_steps)
                        if step_at_idx:
                            progress.task_statuses[step_at_idx["step_id"]] = "retrying"

                new_results: Dict[int, Dict[str, Any]] = {}

                for result_idx, step in steps_to_execute:
                    # C-P4: 检查取消请求
                    if await _is_cancelled(user_id, task_id):
                        logger.info("任务已取消: task_id=%s", task_id)
                        progress.status = "cancelled"
                        progress.message = "任务已取消"
                        await _save_task_progress(user_id, task_id, progress)
                        return

                    progress.current_step = result_idx + 1
                    total = len(all_steps) + len(expanded_steps)
                    progress.progress_percent = int((result_idx + 1) / max(total, 1) * 50)
                    progress.message = f"正在执行: {step['description']}"
                    await _save_task_progress(user_id, task_id, progress)

                    # 根据任务类型选择Agent
                    if step.get("action") in ["search_github", "fetch_github_repo", "fetch_github_file"]:
                        github_task = {
                            "id": step["step_id"],
                            "type": step["action"],
                            "description": step["description"],
                            **step.get("params", {})
                        }
                        result = await github_agent.execute(task=github_task, context={})
                    else:
                        download_task = {
                            "id": str(step.get("step_id")),
                            "type": step.get("action"),
                            "description": step.get("description", ""),
                            **step.get("params", {})
                        }
                        logger.info("[CHECK] Execute download task: %s", download_task)
                        result = await download_agent.execute(task=download_task, context={})

                    # AgentMessage → dict（统一转换）
                    if hasattr(result, "model_dump"):
                        result = result.model_dump()

                    logger.info("[CHECK] Agent result type: %s", type(result))
                    new_results[result_idx] = result

                    # 更新已下载文件列表（仅新增成功的，按 step_id 去重）
                    if result and isinstance(result, dict) and result.get("status") == "success":
                        task_result = result.get("result", {})
                        file_entry = {
                            "step_id": step["step_id"],
                            "description": step["description"],
                            "size": len(task_result.get("content", "")) if isinstance(task_result, dict) else 0,
                            "metadata": task_result.get("metadata", {}) if isinstance(task_result, dict) else {},
                        }
                        existing_idx = next((i for i, f in enumerate(progress.downloaded_files) if f.get("step_id") == step["step_id"]), None)
                        if existing_idx is not None:
                            progress.downloaded_files[existing_idx] = file_entry
                        else:
                            progress.downloaded_files.append(file_entry)
                        progress.task_statuses[step["step_id"]] = "success"
                    elif result and isinstance(result, dict) and result.get("status") != "success":
                        progress.task_statuses[step["step_id"]] = "failed"

                        # 动态任务生成（仅第一轮）
                        if retry == 0 and step.get("action") == "search_github" and step.get("dynamic"):
                            repos = task_result.get("repos", []) if isinstance(task_result, dict) else []
                            max_repos = step.get("max_repos_to_fetch", 3)
                            for repo in repos[:max_repos]:
                                expanded_steps.append({
                                    "step_id": len(all_steps) + len(expanded_steps) + 1,
                                    "action": "fetch_github_repo",
                                    "params": {"repo": repo["full_name"]},
                                    "description": f"抓取 {repo['full_name']} 的文档",
                                    "source_type": "github",
                                })

                # 第一轮：执行动态生成的任务
                if retry == 0 and expanded_steps:
                    if await _is_cancelled(user_id, task_id):
                        logger.info("任务已取消: task_id=%s", task_id)
                        progress.status = "cancelled"
                        progress.message = "任务已取消"
                        await _save_task_progress(user_id, task_id, progress)
                        return
                    logger.info("[EXPAND] Dynamically generated %d tasks", len(expanded_steps))
                    progress.total_steps += len(expanded_steps)

                    for i, step in enumerate(expanded_steps):
                        result_idx = len(all_steps) + i
                        progress.current_step = result_idx + 1
                        progress.progress_percent = 50 + int((i + 1) / len(expanded_steps) * 10)
                        progress.message = f"正在执行扩展任务: {step['description']}"

                        github_task = {
                            "id": step["step_id"],
                            "type": step["action"],
                            "description": step["description"],
                            **step.get("params", {})
                        }
                        result = await github_agent.execute(task=github_task, context={})
                        if hasattr(result, "model_dump"):
                            result = result.model_dump()
                        new_results[result_idx] = result
                        progress.task_statuses[step["step_id"]] = "new"

                        if result and isinstance(result, dict) and result.get("status") == "success":
                            task_result = result.get("result", {})
                            file_entry = {
                                "step_id": step["step_id"],
                                "description": step["description"],
                                "size": len(task_result.get("content", "")) if isinstance(task_result, dict) else 0,
                                "metadata": task_result.get("metadata", {}) if isinstance(task_result, dict) else {},
                            }
                            existing_idx = next((i for i, f in enumerate(progress.downloaded_files) if f.get("step_id") == step["step_id"]), None)
                            if existing_idx is not None:
                                progress.downloaded_files[existing_idx] = file_entry
                            else:
                                progress.downloaded_files.append(file_entry)

                # 合并结果：保留之前成功的结果，覆盖本次重试的结果
                successful_results.update(new_results)

                # 按索引顺序重建 execution_results
                max_idx = max(successful_results.keys()) if successful_results else -1
                execution_results = [successful_results.get(i, {}) for i in range(max_idx + 1)]

                # 质量检查
                if await _is_cancelled(user_id, task_id):
                    logger.info("任务已取消: task_id=%s", task_id)
                    progress.status = "cancelled"
                    progress.message = "任务已取消"
                    await _save_task_progress(user_id, task_id, progress)
                    return

                logger.info("质量检查开始: task_id=%s, retry=%d", task_id, retry)
                progress.status = "quality_check"
                progress.progress_percent = 70
                progress.message = "正在进行质量检查..."

                quality_result = await quality_agent.check(
                    user_input=plan["user_input"],
                    execution_results=execution_results,
                    plan=plan,
                    expanded_keywords=expanded_keywords or None,
                )

                logger.info("质量检查完成: task_id=%s, score=%.2f, passed=%s, failed_indices=%s",
                             task_id, quality_result['score'], quality_result['passed'],
                             quality_result.get('failed_task_indices', []))
                # 设置质检详情供前端展示
                per_task = quality_result.get("per_task_results", [])
                failed_indices_set = set(quality_result.get("failed_task_indices", []))
                phase_b_used = bool(quality_result.get("overall_issues") or quality_result.get("expanded_keywords"))
                progress.quality_details = {
                    "passed_count": len([t for t in per_task if t.get("passed")]),
                    "failed_count": len(failed_indices_set),
                    "phase": "phase_b" if phase_b_used else "phase_a",
                    "total": len(per_task),
                }
                progress.quality_score = quality_result["score"] / 100.0
                # 保存 Phase B 输出的扩展关键词，供下一轮重试使用
                if quality_result.get("expanded_keywords"):
                    expanded_keywords = quality_result["expanded_keywords"]
                    logger.info("[QA] Phase B 输出扩展关键词: %s", expanded_keywords)
                await _save_task_progress(user_id, task_id, progress)

                if quality_result["passed"]:
                    logger.info("质量检查通过: task_id=%s, score=%.1f", task_id, quality_result['score'])
                    progress.retry_count = 0
                    break
                else:
                    logger.warning("质量检查未通过: task_id=%s, failed_indices=%s, issues=%s",
                                   task_id, quality_result.get('failed_task_indices', []),
                                   quality_result.get('issues', []))
                    # 诊断日志：每个失败任务的具体原因
                    for tr in quality_result.get("per_task_results", []):
                        if not tr.get("passed"):
                            logger.warning("[QA-DETAIL] Task %d failed: substance=%s, relevance=%s, reason=%s",
                                           tr.get("task_index"), tr.get("content_substance"),
                                           tr.get("topic_relevance"), tr.get("reason"))
                    if retry < max_retries - 1 and quality_result.get("failed_task_indices"):
                        progress.message = "部分任务质量不合格，准备选择性重试..."
                        # 不清空 progress.downloaded_files，保留成功结果
                        continue
                    else:
                        progress.message = "已达到最大重试次数或无失败任务，使用当前结果"
                        break

            except Exception as e:
                logger.error("[ERROR] Download failed（attempt %d times）: %s", retry + 1, e)
                if retry < max_retries - 1:
                    continue
                else:
                    raise

        # 生成总结
        progress.status = "summarizing"
        progress.progress_percent = 85
        progress.message = "正在整合内容..."
        await _save_task_progress(user_id, task_id, progress)

        # 整合所有内容为一篇文档
        integrated_doc = None
        try:
            logger.info(f"[INTEGRATE] Prepare to integrate content，execution_results count: {len(execution_results)}")
            for i, result in enumerate(execution_results):
                logger.info(f"  execution_results[{i}]: type={type(result)}")
                if result is None:
                    logger.warning(f"    Result is None")
                elif isinstance(result, dict):
                    logger.info(f"    keys={list(result.keys())}")
                    logger.info(f"    status={result.get('status')}")
                    logger.info(f"    has_result={bool(result.get('result'))}")
                    if result.get('result'):
                        result_data = result.get('result')
                        logger.info(f"    result type={type(result_data)}")
                        if isinstance(result_data, dict):
                            logger.info(f"    result keys={list(result_data.keys())}")
                else:
                    logger.warning(f"    Result type error: {type(result)}")

            integrated_doc = await download_agent.integrate_contents(
                execution_results=execution_results,
                user_input=plan["user_input"],
            )
        except Exception as e:
            logger.error("内容整合失败: %s", e, exc_info=True)
            progress.status = "failed"
            progress.message = f"Content integration failed: {str(e)}"
            return

        if not integrated_doc:
            logger.error("[ERROR] Content integration returned empty result")
            progress.status = "failed"
            progress.message = "Content integration failed: 没有生成有效文档"
            return

        logger.info(f"[OK] Content integration successful")
        logger.info(f"  integrated_doc type: {type(integrated_doc)}")
        logger.info(f"  integrated_doc keys: {integrated_doc.keys() if isinstance(integrated_doc, dict) else 'N/A'}")
        logger.info(f"  title: {integrated_doc.get('title', 'N/A') if isinstance(integrated_doc, dict) else 'N/A'}")

        # 使用 SummaryAgent 精炼文档（结构化目录+要点提炼）
        try:
            refined_content = await summary_agent.refine_document(
                user_input=plan["user_input"],
                integrated_doc=integrated_doc,
            )
            if refined_content:
                integrated_doc["integrated_content"] = refined_content
                logger.info("[SUMMARY] 文档精炼完成，长度: %d", len(refined_content))
        except Exception as e:
            logger.warning("[SUMMARY] 文档精炼失败，使用原文: %s", e)

        # 添加到知识库
        progress.status = "indexing"
        progress.progress_percent = 90
        progress.message = "正在添加到知识库..."
        await _save_task_progress(user_id, task_id, progress)

        kb_result = None
        try:
            logger.info(f"[KB] Prepare to call _add_to_knowledge_base")
            logger.info(f"  integrated_doc type: {type(integrated_doc)}")
            logger.info(f"  kb_id: {kb_id}, kb_name: {kb_name}")

            kb_result = await _add_to_knowledge_base(
                integrated_doc=integrated_doc,
                kb_id=kb_id,
                kb_name=kb_name,
                kb_description=kb_description,
                user_id=user_id,
            )

            logger.info(f"[KB] _add_to_knowledge_base returned: {kb_result}")

            # 触发索引任务（在_add_to_knowledge_base之外调用，确保Redis连接可用）
            if kb_result and kb_result.get("kb_id"):
                try:
                    from app.modules.knowledge_base.upload_service import knowledge_base_upload_service
                    kb_id_to_index = kb_result["kb_id"]
                    logger.info(f"[KB] Calling _enqueue_index for kb_id={kb_id_to_index}")
                    await knowledge_base_upload_service._enqueue_index(kb_id_to_index)
                    logger.info(f"[KB] Index task enqueued successfully for kb_id={kb_id_to_index}")
                except Exception as idx_err:
                    logger.error(f"[KB] Failed to enqueue index task: {idx_err}", exc_info=True)

        except Exception as e:
            logger.error(f"[ERROR] Failed to add to knowledge base: {e}", exc_info=True)
            progress.status = "failed"
            progress.message = f"Failed to add to knowledge base: {str(e)}"
            await _save_task_progress(user_id, task_id, progress)
            return

        # 完成
        progress.status = "completed"
        progress.progress_percent = 100
        progress.message = f"完成！已整合 {integrated_doc.get('source_count', 0)} 个来源，文档长度: {integrated_doc.get('total_length', 0)} 字"

        # 添加整合文档信息到进度
        progress.integrated_doc = {
            "title": integrated_doc.get('title', ''),
            "summary": integrated_doc.get('summary', ''),
            "source_count": integrated_doc.get('source_count', 0),
            "total_length": integrated_doc.get('total_length', 0),
            "sources": integrated_doc.get('sources', []),
            "content": integrated_doc.get('integrated_content', ''),
            "source_summaries": integrated_doc.get('source_summaries', []),
        }

        # 添加知识库信息
        if kb_result:
            progress.kb_info = {
                "kb_id": kb_result.get("kb_id"),
                "kb_name": kb_result.get("kb_name"),
                "doc_id": kb_result.get("doc_id"),
            }

        progress.downloaded_files.append({
            "step_id": 0,
            "description": f"整合文档: {integrated_doc.get('title', '未知标题')}",
            "size": integrated_doc.get('total_length', 0),
            "metadata": {
                "title": integrated_doc.get('title', ''),
                "summary": integrated_doc.get('summary', ''),
                "sources": integrated_doc.get('sources', []),
                "kb_id": kb_result.get("kb_id") if kb_result and isinstance(kb_result, dict) else None,
                "doc_id": kb_result.get("doc_id") if kb_result and isinstance(kb_result, dict) else None,
            },
        })

        logger.info("下载任务完成: task_id=%s", task_id)
        await _save_task_progress(user_id, task_id, progress)

    except Exception as e:
        logger.error("下载任务失败: task_id=%s, error=%s", task_id, e, exc_info=True)
        progress.status = "failed"
        progress.message = f"下载失败: {str(e)}"
        await _save_task_progress(user_id, task_id, progress)


async def _check_download_quality(
    downloaded_files: list[Dict[str, Any]],
    intent: Dict[str, Any]
) -> Dict[str, Any]:
    """
    质量检查（简化版，用于兼容）

    检查项：
    1. 下载成功率
    2. 内容相关性
    3. 内容完整性
    """
    if not downloaded_files:
        return {
            "passed": False,
            "score": 0.0,
            "reason": "没有成功下载任何文件"
        }

    # 简单的质量评分
    total_size = sum(len(f.get("content", "")) for f in downloaded_files if f and isinstance(f, dict))
    avg_size = total_size / len(downloaded_files)

    # 如果平均文件大小太小，可能是Download failed
    if avg_size < 100:
        return {
            "passed": False,
            "score": 0.3,
            "reason": "下载的内容过少，可能不完整"
        }

    # 计算成功率
    target_count = len(intent.get("target_resources", [])) if intent and isinstance(intent, dict) else 1
    success_rate = len(downloaded_files) / max(target_count, 1)

    score = min(success_rate * 0.7 + 0.3, 1.0)

    return {
        "passed": score >= 0.6,
        "score": score,
        "reason": "Quality check passed" if score >= 0.6 else "部分Download failed或内容不完整"
    }


async def _add_to_knowledge_base(
    integrated_doc: Dict[str, Any],
    kb_id: Optional[int],
    kb_name: Optional[str],
    kb_description: Optional[str],
    user_id: int = 0,
) -> Dict[str, Any]:
    """
    将整合后的文档添加到知识库

    Args:
        integrated_doc: 整合后的文档
        kb_id: 知识库ID（如果为None则创建新库）
        kb_name: 知识库名称
        kb_description: 知识库描述

    Returns:
        保存结果，包含 kb_id 和 doc_id
    """
    from app.database import get_db_context
    from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity
    from app.modules.knowledge_base.rag_service import KnowledgeBaseRagService

    async with get_db_context() as db:
        # 如果没有指定知识库，创建新的
        if not kb_id:
            kb_name = kb_name or integrated_doc.get("title", "智能下载知识库")
            kb_description = kb_description or integrated_doc.get("summary", "")

            # 生成文件哈希（使用内容的哈希）
            import hashlib
            content = integrated_doc.get("integrated_content", "")
            file_hash = hashlib.sha256(content.encode()).hexdigest()

            kb = KnowledgeBaseEntity(
                user_id=user_id,
                name=kb_name,
                description=kb_description,
                file_hash=file_hash,
                original_filename=f"{kb_name}.md",
                file_size=len(content),
                content_type="text/markdown",
                source_text=content,
                chunk_count=0,
                document_count=1,
                index_status="PENDING",
            )
            db.add(kb)
            await db.flush()
            kb_id = kb.id
            logger.info(f"[KB] Create new knowledge base: {kb_name} (ID: {kb_id})")
        else:
            await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
            logger.info(f"[KB] Use existing knowledge base ID: {kb_id}")

        await db.commit()

        logger.info(f"[DOC] Document saved to knowledge base (ID: {kb_id})")

        return {
            "kb_id": kb_id,
            "kb_name": kb_name,
        }
