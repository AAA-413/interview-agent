import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.interview.diagnosis_schemas import InterviewDiagnosisDTO, InterviewDiagnosisRequest
from app.modules.interview.diagnosis_service import interview_diagnosis_service
from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service
from app.modules.interview.dynamic_service import dynamic_interview_service
from app.modules.interview.history_service import interview_history_service
from app.modules.interview.jd_parse_service import jd_parse_service
from app.modules.interview.persistence_service import interview_persistence_service
from app.modules.interview.project_drill_schemas import (
    ProjectDrillDTO,
    ProjectDrillRequest,
)
from app.modules.interview.project_drill_service import project_drill_service
from app.modules.interview.schemas import (
    CreateInterviewRequest,
    DynamicInterviewCreateRequest,
    DynamicInterviewCreateResponse,
    DynamicReportDTO,
    DynamicSessionDetailDTO,
    DynamicTopicRagInsightDTO,
    DynamicTurnAnswerResponse,
    InterviewDetailDTO,
    InterviewReportDTO,
    InterviewSessionDTO,
    JDParseRequest,
    RetryAnswerComparisonDTO,
    RetryQuestionRequest,
    SessionListItemDTO,
    StructuredJD,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    SubmitDynamicTurnAnswerRequest,
    VoiceTranscriptionDTO,
)
from app.modules.interview.session_service import interview_session_service
from app.modules.interview.voice_service import voice_transcription_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/jd/parse", response_model=Result[StructuredJD])
async def parse_jd(
    request: JDParseRequest,
    user_id: int = Depends(get_current_user_id),
):
    _ = user_id
    structured_jd = jd_parse_service.parse(request.jd_text, request.target_role, request.skill_id)
    return Result.success(structured_jd)


@router.post("/dynamic-sessions", response_model=Result[DynamicInterviewCreateResponse])
async def create_dynamic_session(
    request: DynamicInterviewCreateRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    session = await dynamic_interview_service.create_session(db, request, user_id)
    return Result.success(session)


@router.get("/dynamic-sessions/{session_id}", response_model=Result[DynamicSessionDetailDTO])
async def get_dynamic_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    detail = await dynamic_interview_service.get_session_detail(db, session_id, user_id)
    return Result.success(detail)


@router.post(
    "/dynamic-sessions/{session_id}/turns/{turn_id}/answer",
    response_model=Result[DynamicTurnAnswerResponse],
)
async def submit_dynamic_turn_answer(
    session_id: str,
    turn_id: int,
    request: SubmitDynamicTurnAnswerRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    response = await dynamic_interview_service.submit_turn_answer(db, session_id, turn_id, request, user_id)
    return Result.success(response)


@router.post("/dynamic-sessions/{session_id}/complete", response_model=Result[DynamicReportDTO])
async def complete_dynamic_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    report = await dynamic_interview_service.complete_session(db, session_id, user_id)
    return Result.success(report)


@router.get("/dynamic-sessions/{session_id}/report", response_model=Result[DynamicReportDTO])
async def get_dynamic_report(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    report = await dynamic_interview_service.get_report(db, session_id, user_id)
    return Result.success(report)


@router.get(
    "/dynamic-sessions/{session_id}/topics/{topic_id}/rag-insight",
    response_model=Result[DynamicTopicRagInsightDTO],
)
async def get_dynamic_topic_rag_insight(
    session_id: str,
    topic_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    insight = await dynamic_interview_service.get_topic_rag_insight(db, session_id, topic_id, user_id)
    return Result.success(insight)


@router.post(
    "/dynamic-sessions/{session_id}/topics/{topic_id}/retry",
    response_model=Result[DynamicInterviewCreateResponse],
)
async def create_dynamic_topic_retry_session(
    session_id: str,
    topic_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    session = await dynamic_interview_service.create_topic_retry_session(db, session_id, topic_id, user_id)
    return Result.success(session)


@router.get("/user-topic-profile", response_model=Result[dict])
async def get_user_topic_profile(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    profile = await dynamic_interview_persistence_service.get_user_topic_profile(db, user_id)
    return Result.success(profile)


@router.post("/diagnosis", response_model=Result[InterviewDiagnosisDTO])
async def create_diagnosis(
    request: InterviewDiagnosisRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    diagnosis = await interview_diagnosis_service.diagnose(db, request, user_id)
    return Result.success(diagnosis)


@router.post("/project-drill", response_model=Result[ProjectDrillDTO])
async def create_project_drill(
    request: ProjectDrillRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    drill = await project_drill_service.create_drill(db, request, user_id)
    return Result.success(drill)


@router.get("/sessions", response_model=Result[list[SessionListItemDTO]])
async def list_sessions(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entities = await interview_persistence_service.find_all(db, user_id=user_id)
    items = [interview_persistence_service.to_session_list_item(e) for e in entities]
    return Result.success(items)


@router.post("/sessions", response_model=Result[InterviewSessionDTO])
async def create_session(
    request: CreateInterviewRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        "收到创建面试会话请求: skill_id=%s, difficulty=%s, question_count=%d",
        request.skill_id,
        request.difficulty,
        request.question_count,
    )
    session = await interview_session_service.create_session(db, request, user_id)
    return Result.success(session)


@router.post("/sessions/{session_id}/retry", response_model=Result[InterviewSessionDTO])
async def create_retry_session(
    session_id: str,
    request: RetryQuestionRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    session = await interview_session_service.create_retry_session(db, session_id, request.question_index, user_id)
    return Result.success(session)


@router.get("/sessions/{session_id}/retry-comparison", response_model=Result[RetryAnswerComparisonDTO])
async def get_retry_comparison(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    comparison = await interview_session_service.get_retry_comparison(db, session_id, user_id)
    return Result.success(comparison)


@router.post("/voice/transcribe", response_model=Result[VoiceTranscriptionDTO])
async def transcribe_voice(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
):
    _ = user_id
    transcription = await voice_transcription_service.transcribe(file)
    return Result.success(transcription)


@router.get("/sessions/{session_id}", response_model=Result[InterviewSessionDTO])
async def get_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    session = await interview_session_service.get_session(db, session_id, user_id)
    return Result.success(session)


@router.get("/sessions/{session_id}/question", response_model=Result[dict])
async def get_current_question(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await interview_session_service.get_current_question(db, session_id, user_id)
    return Result.success(result)


@router.post("/sessions/{session_id}/answers", response_model=Result[SubmitAnswerResponse])
async def submit_answer(
    session_id: str,
    request: SubmitAnswerRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    response = await interview_session_service.submit_answer(db, session_id, request, user_id)
    return Result.success(response)


@router.put("/sessions/{session_id}/answers", response_model=Result[None])
async def save_answer(
    session_id: str,
    request: SubmitAnswerRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await interview_session_service.save_answer(db, session_id, request, user_id)
    return Result.success(None)


@router.post("/sessions/{session_id}/complete", response_model=Result[None])
async def complete_interview(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await interview_session_service.complete_interview(db, session_id, user_id)
    return Result.success(None)


@router.get("/sessions/{session_id}/report", response_model=Result[InterviewReportDTO])
async def get_report(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    report = await interview_session_service.generate_report(db, session_id, user_id)
    return Result.success(report)


@router.get("/sessions/unfinished/{resume_id}", response_model=Result[InterviewSessionDTO])
async def find_unfinished_session(
    resume_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    session = await interview_session_service._find_unfinished_session(db, resume_id, user_id)
    if session is None:
        from app.common.error_code import ErrorCode
        from app.common.exception import BusinessException

        raise BusinessException(ErrorCode.INTERVIEW_SESSION_NOT_FOUND, "未找到未完成的面试会话")
    return Result.success(session)


@router.get("/sessions/{session_id}/details", response_model=Result[InterviewDetailDTO])
async def get_interview_detail(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    detail = await interview_history_service.get_interview_detail(db, session_id, user_id)
    return Result.success(detail)


@router.get("/sessions/{session_id}/export")
async def export_interview_pdf(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    pdf_bytes = await interview_history_service.export_interview_pdf(db, session_id, user_id)
    filename = f"interview-report-{session_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.delete("/sessions/{session_id}", response_model=Result[None])
async def delete_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await interview_persistence_service.delete_session(db, session_id, user_id)
    return Result.success(None)
