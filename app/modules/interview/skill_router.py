import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.common.result import Result
from app.modules.interview.schemas import CategoryDTO, SkillDTO
from app.modules.interview.skill_service import interview_skill_service

logger = logging.getLogger(__name__)

router = APIRouter()


class ParseJdRequest(BaseModel):
    jd_text: str = Field(..., min_length=50)


@router.get("", response_model=Result[list[SkillDTO]])
async def list_skills():
    skills = interview_skill_service.get_all_skills()
    return Result.success(skills)


@router.get("/{skill_id}", response_model=Result[SkillDTO])
async def get_skill(skill_id: str):
    skill = interview_skill_service.get_skill(skill_id)
    return Result.success(skill)


@router.post("/parse-jd", response_model=Result[list[CategoryDTO]])
async def parse_jd(request: ParseJdRequest):
    categories = await interview_skill_service.parse_jd(request.jd_text)
    return Result.success(categories)
