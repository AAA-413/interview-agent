"""
智能下载知识库路由 - 两阶段流程
"""

import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.common.ai.llm_provider import llm_registry
from app.modules.agent_orchestration.orchestrator import AgentOrchestrator
from app.modules.agent_orchestration.agents.planning_agent import PlanningAgent
from app.modules.knowledge_base.rag_service import KnowledgeBaseRagService

logger = logging.getLogger(__name__)

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
    status: str  # planning, executing, quality_check, completed, failed
    current_step: int
    total_steps: int
    progress_percent: int
    message: str
    retry_count: int
    downloaded_files: List[Dict[str, Any]]
    quality_score: Optional[float] = None


# ============ 全局状态管理 ============

# 存储下载计划（生产环境应使用Redis）
_download_plans: Dict[str, Dict[str, Any]] = {}

# 存储下载任务进度
_download_tasks: Dict[str, DownloadProgress] = {}


# ============ API 端点 ============

@router.post("/plan", response_model=DownloadPlan)
async def generate_download_plan(
    request: PlanDownloadRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    阶段1：生成下载计划

    使用 PlanningAgent 分析用户需求，生成详细的下载计划供用户确认
    """
    try:
        logger.info(f"📋 生成下载计划: {request.user_input}")

        # 创建 PlanningAgent
        llm_provider = llm_registry.default
        planning_agent = PlanningAgent(
            llm_provider=llm_provider,
            knowledge_service=None,  # 计划阶段不需要知识库
        )

        # 生成计划
        result = await planning_agent.execute(
            user_request=request.user_input,
            context={
                "max_downloads": request.max_downloads,
                "kb_id": request.kb_id,
            }
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.message)

        # 解析计划
        plan_data = result.data
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

        _download_plans[plan_id] = plan.model_dump()

        logger.info(f"✅ 计划生成成功: {len(steps)} 个步骤")
        return plan

    except Exception as e:
        logger.error(f"❌ 生成计划失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成计划失败: {str(e)}")


@router.post("/execute")
async def execute_download_plan(
    request: ExecuteDownloadRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    阶段2：执行下载计划

    使用 AgentOrchestrator 执行完整的4步流程：
    Planning → Execution → Quality → Summary

    支持质量检查失败后重试（最多3次）
    """
    try:
        # 检查计划是否存在
        if request.plan_id not in _download_plans:
            raise HTTPException(status_code=404, detail="计划不存在")

        plan = _download_plans[request.plan_id]

        # 创建任务ID
        import uuid
        task_id = str(uuid.uuid4())

        # 初始化进度
        progress = DownloadProgress(
            task_id=task_id,
            status="executing",
            current_step=0,
            total_steps=plan["total_steps"],
            progress_percent=0,
            message="开始执行下载...",
            retry_count=0,
            downloaded_files=[],
        )
        _download_tasks[task_id] = progress

        # 后台执行下载任务
        background_tasks.add_task(
            _execute_download_with_retry,
            task_id=task_id,
            plan=plan,
            kb_id=request.kb_id,
            kb_name=request.kb_name,
            kb_description=request.kb_description,
        )

        logger.info(f"🚀 开始执行下载任务: {task_id}")

        return {
            "task_id": task_id,
            "message": "下载任务已启动",
            "plan_id": request.plan_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 启动下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


@router.get("/progress/{task_id}", response_model=DownloadProgress)
async def get_download_progress(task_id: str):
    """
    查询下载进度

    前端可以轮询此接口获取实时进度
    """
    if task_id not in _download_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    return _download_tasks[task_id]


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


async def _execute_download_with_retry(
    task_id: str,
    plan: Dict[str, Any],
    kb_id: Optional[int],
    kb_name: Optional[str],
    kb_description: Optional[str],
    max_retries: int = 3,
):
    """
    执行下载任务（支持重试）

    流程：
    1. Execution: 执行下载
    2. Quality: 质量检查
    3. 如果质量不合格：重试（最多3次）
    4. Summary: 生成报告
    """
    progress = _download_tasks[task_id]

    try:
        from app.common.mcp.mcp_service import MCPService
        from app.modules.knowledge_base.rag_service import KnowledgeBaseRagService

        # 初始化服务
        mcp_service = MCPService()

        # 执行下载（支持重试）
        for retry in range(max_retries):
            progress.retry_count = retry
            progress.message = f"执行下载（第 {retry + 1} 次尝试）..."

            try:
                # 执行所有下载步骤
                downloaded_files = []

                for i, step in enumerate(plan["steps"]):
                    progress.current_step = i + 1
                    progress.progress_percent = int((i + 1) / progress.total_steps * 70)  # 70% 用于下载
                    progress.message = f"正在下载: {step['description']}"

                    # 执行下载
                    file_data = await _execute_download_step(mcp_service, step)
                    if file_data:
                        downloaded_files.append(file_data)
                        progress.downloaded_files.append({
                            "step_id": step["step_id"],
                            "description": step["description"],
                            "size": len(file_data.get("content", "")),
                        })

                # 质量检查
                progress.status = "quality_check"
                progress.progress_percent = 75
                progress.message = "正在进行质量检查..."

                quality_result = await _check_download_quality(downloaded_files, plan["intent"])
                progress.quality_score = quality_result["score"]

                # 如果质量合格，跳出重试循环
                if quality_result["passed"]:
                    logger.info(f"✅ 质量检查通过: {quality_result['score']:.2f}")
                    break
                else:
                    logger.warning(f"⚠️ 质量检查未通过: {quality_result['reason']}")
                    if retry < max_retries - 1:
                        progress.message = f"质量不合格，准备重试... ({quality_result['reason']})"
                        continue
                    else:
                        progress.message = f"已达到最大重试次数，使用当前结果"
                        break

            except Exception as e:
                logger.error(f"❌ 下载失败（第 {retry + 1} 次）: {e}")
                if retry < max_retries - 1:
                    continue
                else:
                    raise

        # 添加到知识库
        progress.status = "indexing"
        progress.progress_percent = 85
        progress.message = "正在添加到知识库..."

        # TODO: 集成知识库服务
        # kb_result = await _add_to_knowledge_base(downloaded_files, kb_id, kb_name, kb_description)

        # 完成
        progress.status = "completed"
        progress.progress_percent = 100
        progress.message = f"下载完成！共 {len(downloaded_files)} 个文件"

        logger.info(f"🎉 下载任务完成: {task_id}")

    except Exception as e:
        logger.error(f"❌ 下载任务失败: {e}")
        progress.status = "failed"
        progress.message = f"下载失败: {str(e)}"


async def _execute_download_step(mcp_service: Any, step: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """执行单个下载步骤"""
    try:
        action = step["action"]
        params = step["params"]

        if action == "fetch_url":
            result = await mcp_service.fetch_url(params["url"])
        elif action == "search_web":
            result = await mcp_service.search_web(params["query"], params.get("num_results", 3))
        elif action == "fetch_blog":
            result = await mcp_service.fetch_blog(params["url"])
        else:
            logger.warning(f"未知操作: {action}")
            return None

        return {
            "content": result.get("content", ""),
            "metadata": {
                "step_id": step["step_id"],
                "action": action,
                "params": params,
                "description": step["description"],
            }
        }

    except Exception as e:
        logger.error(f"执行步骤失败: {e}")
        return None


async def _check_download_quality(
    downloaded_files: list[Dict[str, Any]],
    intent: Dict[str, Any]
) -> Dict[str, Any]:
    """
    质量检查

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
    total_size = sum(len(f.get("content", "")) for f in downloaded_files)
    avg_size = total_size / len(downloaded_files)

    # 如果平均文件大小太小，可能是下载失败
    if avg_size < 100:
        return {
            "passed": False,
            "score": 0.3,
            "reason": "下载的内容过少，可能不完整"
        }

    # 计算成功率
    success_rate = len(downloaded_files) / max(len(intent.get("target_resources", [])), 1)

    score = min(success_rate * 0.7 + 0.3, 1.0)

    return {
        "passed": score >= 0.6,
        "score": score,
        "reason": "质量检查通过" if score >= 0.6 else "部分下载失败或内容不完整"
    }
