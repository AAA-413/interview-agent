from app.modules.interview.question_service import interview_question_service
from app.modules.interview.skill_service import interview_skill_service


def test_preset_interview_skill_can_be_augmented_with_jd_without_mutating_registry():
    skill_id = interview_skill_service.get_all_skills()[0].id
    jd_text = "负责高并发订单系统，要求熟悉 Redis 缓存、MySQL 索引优化、服务限流和故障排查。"

    skill_with_jd = interview_question_service._resolve_skill(skill_id, None, f"  {jd_text}  ")
    original_skill = interview_question_service._resolve_skill(skill_id, None, None)

    assert skill_with_jd.id == skill_id
    assert skill_with_jd.source_jd == jd_text
    assert original_skill.source_jd != jd_text


def test_frontend_difficulty_values_map_to_backend_descriptions():
    assert "0-1年" in interview_question_service._resolve_difficulty_description("EASY")
    assert "1-3年" in interview_question_service._resolve_difficulty_description("MEDIUM")
    assert "3年+" in interview_question_service._resolve_difficulty_description("HARD")
