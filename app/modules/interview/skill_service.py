import logging
import re
from pathlib import Path

import yaml

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.common.prompt_utils import load_prompt
from app.modules.interview.schemas import CategoryDTO, SkillCategoryDTO, SkillDTO

logger = logging.getLogger(__name__)

CUSTOM_SKILL_ID = "custom"
MIN_JD_LENGTH = 50

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "skills"
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

_FRONT_MATTER_PATTERN = re.compile(r"(?s)^---\s*\n(.*?)\n---\s*\n?(.*)$")


class InterviewSkillService:
    def __init__(self):
        self._preset_registry: dict[str, dict] = {}
        self._category_ref_index: dict[str, dict] = {}
        self._load_preset_skills()

    def _load_preset_skills(self) -> None:
        if not _SKILLS_DIR.exists():
            logger.warning("Skills 目录不存在: %s", _SKILLS_DIR)
            return

        for skill_dir in _SKILLS_DIR.iterdir():
            if not skill_dir.is_dir() or skill_dir.name == "_shared":
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            skill_id = skill_dir.name
            definition = self._parse_skill_definition(skill_id, skill_md)
            if definition:
                self._preset_registry[skill_id] = definition
                logger.info("加载预设 Skill: %s (%s)", skill_id, definition.get("name", ""))

        self._build_category_ref_index()
        logger.info("共加载 %d 个预设 Skill", len(self._preset_registry))

    def _parse_skill_definition(self, skill_id: str, skill_md: Path) -> dict | None:
        try:
            content = skill_md.read_text(encoding="utf-8")
            match = _FRONT_MATTER_PATTERN.match(content)
            if not match:
                logger.warning("Skill 文件格式错误: %s", skill_md)
                return None

            front_matter_str = match.group(1)
            persona = match.group(2).strip() if match.group(2) else ""

            front_matter = yaml.safe_load(front_matter_str) or {}
            name = front_matter.get("name", "")
            description = front_matter.get("description", "")

            meta = self._load_skill_meta(skill_id)
            display_name = meta.get("displayName", name)
            display = meta.get("display", {})
            categories = meta.get("categories", [])

            if not name:
                logger.warning("跳过无效 Skill（缺少 name）: %s", skill_id)
                return None

            return {
                "name": name,
                "description": description,
                "persona": persona,
                "display_name": display_name,
                "display": display,
                "categories": categories,
            }
        except Exception as e:
            logger.error("解析 Skill 文件失败: %s, error=%s", skill_md, e)
            return None

    def _load_skill_meta(self, skill_id: str) -> dict:
        meta_path = _SKILLS_DIR / skill_id / "skill.meta.yml"
        if not meta_path.exists():
            return {}
        try:
            content = meta_path.read_text(encoding="utf-8")
            return yaml.safe_load(content) or {}
        except Exception as e:
            logger.warning("读取 skill meta 失败: %s, error=%s", meta_path, e)
            return {}

    def _build_category_ref_index(self) -> None:
        self._category_ref_index.clear()
        for skill_id, definition in self._preset_registry.items():
            for cat in definition.get("categories", []):
                key = cat.get("key")
                ref = cat.get("ref")
                if key and ref:
                    self._category_ref_index[key] = {
                        "ref": ref,
                        "shared": cat.get("shared", False),
                        "source_skill_id": skill_id,
                    }
        logger.info("构建 category→reference 映射: %d 个条目", len(self._category_ref_index))

    def get_all_skills(self) -> list[SkillDTO]:
        result = []
        for skill_id, definition in self._preset_registry.items():
            result.append(self._to_skill_dto(skill_id, definition))
        return result

    def get_skill(self, skill_id: str) -> SkillDTO:
        definition = self._preset_registry.get(skill_id)
        if definition:
            return self._to_skill_dto(skill_id, definition)
        raise BusinessException(ErrorCode.BAD_REQUEST, f"未找到面试主题: {skill_id}")

    def build_custom_skill(self, custom_categories: list[CategoryDTO], jd_text: str) -> SkillDTO:
        categories = []
        for cat in custom_categories:
            ref_mapping = self._category_ref_index.get(cat.key)
            if ref_mapping:
                categories.append(
                    SkillCategoryDTO(
                        key=cat.key,
                        label=cat.label,
                        priority=cat.priority,
                        ref=ref_mapping["ref"],
                        shared=ref_mapping["shared"],
                    )
                )
            else:
                categories.append(
                    SkillCategoryDTO(
                        key=cat.key,
                        label=cat.label,
                        priority=cat.priority,
                        ref=cat.ref,
                        shared=cat.shared or False,
                    )
                )

        matched_count = sum(1 for c in categories if c.ref)
        logger.info("构建自定义 Skill: %d 个分类, %d 个匹配到参考文件", len(categories), matched_count)

        return SkillDTO(
            id=CUSTOM_SKILL_ID,
            name="自定义面试（JD 解析）",
            description="基于职位描述提取的面试方向",
            categories=categories,
            is_preset=False,
            source_jd=jd_text,
        )

    def calculate_allocation(self, categories: list[SkillCategoryDTO], total_questions: int) -> dict[str, int]:
        always_one_cats = [c for c in categories if c.priority == "ALWAYS_ONE"]
        core_cats = [c for c in categories if c.priority == "CORE"]
        normal_cats = [c for c in categories if c.priority not in ("ALWAYS_ONE", "CORE")]

        allocation: dict[str, int] = {}
        remaining = total_questions

        for cat in always_one_cats:
            if remaining > 0:
                allocation[cat.key] = 1
                remaining -= 1

        for cat in core_cats:
            if remaining > 0:
                allocation[cat.key] = 1
                remaining -= 1

        for cat in normal_cats:
            if remaining > 0:
                allocation[cat.key] = 1
                remaining -= 1

        while remaining > 0:
            for cat in core_cats:
                if remaining <= 0:
                    break
                allocation[cat.key] = allocation.get(cat.key, 0) + 1
                remaining -= 1
            for cat in normal_cats:
                if remaining <= 0:
                    break
                allocation[cat.key] = allocation.get(cat.key, 0) + 1
                remaining -= 1
            if not core_cats and not normal_cats:
                break

        for cat in core_cats:
            allocation.setdefault(cat.key, 0)
        for cat in normal_cats:
            allocation.setdefault(cat.key, 0)

        return allocation

    def build_allocation_description(self, allocation: dict[str, int], categories: list[SkillCategoryDTO]) -> str:
        lines = []
        for cat in categories:
            count = allocation.get(cat.key, 0)
            if count > 0:
                lines.append(f"| {cat.label} | {count} 题 | {cat.priority} |")
        return "\n".join(lines)

    def build_reference_section(self, skill: SkillDTO, allocation: dict[str, int]) -> str:
        return self._build_reference_section_internal(
            skill, lambda c: allocation.get(c.key, 0) > 0, 12000
        )

    def build_evaluation_reference_section(self, skill_id: str) -> str:
        skill = self.get_skill(skill_id)
        return self._build_reference_section_internal(skill, lambda _: True, 6000)

    def build_evaluation_reference_section_safe(self, skill_id: str | None) -> str:
        if not skill_id:
            return ""
        try:
            return self.build_evaluation_reference_section(skill_id)
        except Exception as e:
            logger.warning("加载评估参考基线失败: skillId=%s, error=%s", skill_id, e)
            return ""

    def _build_reference_section_internal(
        self, skill: SkillDTO, category_filter, max_chars: int
    ) -> str:
        sections = []
        for category in skill.categories:
            if not category_filter(category):
                continue
            if not category.ref:
                continue

            effective_skill_id = skill.id
            if skill.id == CUSTOM_SKILL_ID and not category.shared and category.ref:
                mapping = self._category_ref_index.get(category.key)
                if mapping:
                    effective_skill_id = mapping["source_skill_id"]

            reference_content = self._load_reference_content(effective_skill_id, category.ref, category.shared)
            if not reference_content:
                continue

            sections.append(f"### {category.label} ({category.key})\n{reference_content}")

            total = sum(len(s) for s in sections)
            if total >= max_chars:
                break

        result = "\n\n".join(sections)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n...（references 已截断）"
        return result if result else "未配置 references。"

    def _load_reference_content(self, skill_id: str, ref: str, shared: bool) -> str:
        if skill_id == CUSTOM_SKILL_ID:
            for sid, _ in self._preset_registry.items():
                path = _SKILLS_DIR / sid / ref
                if path.exists():
                    try:
                        return path.read_text(encoding="utf-8")[:3000]
                    except Exception:
                        continue
            return ""

        if shared:
            for candidate in [_SKILLS_DIR / "_shared" / "references" / ref, _SKILLS_DIR / "_shared" / ref]:
                if candidate.exists():
                    try:
                        return candidate.read_text(encoding="utf-8")[:3000]
                    except Exception:
                        pass

        path = _SKILLS_DIR / skill_id / ref
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")[:3000]
            except Exception:
                pass
        return ""

    async def parse_jd(self, jd_text: str) -> list[CategoryDTO]:
        if not jd_text or len(jd_text) < MIN_JD_LENGTH:
            raise BusinessException(ErrorCode.BAD_REQUEST, f"JD 内容太少（至少 {MIN_JD_LENGTH} 字），请补充后重试")

        logger.info("开始解析 JD，长度: %d", len(jd_text))

        try:
            from app.common.ai.llm_provider import llm_registry
            from app.common.ai.structured_output import structured_output_invoker
            from app.common.error_code import ErrorCode
            from pydantic import BaseModel

            class _CategoryItemDTO(BaseModel):
                key: str
                label: str
                priority: str = "NORMAL"
                ref: str | None = None
                shared: bool | None = None

            class _CategoryListDTO(BaseModel):
                categories: list[_CategoryItemDTO] | None = None

            chat_model = llm_registry.get_chat_model(None)

            jd_system_prompt = load_prompt(_PROMPTS_DIR, "jd-parse-system.md")

            dto = await structured_output_invoker.invoke(
                chat_model=chat_model,
                system_prompt=jd_system_prompt,
                user_prompt=f"职位描述：\n{jd_text}",
                output_model=_CategoryListDTO,
                error_code=ErrorCode.AI_SERVICE_ERROR,
                error_prefix="JD 解析失败：",
                log_context="JD 解析",
            )

            if not dto or not dto.categories:
                raise BusinessException(ErrorCode.AI_SERVICE_ERROR, "JD 解析结果为空，请重试")

            result = [
                CategoryDTO(key=c.key, label=c.label, priority=c.priority, ref=c.ref, shared=c.shared)
                for c in dto.categories
            ]

            ref_matched = sum(1 for c in result if c.ref)
            logger.info("JD 解析完成: %d 个方向, %d 个匹配到参考文件", len(result), ref_matched)
            return result
        except BusinessException:
            raise
        except Exception as e:
            logger.error("JD 解析失败: %s", e)
            raise BusinessException(ErrorCode.AI_SERVICE_ERROR, "JD 解析失败，请重试或选择预设主题")

    def _to_skill_dto(self, skill_id: str, definition: dict) -> SkillDTO:
        categories = []
        for cat in definition.get("categories", []):
            categories.append(
                SkillCategoryDTO(
                    key=cat.get("key", ""),
                    label=cat.get("label", ""),
                    priority=cat.get("priority", "NORMAL"),
                    ref=cat.get("ref"),
                    shared=cat.get("shared", False),
                )
            )

        return SkillDTO(
            id=skill_id,
            name=definition.get("name", ""),
            description=definition.get("description"),
            categories=categories,
            is_preset=True,
            source_jd=None,
            display_name=definition.get("display_name"),
            persona=definition.get("persona"),
        )


interview_skill_service = InterviewSkillService()
