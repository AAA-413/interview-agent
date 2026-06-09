from app.modules.interview.question_service import interview_question_service
from app.modules.interview.schemas import HistoricalQuestion, InterviewQuestionDTO, SkillCategoryDTO, SkillDTO
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


def test_historical_section_includes_recent_original_questions_for_dedup():
    section = interview_question_service._build_historical_section(
        [
            HistoricalQuestion(
                question="请说明 Redis 缓存穿透的处理方案，以及布隆过滤器可能带来的误判风险。",
                type="REDIS",
                topic_summary="Redis 缓存穿透",
            )
        ]
    )

    assert "最近原题" in section
    assert "Redis 缓存穿透的处理方案" in section


def test_fallback_questions_rotate_by_generation_seed():
    skill = SkillDTO(
        id="backend",
        name="后端",
        categories=[
            SkillCategoryDTO(key="REDIS", label="Redis"),
            SkillCategoryDTO(key="MYSQL", label="MySQL"),
        ],
    )

    first = interview_question_service._generate_fallback_questions(skill, 2, "seed-a")
    second = interview_question_service._generate_fallback_questions(skill, 2, "seed-b")

    assert [item.question for item in first] != [item.question for item in second]


def test_diversify_questions_filters_history_duplicates_and_fills_count():
    skill = SkillDTO(
        id="backend",
        name="后端",
        categories=[
            SkillCategoryDTO(key="REDIS", label="Redis"),
            SkillCategoryDTO(key="MYSQL", label="MySQL"),
        ],
    )
    historical = [
        HistoricalQuestion(
            question="请说明 Redis 缓存穿透的处理方案，以及布隆过滤器可能带来的误判风险。",
            type="REDIS",
            topic_summary="Redis 缓存穿透",
        )
    ]
    questions = [
        InterviewQuestionDTO(
            question_index=0,
            question="请说明 Redis 缓存穿透的处理方案，以及布隆过滤器可能带来的误判风险。",
            type="REDIS",
        ),
        InterviewQuestionDTO(question_index=1, question="请说明 MySQL 索引失效的常见场景。", type="MYSQL"),
    ]

    result = interview_question_service._diversify_questions(questions, historical, skill, 2, "seed-a")

    assert len(result) == 2
    assert [item.question_index for item in result] == [0, 1]
    assert all(item.question != historical[0].question for item in result)
