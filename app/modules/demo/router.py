import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.model import AsyncTaskStatus
from app.common.result import Result
from app.database import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.demo.schemas import DemoSeedResponse
from app.modules.interview.models import InterviewAnswerEntity, InterviewSessionEntity, SessionStatus
from app.modules.interview.schemas import InterviewQuestionDTO, KeyPoint
from app.modules.resume.models import ResumeAnalysisEntity, ResumeEntity

router = APIRouter()

DEMO_FILE_HASH_PREFIX = "demo-offerpilot"
DEMO_SKILL_ID = "demo-coach-report"


@router.post("/seed", response_model=Result[DemoSeedResponse])
async def seed_demo_data(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    resume = await _ensure_demo_resume(db, user_id)
    await _ensure_demo_analysis(db, resume)
    session = await _ensure_demo_interview_session(db, user_id, resume.id)
    payload = DemoSeedResponse(
        resume_id=resume.id,
        interview_session_id=session.session_id,
        resume_path=f"/resumes/{resume.id}",
        interview_report_path=f"/interviews/{session.session_id}",
        message="演示数据已准备好，可直接查看简历分析、面试报告和同题再练。",
    )
    return Result.success(payload)


async def _ensure_demo_resume(db: AsyncSession, user_id: int) -> ResumeEntity:
    file_hash = f"{DEMO_FILE_HASH_PREFIX}-{user_id}"
    result = await db.execute(
        select(ResumeEntity).where(
            ResumeEntity.user_id == user_id,
            ResumeEntity.file_hash == file_hash,
        )
    )
    resume = result.scalar_one_or_none()
    if resume:
        return resume

    resume = ResumeEntity(
        user_id=user_id,
        file_hash=file_hash,
        original_filename="OfferPilot演示简历.pdf",
        file_size=186000,
        content_type="application/pdf",
        storage_key=f"demo/{user_id}/offerpilot-resume.pdf",
        storage_url=None,
        resume_text=_demo_resume_text(),
        analyze_status=AsyncTaskStatus.COMPLETED,
    )
    db.add(resume)
    await db.flush()
    return resume


async def _ensure_demo_analysis(db: AsyncSession, resume: ResumeEntity) -> ResumeAnalysisEntity:
    result = await db.execute(select(ResumeAnalysisEntity).where(ResumeAnalysisEntity.resume_id == resume.id).limit(1))
    analysis = result.scalar_one_or_none()
    if analysis:
        return analysis

    analysis = ResumeAnalysisEntity(
        resume_id=resume.id,
        overall_score=78,
        content_score=80,
        structure_score=75,
        skill_match_score=82,
        expression_score=76,
        project_score=79,
        summary="候选人具备 AI 应用全栈交付经验，但项目指标、个人贡献边界和异常兜底仍需要更清晰。",
        strengths_json=json.dumps(
            [
                "能把简历解析、RAG、模拟面试串成完整训练链路",
                "具备 FastAPI、React、PostgreSQL、Redis 的端到端实现经验",
                "有产品化意识，能围绕复盘报告设计用户闭环",
            ],
            ensure_ascii=False,
        ),
        suggestions_json=json.dumps(
            [
                {
                    "category": "结果指标",
                    "priority": "HIGH",
                    "issue": "项目成果偏描述，缺少耗时、准确率、留存或转化指标。",
                    "recommendation": "补充 2-3 个可验证指标，并说明数据如何采集。",
                },
                {
                    "category": "个人贡献",
                    "priority": "HIGH",
                    "issue": "全栈开发表述较宽泛，面试官难判断个人决策深度。",
                    "recommendation": "明确负责模块、关键取舍、踩坑过程和最终产出。",
                },
                {
                    "category": "工程稳定性",
                    "priority": "MEDIUM",
                    "issue": "AI 调用失败、Redis 入队失败、报告生成失败的兜底说明不足。",
                    "recommendation": "按触发条件、降级策略、监控告警整理成一段回答。",
                },
            ],
            ensure_ascii=False,
        ),
        profile_json=json.dumps(
            {
                "projects": [
                    {
                        "name": "OfferPilot AI 面试训练平台",
                        "role": "产品与全栈开发",
                        "tech_stack": ["FastAPI", "React", "PostgreSQL", "Redis", "RAG", "LLM"],
                        "description": "围绕求职者训练场景，提供简历诊断、项目深挖、模拟面试和报告复盘。",
                        "highlights": [
                            "将简历画像与面试题生成联动",
                            "新增教练式反馈字段，输出 80/90 分示范答案",
                            "用配置检查和 E2E 冒烟测试降低演示故障率",
                        ],
                    }
                ],
                "tech_stacks": [
                    {"name": "FastAPI", "proficiency": "熟练", "context": "后端 API、鉴权、异步任务"},
                    {"name": "React", "proficiency": "熟练", "context": "训练工作台、报告页、表单流"},
                    {"name": "PostgreSQL", "proficiency": "熟练", "context": "业务数据建模与报告持久化"},
                    {"name": "Redis", "proficiency": "了解", "context": "异步评估任务队列"},
                ],
                "experience_level": "mid",
                "has_projects": True,
                "summary": "适合 AI 应用开发、后端开发、全栈产品工程岗位。",
            },
            ensure_ascii=False,
        ),
    )
    db.add(analysis)
    await db.flush()
    return analysis


async def _ensure_demo_interview_session(
    db: AsyncSession,
    user_id: int,
    resume_id: int,
) -> InterviewSessionEntity:
    result = await db.execute(
        select(InterviewSessionEntity)
        .where(
            InterviewSessionEntity.user_id == user_id,
            InterviewSessionEntity.skill_id == DEMO_SKILL_ID,
        )
        .order_by(InterviewSessionEntity.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session:
        return session

    questions = _demo_questions()
    reference_answers = [
        {
            "question_index": question.question_index,
            "question": question.question,
            "reference_answer": question.reference_answer,
            "key_points": [point.point for point in (question.key_points or [])],
        }
        for question in questions
    ]
    session = InterviewSessionEntity(
        user_id=user_id,
        session_id=uuid.uuid4().hex[:16],
        skill_id=DEMO_SKILL_ID,
        difficulty="demo",
        resume_id=resume_id,
        total_questions=len(questions),
        current_question_index=len(questions),
        status=SessionStatus.EVALUATED,
        questions_json=json.dumps([question.model_dump() for question in questions], ensure_ascii=False),
        overall_score=76,
        overall_feedback="整体具备项目完整度和工程意识，但回答还需要更强的量化结果、个人决策和失败兜底。",
        strengths_json=json.dumps(
            [
                "能说明项目从简历到面试复盘的完整闭环",
                "技术栈覆盖前后端、数据层和 AI 调用链路",
                "已经能从产品视角解释目标用户和交付路径",
            ],
            ensure_ascii=False,
        ),
        improvements_json=json.dumps(
            [
                "回答中补充真实指标或阶段性指标",
                "把个人贡献从“参与开发”改成“我做了哪些决策”",
                "准备异常场景和成本控制的追问回答",
            ],
            ensure_ascii=False,
        ),
        reference_answers_json=json.dumps(reference_answers, ensure_ascii=False),
        evaluate_status=AsyncTaskStatus.COMPLETED.value,
        llm_provider="demo",
        completed_at=datetime.now(),
    )
    db.add(session)
    await db.flush()

    for answer in _demo_answers(session.id):
        db.add(answer)
    await db.flush()
    return session


def _demo_questions() -> list[InterviewQuestionDTO]:
    return [
        InterviewQuestionDTO(
            question_index=0,
            question="请用 2 分钟介绍 OfferPilot 项目，并说明你个人负责的关键模块。",
            type="PROJECT",
            category="项目介绍",
            question_type="project",
            reference_answer="可以按目标用户、核心流程、个人贡献、技术难点、结果指标五段回答。",
            key_points=[
                KeyPoint(point="目标用户与痛点", score_range="60-70", weight="MEDIUM"),
                KeyPoint(point="个人负责模块", score_range="70-85", weight="HIGH"),
                KeyPoint(point="可验证结果", score_range="80-95", weight="HIGH"),
            ],
        ),
        InterviewQuestionDTO(
            question_index=1,
            question="AI 评估失败、Redis 入队失败或模型响应不稳定时，你怎么保证用户体验？",
            type="PROJECT",
            category="异常兜底",
            question_type="project",
            reference_answer="建议从同步提示、任务状态、重试、降级报告、日志告警、配置检查六点说明。",
            key_points=[
                KeyPoint(point="失败状态可见", score_range="60-75", weight="HIGH"),
                KeyPoint(point="重试与降级策略", score_range="70-85", weight="HIGH"),
                KeyPoint(point="监控与定位", score_range="80-95", weight="MEDIUM"),
            ],
        ),
    ]


def _demo_answers(session_entity_id: int) -> list[InterviewAnswerEntity]:
    payloads = [
        {
            "question_index": 0,
            "question": "请用 2 分钟介绍 OfferPilot 项目，并说明你个人负责的关键模块。",
            "category": "项目介绍",
            "user_answer": "这是一个 AI 面试助手，我做了简历分析、面试、报告这些功能，前后端都有参与。",
            "score": 62,
            "feedback": "面试官判断：项目完整度可以，但个人贡献和结果指标不够清楚。当前风险点：容易被追问你到底做了哪些关键决策。80分改法：按目标、链路、贡献、难点、结果五段重答。下一步追问：你如何证明这个项目真正提升了训练效果？",
            "reference_answer": "OfferPilot 面向求职者和培训机构，把简历诊断、项目深挖、模拟面试和报告复盘串成训练闭环。我负责后端会话、评估持久化、教练式反馈和前端报告页。",
            "metadata": {
                "question_type": "project",
                "dimensions": {"authenticity": 72, "technical_depth": 65, "depth": 62, "expression": 70},
                "interviewer_judgement": "项目方向清楚，但回答还像功能清单，缺少个人决策和业务结果。",
                "answer_issues": ["没有说明目标用户的真实痛点", "个人贡献边界模糊", "缺少量化指标"],
                "answer_framework": ["目标用户", "核心链路", "个人贡献", "技术取舍", "结果指标"],
                "answer_80": "OfferPilot 面向求职者和培训机构，解决简历改完后不知道怎么练的问题。我负责会话生成、报告持久化、教练式反馈和前端报告页，把简历画像、项目深挖、模拟面试串成闭环。技术上用 FastAPI 承接 API，Redis 做异步评估队列，PostgreSQL 保存问答与报告，前端把低分题、80 分回答和同题再练放在同一页。",
                "answer_90": "我会补充真实指标：例如演示链路 10 个核心接口冒烟通过、报告页低分题可一键进入同题再练、配置检查前置后本地演示失败从启动后暴露变成启动时暴露。同时说明我做过的取舍：先用规则化教练字段保证输出稳定，再逐步引入更细的班级/组织运营数据。",
                "next_practice_question": "如果让你把 OfferPilot 卖给一个培训机构，你会用哪 3 个指标证明它值得续费？",
            },
        },
        {
            "question_index": 1,
            "question": "AI 评估失败、Redis 入队失败或模型响应不稳定时，你怎么保证用户体验？",
            "category": "异常兜底",
            "user_answer": "可以让用户稍后刷新，如果失败就在日志里看错误，然后重新提交。",
            "score": 58,
            "feedback": "面试官判断：知道要重试，但没有形成工程化兜底链路。当前风险点：面试官会担心线上不可用。80分改法：按状态、重试、降级、告警四层说明。下一步追问：如果 Redis 挂了，用户提交答案后界面应该看到什么？",
            "reference_answer": "用户侧展示 PENDING/FAILED 状态和错误提示；服务侧记录 evaluate_error，失败时允许重新生成；配置检查在启动前暴露缺失项；关键任务失败进入日志和告警。",
            "metadata": {
                "question_type": "project",
                "dimensions": {"authenticity": 68, "technical_depth": 60, "depth": 58, "expression": 64},
                "interviewer_judgement": "回答停留在人工排查，缺少可恢复设计。",
                "answer_issues": ["没有用户侧状态", "没有服务侧重试策略", "没有配置与依赖检查"],
                "answer_framework": ["状态可见", "自动重试", "人工重跑", "降级提示", "日志告警"],
                "answer_80": "我会先保证状态可见：答案提交成功后会话进入 COMPLETED，评估任务标记 PENDING；如果 Redis 入队失败，evaluate_status 会写成 FAILED 并保留 evaluate_error，报告页展示失败原因。其次提供重试入口或后台重跑；模型波动时用超时、重试和结构化 fallback；启动时通过配置检查提前发现缺 key、CORS 或依赖问题。",
                "answer_90": "进一步我会把失败分层：用户输入类直接提示修正；模型类可降级为简短评估；队列类保留答案并延迟重试；基础设施类进入告警。这样用户不会丢数据，运营人员能看到失败原因，开发也能快速定位到模型、队列还是配置问题。",
                "next_practice_question": "请设计一个“报告生成失败后重新评估”的接口和前端交互。",
            },
        },
    ]
    return [
        InterviewAnswerEntity(
            session_id=session_entity_id,
            question_index=item["question_index"],
            question=item["question"],
            category=item["category"],
            user_answer=item["user_answer"],
            score=item["score"],
            feedback=item["feedback"],
            reference_answer=item["reference_answer"],
            key_points_json=json.dumps(item["metadata"], ensure_ascii=False),
        )
        for item in payloads
    ]


def _demo_resume_text() -> str:
    return """
姓名：演示候选人
目标岗位：AI 应用开发 / 后端开发 / 全栈产品工程师
项目：OfferPilot AI 面试训练平台
职责：负责产品方案、后端 API、面试会话、报告复盘、前端训练工作台。
技术栈：FastAPI、React、PostgreSQL、Redis、RAG、LLM、Docker。
亮点：将简历诊断、项目深挖、模拟面试、教练式反馈和同题再练串成闭环。
""".strip()
