from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.interview.project_drill_schemas import (
    ProjectCandidateDTO,
    ProjectDrillDTO,
    ProjectDrillQuestionDTO,
    ProjectDrillRequest,
)
from app.modules.interview.schemas import InterviewQuestionDTO, KeyPoint
from app.modules.resume.history_service import resume_history_service
from app.modules.resume.schemas import ProjectInfo, ResumeDetailDTO, ResumeProfile


class ProjectDrillService:
    async def create_drill(
        self,
        db: AsyncSession,
        request: ProjectDrillRequest,
        user_id: int,
    ) -> ProjectDrillDTO:
        resume_detail = await resume_history_service.get_resume_detail(db, request.resume_id, user_id)
        return self.build_drill(request, resume_detail)

    def build_drill(self, request: ProjectDrillRequest, resume_detail: ResumeDetailDTO) -> ProjectDrillDTO:
        target_role = request.target_role.strip()
        target_company = request.target_company.strip() if request.target_company else None
        level = request.level.strip() if request.level else "校招/转岗"
        profile = self._latest_profile(resume_detail)
        projects = profile.projects if profile else []
        selected_project = self._select_project(projects, request.project_name)
        candidates = self._project_candidates(projects, target_role)
        selected_candidate = self._candidate_from_project(selected_project, target_role)

        if not candidates:
            candidates = [selected_candidate]

        return ProjectDrillDTO(
            resume_id=resume_detail.id,
            resume_filename=resume_detail.filename,
            target_role=target_role,
            target_company=target_company,
            level=level,
            selected_project=selected_candidate,
            project_candidates=candidates[:5],
            risk_summary=self._risk_summary(selected_project, target_role, bool(request.jd_text)),
            warmup_prompt=self._warmup_prompt(selected_project, target_role, target_company),
            questions=self._build_questions(selected_project, target_role, request.jd_text or ""),
            practice_checklist=self._practice_checklist(selected_project, target_role),
        )

    @staticmethod
    def _latest_profile(resume_detail: ResumeDetailDTO) -> ResumeProfile | None:
        if not resume_detail.analyses:
            return None
        latest = max(resume_detail.analyses, key=lambda item: item.analyzed_at)
        return latest.profile

    @staticmethod
    def _select_project(projects: list[ProjectInfo], project_name: str | None) -> ProjectInfo | None:
        if not projects:
            return None
        if project_name:
            normalized = project_name.strip().lower()
            for project in projects:
                if project.name.strip().lower() == normalized:
                    return project
        return projects[0]

    def _project_candidates(self, projects: list[ProjectInfo], target_role: str) -> list[ProjectCandidateDTO]:
        return [self._candidate_from_project(project, target_role) for project in projects]

    @staticmethod
    def _candidate_from_project(project: ProjectInfo | None, target_role: str) -> ProjectCandidateDTO:
        if project is None:
            return ProjectCandidateDTO(
                name="待补充核心项目",
                role="候选人",
                tech_stack=[],
                reason=f"当前简历没有识别到明确项目，先按“{target_role}”补一个能证明岗位能力的项目样本。",
            )

        tech_text = "、".join(project.tech_stack[:3]) if project.tech_stack else "项目技术栈"
        return ProjectCandidateDTO(
            name=project.name or "未命名项目",
            role=project.role or None,
            tech_stack=project.tech_stack,
            reason=f"该项目可以用 {tech_text} 证明你的岗位匹配度，适合作为首轮深挖主项目。",
        )

    @staticmethod
    def _risk_summary(project: ProjectInfo | None, target_role: str, has_jd: bool) -> str:
        if project is None:
            return "当前最大风险不是答题，而是缺少可被追问的项目证据。先补一个能证明岗位能力的项目，再进入模拟面试。"
        if not has_jd:
            return "当前可以做项目追问训练，但缺少 JD 对齐。建议补充目标 JD 后，把项目亮点改成岗位关键词证据。"
        return f"围绕“{target_role}”面试，最容易被追问的是个人贡献、技术取舍、结果指标和项目真实性。"

    @staticmethod
    def _warmup_prompt(project: ProjectInfo | None, target_role: str, target_company: str | None) -> str:
        project_name = project.name if project else "你的核心项目"
        company_text = target_company or "目标公司"
        return f"请用 2 分钟介绍{project_name}，重点说明它为什么能证明你适合{company_text}的{target_role}。"

    def _build_questions(
        self,
        project: ProjectInfo | None,
        target_role: str,
        jd_text: str,
    ) -> list[ProjectDrillQuestionDTO]:
        project_name = project.name if project else "你的核心项目"
        tech_stack = project.tech_stack if project else []
        primary_tech = tech_stack[0] if tech_stack else self._primary_role_topic(target_role, jd_text)

        return [
            ProjectDrillQuestionDTO(
                category="项目概述",
                question=f"请用 2 分钟介绍{project_name}，只保留最能证明你适合{target_role}的内容。",
                risk="开场讲太散，面试官听不出项目价值和个人贡献。",
                answer_framework=[
                    "一句话说明项目解决了什么问题",
                    "说明你的角色和负责模块",
                    "讲一个最关键的技术动作",
                    "用指标或反馈证明结果",
                ],
                strong_answer_signals=["结论先行", "个人贡献清楚", "结果可验证"],
                red_flags=["只讲背景不讲自己", "没有结果", "超过 3 分钟仍没有重点"],
            ),
            ProjectDrillQuestionDTO(
                category="个人贡献",
                question=f"{project_name}里哪些部分是你独立完成或主导推进的？如何证明不是只参与了一下？",
                risk="贡献边界不清，校招/转岗面试很容易被判断为项目含金量不足。",
                answer_framework=[
                    "列出你负责的模块边界",
                    "说明你做过的关键决策",
                    "补充遇到的阻塞和解决动作",
                    "用提交、文档、指标或复盘证明贡献",
                ],
                strong_answer_signals=["职责边界明确", "有独立决策", "能讲清困难和取舍"],
                red_flags=["我们团队做了", "我主要学习了", "没有具体动作"],
            ),
            ProjectDrillQuestionDTO(
                category="技术取舍",
                question=f"为什么在{project_name}里选择 {primary_tech}？如果重新做，你会换方案吗？",
                risk="只会说用了什么，不会解释为什么这么用。",
                answer_framework=[
                    "先说当时的约束条件",
                    "列 1 到 2 个替代方案",
                    "比较成本、复杂度、性能或团队熟悉度",
                    "说明现在复盘后的改进方案",
                ],
                strong_answer_signals=["能讲约束", "能比较替代方案", "能复盘改进"],
                red_flags=["因为大家都这么用", "没有考虑过替代方案", "只背技术名词"],
            ),
            ProjectDrillQuestionDTO(
                category="结果指标",
                question=f"{project_name}上线或完成后，如何证明它真的有效？有没有量化指标？",
                risk="没有结果指标时，项目容易被认为只是课程作业或练手 Demo。",
                answer_framework=[
                    "给出业务指标或用户反馈",
                    "给出技术指标，如耗时、吞吐、错误率、准确率",
                    "说明指标采集方式",
                    "补充没有量化时的替代验证方式",
                ],
                strong_answer_signals=["有前后对比", "有验证方法", "知道指标边界"],
                red_flags=["感觉效果不错", "没有验证", "指标和项目目标无关"],
            ),
            ProjectDrillQuestionDTO(
                category="异常与边界",
                question=f"{project_name}在数据异常、并发变高或第三方服务失败时会发生什么？你做过哪些兜底？",
                risk="项目只讲正常流程，缺少工程可靠性意识。",
                answer_framework=[
                    "选一个最可能失败的链路",
                    "说明失败后的用户影响",
                    "讲清检测、重试、降级或人工兜底",
                    "补充后续监控和告警",
                ],
                strong_answer_signals=["能画失败链路", "有兜底意识", "能说明用户影响"],
                red_flags=["没考虑过异常", "失败就重试", "没有监控"],
            ),
            ProjectDrillQuestionDTO(
                category="岗位对齐",
                question=f"如果面试官问：这个项目和{target_role}岗位有什么关系？你怎么回答？",
                risk="项目经历和目标岗位脱节，尤其转岗同学会被质疑迁移能力。",
                answer_framework=[
                    "提炼 3 个岗位关键词",
                    "每个关键词对应一个项目证据",
                    "说明你可以迁移到目标岗位的能力",
                    "补一个正在补强的短板",
                ],
                strong_answer_signals=["岗位关键词明确", "项目证据对应", "能承认并补强短板"],
                red_flags=["只说感兴趣", "泛泛说学习能力强", "没有证据"],
            ),
        ]

    @staticmethod
    def _primary_role_topic(target_role: str, jd_text: str) -> str:
        text = f"{target_role} {jd_text}".lower()
        if any(keyword in text for keyword in ["ai", "llm", "rag", "算法", "机器学习"]):
            return "RAG/模型应用链路"
        if any(keyword in text for keyword in ["前端", "react", "vue", "javascript", "typescript"]):
            return "前端框架和工程化方案"
        if any(keyword in text for keyword in ["java", "后端", "spring", "微服务"]):
            return "后端服务设计"
        return "核心技术方案"

    @staticmethod
    def _practice_checklist(project: ProjectInfo | None, target_role: str) -> list[str]:
        project_name = project.name if project else "核心项目"
        return [
            f"把{project_name}压缩成 2 分钟版本，录音后检查是否结论先行。",
            "补齐个人贡献、技术取舍、结果指标、失败边界四类证据。",
            f"写出 3 条“为什么适合{target_role}”的项目证据。",
            "每道追问先口答一遍，再改成 80 分结构化回答。",
        ]

    def build_session_questions(self, drill: ProjectDrillDTO) -> list[InterviewQuestionDTO]:
        questions = []
        for index, question in enumerate(drill.questions):
            key_points = [
                KeyPoint(point=item, score_range="70-90", weight="HIGH") for item in question.answer_framework[:4]
            ]
            reference_answer = (
                "回答应结论先行，明确个人贡献，说明技术取舍和验证方式；"
                f"本题重点关注：{'、'.join(question.strong_answer_signals)}。"
            )
            questions.append(
                InterviewQuestionDTO(
                    question_index=index,
                    question=question.question,
                    type="PROJECT_DRILL",
                    category=question.category,
                    topic_summary=question.risk,
                    is_follow_up=False,
                    question_type="project",
                    reference_answer=reference_answer,
                    key_points=key_points,
                )
            )
        return questions


project_drill_service = ProjectDrillService()
