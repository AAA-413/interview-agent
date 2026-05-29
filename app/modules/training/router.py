from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.training.schemas import (
    PersonalTrainingPlanDTO,
    ScoreCalibrationDTO,
    TrainingTaskProgressDTO,
    TrainingTrendDTO,
    UpdateTrainingTaskProgressRequest,
)
from app.modules.training.service import training_service

router = APIRouter()


@router.get("/calibration", response_model=Result[ScoreCalibrationDTO])
async def get_score_calibration(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    calibration = await training_service.get_score_calibration(db, user_id)
    return Result.success(calibration)


@router.get("/plan", response_model=Result[PersonalTrainingPlanDTO])
async def get_personal_training_plan(
    days: int = Query(default=7, ge=1, le=14),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    plan = await training_service.get_personal_training_plan(db, user_id, days)
    return Result.success(plan)


@router.put("/tasks/progress", response_model=Result[TrainingTaskProgressDTO])
async def update_training_task_progress(
    request: UpdateTrainingTaskProgressRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    progress = await training_service.update_task_progress(db, user_id, request)
    return Result.success(progress)


@router.get("/trends", response_model=Result[TrainingTrendDTO])
async def get_training_trend(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    trend = await training_service.get_training_trend(db, user_id)
    return Result.success(trend)
