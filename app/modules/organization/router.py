from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.auth.models import UserEntity
from app.modules.interview.models import InterviewAnswerEntity, InterviewSessionEntity, SessionStatus
from app.modules.organization.models import OrganizationEntity, OrganizationMemberEntity, OrganizationRole
from app.modules.organization.schemas import (
    OrganizationCreateRequest,
    OrganizationDashboardDTO,
    OrganizationDashboardSummaryDTO,
    OrganizationDTO,
    OrganizationMemberAddRequest,
    OrganizationMemberDTO,
    OrganizationMemberTrainingDTO,
)
from app.modules.resume.models import ResumeEntity

router = APIRouter()


@router.get("", response_model=Result[list[OrganizationDTO]])
async def list_organizations(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    member_count_subq = (
        select(
            OrganizationMemberEntity.organization_id,
            func.count(OrganizationMemberEntity.id).label("member_count"),
        )
        .group_by(OrganizationMemberEntity.organization_id)
        .subquery()
    )
    stmt = (
        select(
            OrganizationEntity,
            OrganizationMemberEntity.role,
            func.coalesce(member_count_subq.c.member_count, 0),
        )
        .join(OrganizationMemberEntity, OrganizationMemberEntity.organization_id == OrganizationEntity.id)
        .outerjoin(member_count_subq, member_count_subq.c.organization_id == OrganizationEntity.id)
        .where(OrganizationMemberEntity.user_id == user_id)
        .order_by(OrganizationEntity.updated_at.desc())
    )
    result = await db.execute(stmt)
    data = [
        OrganizationDTO(
            id=org.id,
            owner_id=org.owner_id,
            name=org.name,
            description=org.description,
            member_count=int(member_count or 0),
            current_user_role=role,
            created_at=org.created_at,
            updated_at=org.updated_at,
        )
        for org, role, member_count in result.all()
    ]
    return Result.success(data)


@router.post("", response_model=Result[OrganizationDTO])
async def create_organization(
    request: OrganizationCreateRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    org = OrganizationEntity(owner_id=user_id, name=request.name, description=request.description)
    db.add(org)
    await db.flush()

    member = OrganizationMemberEntity(
        organization_id=org.id,
        user_id=user_id,
        role=OrganizationRole.OWNER,
        note="创建者",
    )
    db.add(member)
    await db.flush()

    return Result.success(
        OrganizationDTO(
            id=org.id,
            owner_id=org.owner_id,
            name=org.name,
            description=org.description,
            member_count=1,
            current_user_role=OrganizationRole.OWNER,
            created_at=org.created_at,
            updated_at=org.updated_at,
        )
    )


@router.get("/{organization_id}/members", response_model=Result[list[OrganizationMemberDTO]])
async def list_members(
    organization_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(db, organization_id, user_id)
    members = await _member_rows(db, organization_id)
    return Result.success(members)


@router.get("/{organization_id}/dashboard", response_model=Result[OrganizationDashboardDTO])
async def get_dashboard(
    organization_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(db, organization_id, user_id)
    rows = await _member_entity_rows(db, organization_id)
    user_ids = [member.user_id for member, _user in rows]
    if not user_ids:
        return Result.success(
            OrganizationDashboardDTO(
                organization_id=organization_id,
                generated_at=datetime.now(),
                summary=OrganizationDashboardSummaryDTO(),
                members=[],
            )
        )

    resumes = await _load_resumes(db, user_ids)
    sessions = await _load_sessions(db, user_ids)
    low_scores = await _load_low_score_counts(db, user_ids)
    member_metrics = [
        _build_member_training(
            member, user, resumes.get(member.user_id, []), sessions.get(member.user_id, []), low_scores
        )
        for member, user in rows
    ]

    summary = OrganizationDashboardSummaryDTO(
        member_count=len(member_metrics),
        active_member_count=sum(1 for item in member_metrics if item.last_activity_at is not None),
        resume_count=sum(item.resume_count for item in member_metrics),
        analyzed_resume_count=sum(item.analyzed_resume_count for item in member_metrics),
        average_resume_score=_average_score(
            [item.latest_resume_score for item in member_metrics if item.latest_resume_score is not None]
        ),
        interview_count=sum(item.interview_count for item in member_metrics),
        evaluated_interview_count=sum(item.evaluated_interview_count for item in member_metrics),
        retry_session_count=sum(item.retry_session_count for item in member_metrics),
        completed_retry_session_count=sum(item.completed_retry_session_count for item in member_metrics),
        low_score_question_count=sum(item.low_score_question_count for item in member_metrics),
    )

    return Result.success(
        OrganizationDashboardDTO(
            organization_id=organization_id,
            generated_at=datetime.now(),
            summary=summary,
            members=member_metrics,
        )
    )


@router.post("/{organization_id}/members", response_model=Result[OrganizationMemberDTO])
async def add_member(
    organization_id: int,
    request: OrganizationMemberAddRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(db, organization_id, user_id)
    user = await _find_user_by_name_or_email(db, request.username_or_email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在，请先让学员注册账号")

    existing = await db.execute(
        select(OrganizationMemberEntity).where(
            OrganizationMemberEntity.organization_id == organization_id,
            OrganizationMemberEntity.user_id == user.id,
        )
    )
    member = existing.scalar_one_or_none()
    if member is None:
        member = OrganizationMemberEntity(
            organization_id=organization_id,
            user_id=user.id,
            role=request.role,
            note=request.note,
        )
        db.add(member)
    else:
        member.role = request.role
        member.note = request.note
    await db.flush()

    return Result.success(_to_member_dto(member, user))


@router.delete("/{organization_id}/members/{member_id}", response_model=Result[None])
async def remove_member(
    organization_id: int,
    member_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    admin_member = await _require_admin(db, organization_id, user_id)
    result = await db.execute(
        select(OrganizationMemberEntity).where(
            OrganizationMemberEntity.organization_id == organization_id,
            OrganizationMemberEntity.id == member_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="成员不存在")
    if member.role == OrganizationRole.OWNER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能移除组织拥有者")
    if member.id == admin_member.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能移除自己")
    await db.delete(member)
    await db.flush()
    return Result.success(None)


async def _require_member(db: AsyncSession, organization_id: int, user_id: int) -> OrganizationMemberEntity:
    result = await db.execute(
        select(OrganizationMemberEntity).where(
            OrganizationMemberEntity.organization_id == organization_id,
            OrganizationMemberEntity.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="组织不存在或无访问权限")
    return member


async def _require_admin(db: AsyncSession, organization_id: int, user_id: int) -> OrganizationMemberEntity:
    member = await _require_member(db, organization_id, user_id)
    if member.role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要组织管理员权限")
    return member


async def _find_user_by_name_or_email(db: AsyncSession, username_or_email: str) -> UserEntity | None:
    key = username_or_email.strip()
    result = await db.execute(select(UserEntity).where(or_(UserEntity.username == key, UserEntity.email == key)))
    return result.scalar_one_or_none()


async def _member_rows(db: AsyncSession, organization_id: int) -> list[OrganizationMemberDTO]:
    rows = await _member_entity_rows(db, organization_id)
    return [_to_member_dto(member, user) for member, user in rows]


async def _member_entity_rows(
    db: AsyncSession, organization_id: int
) -> list[tuple[OrganizationMemberEntity, UserEntity]]:
    result = await db.execute(
        select(OrganizationMemberEntity, UserEntity)
        .join(UserEntity, UserEntity.id == OrganizationMemberEntity.user_id)
        .where(OrganizationMemberEntity.organization_id == organization_id)
        .order_by(OrganizationMemberEntity.role, OrganizationMemberEntity.joined_at)
    )
    return list(result.all())


async def _load_resumes(db: AsyncSession, user_ids: list[int]) -> dict[int, list[ResumeEntity]]:
    result = await db.execute(select(ResumeEntity).where(ResumeEntity.user_id.in_(user_ids)))
    grouped: dict[int, list[ResumeEntity]] = {user_id: [] for user_id in user_ids}
    for resume in result.scalars().unique().all():
        grouped.setdefault(resume.user_id, []).append(resume)
    return grouped


async def _load_sessions(db: AsyncSession, user_ids: list[int]) -> dict[int, list[InterviewSessionEntity]]:
    result = await db.execute(select(InterviewSessionEntity).where(InterviewSessionEntity.user_id.in_(user_ids)))
    grouped: dict[int, list[InterviewSessionEntity]] = {user_id: [] for user_id in user_ids}
    for session in result.scalars().unique().all():
        grouped.setdefault(session.user_id, []).append(session)
    return grouped


async def _load_low_score_counts(db: AsyncSession, user_ids: list[int]) -> dict[int, int]:
    result = await db.execute(
        select(InterviewSessionEntity.user_id, func.count(InterviewAnswerEntity.id))
        .join(InterviewAnswerEntity, InterviewAnswerEntity.session_id == InterviewSessionEntity.id)
        .where(
            InterviewSessionEntity.user_id.in_(user_ids),
            InterviewAnswerEntity.score.isnot(None),
            InterviewAnswerEntity.score < 60,
        )
        .group_by(InterviewSessionEntity.user_id)
    )
    return {user_id: int(count) for user_id, count in result.all()}


def _build_member_training(
    member: OrganizationMemberEntity,
    user: UserEntity,
    resumes: list[ResumeEntity],
    sessions: list[InterviewSessionEntity],
    low_scores: dict[int, int],
) -> OrganizationMemberTrainingDTO:
    latest_resume_score = _latest_resume_score(resumes)
    analyzed_resume_count = sum(1 for resume in resumes if resume.analyses)
    evaluated_interview_count = sum(1 for session in sessions if session.status == SessionStatus.EVALUATED)
    retry_sessions = [session for session in sessions if session.difficulty == "retry"]
    completed_retry_session_count = sum(
        1 for session in retry_sessions if session.status in {SessionStatus.COMPLETED, SessionStatus.EVALUATED}
    )
    low_score_question_count = low_scores.get(user.id, 0)
    last_activity_at = _latest_activity_at(resumes, sessions)
    readiness_score = _readiness_score(
        latest_resume_score=latest_resume_score,
        analyzed_resume_count=analyzed_resume_count,
        evaluated_interview_count=evaluated_interview_count,
        completed_retry_session_count=completed_retry_session_count,
        low_score_question_count=low_score_question_count,
    )

    return OrganizationMemberTrainingDTO(
        user_id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        note=member.note,
        resume_count=len(resumes),
        analyzed_resume_count=analyzed_resume_count,
        latest_resume_score=latest_resume_score,
        interview_count=len(sessions),
        evaluated_interview_count=evaluated_interview_count,
        retry_session_count=len(retry_sessions),
        completed_retry_session_count=completed_retry_session_count,
        low_score_question_count=low_score_question_count,
        readiness_score=readiness_score,
        next_action=_next_action(
            resume_count=len(resumes),
            analyzed_resume_count=analyzed_resume_count,
            interview_count=len(sessions),
            retry_session_count=len(retry_sessions),
            low_score_question_count=low_score_question_count,
        ),
        last_activity_at=last_activity_at,
    )


def _latest_resume_score(resumes: list[ResumeEntity]) -> int | None:
    latest_score = None
    latest_time = None
    for resume in resumes:
        for analysis in resume.analyses:
            if latest_time is None or analysis.analyzed_at > latest_time:
                latest_time = analysis.analyzed_at
                latest_score = analysis.overall_score
    return latest_score


def _latest_activity_at(
    resumes: list[ResumeEntity],
    sessions: list[InterviewSessionEntity],
) -> datetime | None:
    candidates: list[datetime] = []
    for resume in resumes:
        if resume.uploaded_at:
            candidates.append(resume.uploaded_at)
        if resume.last_accessed_at:
            candidates.append(resume.last_accessed_at)
    for session in sessions:
        if session.created_at:
            candidates.append(session.created_at)
        if session.completed_at:
            candidates.append(session.completed_at)
    return max(candidates, key=lambda value: value.timestamp()) if candidates else None


def _readiness_score(
    latest_resume_score: int | None,
    analyzed_resume_count: int,
    evaluated_interview_count: int,
    completed_retry_session_count: int,
    low_score_question_count: int,
) -> int:
    score = 0
    if analyzed_resume_count > 0:
        score += 20
    if latest_resume_score is not None:
        score += min(35, round(latest_resume_score * 0.35))
    if evaluated_interview_count > 0:
        score += 25
    if completed_retry_session_count > 0:
        score += 15
    if low_score_question_count == 0 and evaluated_interview_count > 0:
        score += 5
    return min(100, score)


def _next_action(
    resume_count: int,
    analyzed_resume_count: int,
    interview_count: int,
    retry_session_count: int,
    low_score_question_count: int,
) -> str:
    if resume_count == 0:
        return "上传简历"
    if analyzed_resume_count == 0:
        return "完成简历分析"
    if interview_count == 0:
        return "安排模拟面试"
    if low_score_question_count > 0 and retry_session_count == 0:
        return "低分题同题再练"
    if low_score_question_count > 0:
        return "跟进低分题复盘"
    return "保持训练节奏"


def _average_score(scores: list[int]) -> int:
    if not scores:
        return 0
    return round(sum(scores) / len(scores))


def _to_member_dto(member: OrganizationMemberEntity, user: UserEntity) -> OrganizationMemberDTO:
    return OrganizationMemberDTO(
        id=member.id,
        organization_id=member.organization_id,
        user_id=member.user_id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        note=member.note,
        joined_at=member.joined_at,
    )
