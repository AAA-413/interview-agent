from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.interview.diagnosis_schemas import (
    DiagnosisItemDTO,
    InterviewDiagnosisDTO,
    InterviewDiagnosisRequest,
    PracticeTaskDTO,
    RiskQuestionDTO,
    SevenDayPlanItemDTO,
)
from app.modules.resume.history_service import resume_history_service
from app.modules.resume.schemas import AnalysisHistoryDTO, ResumeDetailDTO, ResumeProfile


class InterviewDiagnosisService:
    async def diagnose(
        self,
        db: AsyncSession,
        request: InterviewDiagnosisRequest,
        user_id: int,
    ) -> InterviewDiagnosisDTO:
        resume_detail = None
        if request.resume_id is not None:
            resume_detail = await resume_history_service.get_resume_detail(db, request.resume_id, user_id)
        return self.build_diagnosis(request, resume_detail)

    def build_diagnosis(
        self,
        request: InterviewDiagnosisRequest,
        resume_detail: ResumeDetailDTO | None = None,
    ) -> InterviewDiagnosisDTO:
        target_role = request.target_role.strip()
        target_company = request.target_company.strip() if request.target_company else None
        level = request.level.strip() if request.level else "校招/转岗"
        latest_analysis = self._latest_analysis(resume_detail)
        profile = latest_analysis.profile if latest_analysis else None
        resume_text = (resume_detail.resume_text if resume_detail else request.resume_text) or ""
        jd_text = request.jd_text or ""
        resolved_resume_id = resume_detail.id if resume_detail else request.resume_id

        score = self._readiness_score(latest_analysis, profile, resume_text, jd_text, target_company)
        weaknesses = self._build_weaknesses(latest_analysis, profile, resume_text, jd_text, target_role)
        knowledge_gaps = self._build_knowledge_gaps(target_role, jd_text)
        resume_risks = self._build_resume_risks(profile, target_role, target_company)
        project_questions = self._build_project_followups(profile, target_role)
        today_tasks = self._build_today_tasks(resolved_resume_id, weaknesses, knowledge_gaps, bool(jd_text))
        seven_day_plan = self._build_seven_day_plan(target_role, weaknesses, knowledge_gaps)
        next_actions = self._build_next_actions(resolved_resume_id, bool(jd_text))
        basis = self._build_basis(resume_detail, latest_analysis, jd_text)

        return InterviewDiagnosisDTO(
            target_role=target_role,
            target_company=target_company,
            level=level,
            resume_id=resolved_resume_id,
            resume_filename=resume_detail.filename if resume_detail else None,
            readiness_score=score,
            readiness_level=self._readiness_level(score),
            score_explanation=self._score_explanation(score, latest_analysis, resume_text, jd_text),
            weakness_summary=self._weakness_summary(weaknesses),
            diagnosis_basis=basis,
            weaknesses=weaknesses[:5],
            resume_risks=resume_risks[:6],
            project_follow_up_questions=project_questions[:8],
            knowledge_gaps=knowledge_gaps[:5],
            today_tasks=today_tasks,
            seven_day_plan=seven_day_plan,
            next_actions=next_actions,
        )

    @staticmethod
    def _latest_analysis(resume_detail: ResumeDetailDTO | None) -> AnalysisHistoryDTO | None:
        if not resume_detail or not resume_detail.analyses:
            return None
        return max(resume_detail.analyses, key=lambda item: item.analyzed_at)

    @staticmethod
    def _readiness_score(
        latest_analysis: AnalysisHistoryDTO | None,
        profile: ResumeProfile | None,
        resume_text: str,
        jd_text: str,
        target_company: str | None,
    ) -> int:
        if latest_analysis and latest_analysis.overall_score is not None:
            base_score = latest_analysis.overall_score
            project_score = latest_analysis.project_score or base_score
            skill_score = latest_analysis.skill_match_score or base_score
            score = round(base_score * 0.6 + project_score * 0.2 + skill_score * 0.2)
        else:
            score = 58

        if not resume_text.strip():
            score -= 18
        elif len(resume_text) < 600:
            score -= 6

        if not jd_text.strip():
            score -= 7

        if profile and not profile.has_projects:
            score -= 12

        if not target_company:
            score -= 2

        return max(25, min(95, score))

    def _build_weaknesses(
        self,
        latest_analysis: AnalysisHistoryDTO | None,
        profile: ResumeProfile | None,
        resume_text: str,
        jd_text: str,
        target_role: str,
    ) -> list[DiagnosisItemDTO]:
        items: list[DiagnosisItemDTO] = []

        if latest_analysis:
            for suggestion in sorted(latest_analysis.suggestions, key=lambda item: self._priority_rank(item.priority)):
                items.append(
                    DiagnosisItemDTO(
                        title=suggestion.issue,
                        severity=self._severity_from_priority(suggestion.priority),
                        evidence=f"{suggestion.category}：{suggestion.issue}",
                        impact="面试官可能顺着这个点追问细节，回答不扎实会影响可信度和岗位匹配判断。",
                        action=suggestion.recommendation,
                    )
                )

            self._append_score_gap(
                items,
                latest_analysis.skill_match_score,
                "技能匹配没有形成岗位闭环",
                "简历中的技术栈和目标岗位要求之间缺少明确对应关系。",
                f"按“{target_role}”JD 列 6 个关键词，逐条补上项目证据和可讲案例。",
            )
            self._append_score_gap(
                items,
                latest_analysis.project_score,
                "项目经历缺少可追问深度",
                "项目分偏低，说明职责、技术选择、结果指标或个人贡献还不够清楚。",
                "为最核心项目写一版 2 分钟 STAR 复盘，包含背景、动作、取舍、结果和复盘。",
            )
            self._append_score_gap(
                items,
                latest_analysis.expression_score,
                "表达专业度还需要压缩",
                "表达分偏低，面试中容易出现讲太散、关键词不足或结论不先行。",
                "把每个项目回答改成“结论先行 + 3 个证据 + 1 个反思”的结构。",
            )
            self._append_score_gap(
                items,
                latest_analysis.content_score,
                "简历信息完整度不足",
                "内容分偏低，面试官可能无法快速判断你的核心能力。",
                "补齐项目规模、数据指标、技术难点、上线结果和团队协作信息。",
            )

        if not resume_text.strip():
            items.append(
                DiagnosisItemDTO(
                    title="缺少可诊断的简历材料",
                    severity="HIGH",
                    evidence="当前没有选择已解析简历，也没有提供简历文本。",
                    impact="诊断只能基于目标岗位给出通用训练项，无法定位真实项目风险。",
                    action="先上传并完成简历解析，再用目标岗位重新生成面试诊断。",
                )
            )

        if not jd_text.strip():
            items.append(
                DiagnosisItemDTO(
                    title="缺少目标 JD 对齐",
                    severity="HIGH",
                    evidence="当前没有提供岗位 JD。",
                    impact="准备方向容易变成泛泛刷题，不能优先处理岗位筛选标准。",
                    action="粘贴目标岗位 JD，提取硬技能、项目场景、业务关键词和加分项。",
                )
            )

        if profile and not profile.has_projects:
            items.append(
                DiagnosisItemDTO(
                    title="项目样本不足",
                    severity="HIGH",
                    evidence="简历画像未识别出明确项目经历。",
                    impact="校招和转岗面试通常会围绕项目打磨后的证据追问，没有项目证据会削弱录用信号。",
                    action="补充 1 到 2 个能说明岗位能力的项目，哪怕是课程设计、实习任务或开源贡献。",
                )
            )

        defaults = [
            DiagnosisItemDTO(
                title="项目复盘缺少量化结果",
                severity="MEDIUM",
                evidence="诊断需要看到上线效果、性能变化、用户规模或业务指标。",
                impact="没有结果指标时，面试官很难判断项目价值和你的真实贡献。",
                action="为每个核心项目补 1 个结果指标，无法量化时写清楚验证方式和收益范围。",
            ),
            DiagnosisItemDTO(
                title="追问预案不足",
                severity="MEDIUM",
                evidence="多数同学只准备项目介绍，没有准备“为什么这么做”和“换方案会怎样”。",
                impact="二连问、三连问会暴露方案理解深度。",
                action="每个项目至少准备技术选型、失败边界、优化方案、个人贡献 4 类追问。",
            ),
            DiagnosisItemDTO(
                title="岗位关键词没有转成回答素材",
                severity="MEDIUM",
                evidence="岗位关键词需要落到项目证据、基础题和行为面例子里。",
                impact="只背概念不能证明你能胜任目标岗位。",
                action="把 JD 关键词拆成“会不会、做没做过、怎么证明”三列清单。",
            ),
        ]
        items.extend(defaults)
        return self._dedupe_items(items)

    @staticmethod
    def _append_score_gap(
        items: list[DiagnosisItemDTO],
        score: int | None,
        title: str,
        evidence: str,
        action: str,
    ) -> None:
        if score is not None and score < 72:
            severity = "HIGH" if score < 60 else "MEDIUM"
            items.append(
                DiagnosisItemDTO(
                    title=title,
                    severity=severity,
                    evidence=f"{evidence} 当前评分：{score}。",
                    impact="这是面试官判断是否进入下一轮时非常常见的扣分项。",
                    action=action,
                )
            )

    def _build_knowledge_gaps(self, target_role: str, jd_text: str) -> list[DiagnosisItemDTO]:
        text = f"{target_role} {jd_text}".lower()
        role_items: list[DiagnosisItemDTO]

        if self._contains_any(text, ["python", "ai", "算法", "机器学习", "llm", "rag"]):
            role_items = [
                self._gap(
                    "模型应用链路",
                    "AI 岗位会追问数据、评估、召回、重排和成本。",
                    "用一个 RAG 或 Agent 场景讲清输入、检索、生成、评估和监控。",
                ),
                self._gap(
                    "工程落地能力",
                    "只讲模型名不够，需要证明能上线和排错。",
                    "准备一次延迟、召回率、幻觉或成本优化的具体案例。",
                ),
                self._gap(
                    "基础算法表达",
                    "算法题和工程题都需要清晰说明复杂度和边界条件。",
                    "每天练 2 道目标岗位高频题，并录音复盘表达结构。",
                ),
            ]
        elif self._contains_any(text, ["前端", "frontend", "react", "vue", "javascript", "typescript"]):
            role_items = [
                self._gap(
                    "浏览器与网络链路",
                    "HTML/CSS/JS 之外，面试会追问渲染、缓存、跨域、性能。",
                    "整理从输入 URL 到页面渲染的完整链路，并补 3 个性能优化案例。",
                ),
                self._gap(
                    "工程化与组件设计",
                    "只会写页面不足以证明可维护性。",
                    "准备组件拆分、状态管理、构建优化、错误监控各 1 个案例。",
                ),
                self._gap(
                    "框架原理边界",
                    "React/Vue 项目经常被追问更新机制和性能瓶颈。",
                    "用自己的项目解释一次渲染更新、状态变更和性能优化。",
                ),
            ]
        elif self._contains_any(text, ["java", "后端", "backend", "spring", "微服务"]):
            role_items = [
                self._gap(
                    "并发与事务边界",
                    "后端面试会重点看线程安全、事务一致性和异常处理。",
                    "准备一个库存、订单或支付场景，讲清锁、事务和幂等。",
                ),
                self._gap(
                    "数据库与缓存设计",
                    "CRUD 经验需要升级成索引、慢查询、缓存一致性和容量预估。",
                    "复盘一个表设计，补充索引选择、查询路径和缓存失效策略。",
                ),
                self._gap(
                    "服务稳定性",
                    "中级岗位会追问超时、重试、限流、降级和观测。",
                    "为核心接口画出失败链路，并写出兜底方案。",
                ),
            ]
        elif self._contains_any(text, ["测试", "qa", "质量"]):
            role_items = [
                self._gap(
                    "测试策略设计",
                    "测试岗位会关注风险识别和覆盖取舍。",
                    "准备一个功能从需求到用例、自动化和回归策略的完整案例。",
                ),
                self._gap(
                    "自动化与持续集成",
                    "只会手工测试很难体现效率提升。",
                    "梳理接口、UI、性能测试各自适用场景和维护成本。",
                ),
                self._gap(
                    "缺陷定位能力",
                    "面试会追问你如何从现象定位到根因。",
                    "复盘 2 个缺陷，写清日志、数据、环境和修复验证路径。",
                ),
            ]
        else:
            role_items = [
                self._gap(
                    "岗位基础题",
                    "目标岗位的高频基础题决定第一轮通过率。",
                    "整理 20 道高频题，按“概念、场景、项目证据”三段回答。",
                ),
                self._gap(
                    "项目方法论",
                    "面试官会用项目判断你是否能独立解决问题。",
                    "准备 2 个项目，每个项目写清目标、难点、方案、结果和反思。",
                ),
                self._gap(
                    "业务理解",
                    "同样的技术能力，懂业务场景的候选人更容易被记住。",
                    "把目标公司的产品、用户和岗位职责整理成 1 页面试备忘。",
                ),
            ]

        role_items.append(
            DiagnosisItemDTO(
                title="行为面素材不成体系",
                severity="MEDIUM",
                evidence="多数面试会覆盖冲突、压力、学习能力、失败复盘和协作。",
                impact="行为面回答散乱，会削弱面试官对稳定性和成长性的判断。",
                action="准备 5 个 STAR 故事，每个故事控制在 90 秒内。",
            )
        )
        return role_items

    @staticmethod
    def _gap(title: str, evidence: str, action: str) -> DiagnosisItemDTO:
        return DiagnosisItemDTO(
            title=title,
            severity="MEDIUM",
            evidence=evidence,
            impact="这类能力常用于区分“背过题”和“做过事”。",
            action=action,
        )

    def _build_resume_risks(
        self,
        profile: ResumeProfile | None,
        target_role: str,
        target_company: str | None,
    ) -> list[RiskQuestionDTO]:
        questions: list[RiskQuestionDTO] = []
        company_text = target_company or "目标公司"

        if profile and profile.projects:
            for project in profile.projects[:3]:
                project_name = project.name or "这个项目"
                questions.append(
                    RiskQuestionDTO(
                        question=f"你在{project_name}里最核心的个人贡献是什么？如果去掉你，项目会有什么不同？",
                        risk="个人贡献边界不清，容易被认为只是参与者。",
                        answer_hint="用“我负责的模块、关键决策、量化结果、复盘改进”回答，避免只讲团队成果。",
                    )
                )
                if project.tech_stack:
                    tech = project.tech_stack[0]
                    questions.append(
                        RiskQuestionDTO(
                            question=f"{project_name}为什么选择 {tech}？如果数据量或并发翻倍，你会先改哪里？",
                            risk="技术选型和扩展性理解不足。",
                            answer_hint="讲清当时约束、替代方案、取舍理由，再给出下一阶段优化方案。",
                        )
                    )
                questions.append(
                    RiskQuestionDTO(
                        question=f"{project_name}上线后如何证明它是有效的？有没有失败指标或反例？",
                        risk="项目价值无法验证，容易被追问到结果缺失。",
                        answer_hint="准备 1 个业务指标、1 个技术指标和 1 个用户或团队反馈。",
                    )
                )

        questions.extend(
            [
                RiskQuestionDTO(
                    question=f"为什么你适合{company_text}的{target_role}？请用三个证据回答。",
                    risk="岗位动机和能力证据脱节。",
                    answer_hint="用岗位关键词匹配项目证据，不要只说感兴趣或学习能力强。",
                ),
                RiskQuestionDTO(
                    question="你最近一次遇到技术卡点是怎么定位和解决的？",
                    risk="排错过程不具体，无法体现独立解决问题能力。",
                    answer_hint="按现象、假设、验证、修复、复盘五步讲，最好带日志或数据依据。",
                ),
                RiskQuestionDTO(
                    question="如果面试官质疑你的项目难度不够，你会如何补充说明？",
                    risk="项目含金量表达不足。",
                    answer_hint="补充约束条件、关键难点、你做过的取舍和可复用经验。",
                ),
            ]
        )
        return self._dedupe_risks(questions)

    @staticmethod
    def _build_project_followups(profile: ResumeProfile | None, target_role: str) -> list[str]:
        if profile and profile.projects:
            project = profile.projects[0]
            name = project.name or "你的核心项目"
            return [
                f"{name}的目标用户或业务场景是什么？为什么这个问题值得做？",
                f"{name}里你负责的模块和其他人模块的边界是什么？",
                f"{name}最难的技术问题是什么？你尝试过哪些方案？",
                f"{name}如果重做一遍，你会改动哪三个地方？",
                f"{name}有没有压测、监控、异常兜底或数据验证？",
                f"{name}和{target_role}岗位要求之间最强的对应关系是什么？",
                "这个项目里有哪些内容是你现在还能现场画图讲清楚的？",
                "如果面试官只给你 2 分钟介绍项目，你会保留哪三句话？",
            ]

        return [
            f"你最能证明自己适合{target_role}的项目或经历是什么？",
            "这个经历里你的个人贡献和团队成果分别是什么？",
            "你遇到过的最大技术卡点是什么？如何验证解决方案有效？",
            "这个经历有什么量化结果或外部反馈？",
            "如果目标岗位追问技术深度，你准备讲哪一个细节？",
        ]

    @staticmethod
    def _build_today_tasks(
        resume_id: int | None,
        weaknesses: list[DiagnosisItemDTO],
        knowledge_gaps: list[DiagnosisItemDTO],
        has_jd: bool,
    ) -> list[PracticeTaskDTO]:
        first_weakness = weaknesses[0] if weaknesses else None
        first_gap = knowledge_gaps[0] if knowledge_gaps else None
        tasks = [
            PracticeTaskDTO(
                title="写一版核心项目 2 分钟复盘稿",
                deliverable="交付物：背景、目标、个人贡献、技术取舍、结果指标各 1 段。",
                minutes=35,
                action_path=f"/project-drill?resumeId={resume_id}" if resume_id else "/upload",
            ),
            PracticeTaskDTO(
                title=f"处理最高风险项：{first_weakness.title if first_weakness else '岗位匹配'}",
                deliverable=f"交付物：补 3 条证据和 2 个追问答案。{first_weakness.action if first_weakness else ''}".strip(),
                minutes=30,
                action_path=f"/resumes/{resume_id}" if resume_id else "/upload",
            ),
            PracticeTaskDTO(
                title=f"补齐技术缺口：{first_gap.title if first_gap else '岗位基础题'}",
                deliverable=f"交付物：完成 5 个问答卡片。{first_gap.action if first_gap else ''}".strip(),
                minutes=40,
                action_path="/knowledgebases",
            ),
        ]

        if not has_jd:
            tasks.insert(
                0,
                PracticeTaskDTO(
                    title="补一份目标 JD",
                    deliverable="交付物：岗位硬技能、项目场景、加分项、风险项各列 5 条。",
                    minutes=20,
                    action_path="/diagnosis",
                ),
            )
        return tasks[:4]

    @staticmethod
    def _build_seven_day_plan(
        target_role: str,
        weaknesses: list[DiagnosisItemDTO],
        knowledge_gaps: list[DiagnosisItemDTO],
    ) -> list[SevenDayPlanItemDTO]:
        weak_title = weaknesses[0].title if weaknesses else "简历项目表达"
        gap_title = knowledge_gaps[0].title if knowledge_gaps else "岗位基础题"
        return [
            SevenDayPlanItemDTO(
                day=1,
                theme="定位岗位与材料",
                tasks=["拆解目标 JD 关键词", f"修正最高风险项：{weak_title}", "确定主打项目和备选项目"],
            ),
            SevenDayPlanItemDTO(
                day=2,
                theme="项目打磨",
                tasks=["写 2 分钟项目复盘稿", "补技术选型和替代方案", "准备 6 个项目追问答案"],
            ),
            SevenDayPlanItemDTO(
                day=3,
                theme="基础题补强",
                tasks=[f"集中补：{gap_title}", "整理 20 道高频问答", "录音复盘表达是否结论先行"],
            ),
            SevenDayPlanItemDTO(
                day=4,
                theme="岗位场景题",
                tasks=[f"围绕{target_role}做 1 次场景设计", "准备异常、扩展、性能或协作追问", "补 1 张方案草图"],
            ),
            SevenDayPlanItemDTO(
                day=5,
                theme="行为面",
                tasks=["准备 5 个 STAR 故事", "每个故事压缩到 90 秒", "补冲突、失败、压力、学习四类问题"],
            ),
            SevenDayPlanItemDTO(
                day=6,
                theme="完整模拟",
                tasks=["完成一场 8 到 10 题模拟面试", "记录卡壳问题", "把低分答案改成结构化版本"],
            ),
            SevenDayPlanItemDTO(
                day=7,
                theme="临场冲刺",
                tasks=["复盘简历和项目风险清单", "准备反问问题", "做一次 20 分钟快问快答"],
            ),
        ]

    @staticmethod
    def _build_next_actions(resume_id: int | None, has_jd: bool) -> list[PracticeTaskDTO]:
        actions = [
            PracticeTaskDTO(
                title="项目打磨训练",
                deliverable="先把最高风险项目练到经得起连续追问，再进入完整模拟。",
                minutes=45,
                action_path=f"/project-drill?resumeId={resume_id}" if resume_id else "/upload",
            ),
            PracticeTaskDTO(
                title="更新简历证据",
                deliverable="把诊断中的高风险项改到简历项目描述里。",
                minutes=25,
                action_path=f"/resumes/{resume_id}" if resume_id else "/upload",
            ),
        ]
        if not has_jd:
            actions.append(
                PracticeTaskDTO(
                    title="补充目标 JD 后重诊断",
                    deliverable="让诊断从通用建议升级为岗位匹配建议。",
                    minutes=15,
                    action_path="/diagnosis",
                )
            )
        return actions

    @staticmethod
    def _build_basis(
        resume_detail: ResumeDetailDTO | None,
        latest_analysis: AnalysisHistoryDTO | None,
        jd_text: str,
    ) -> list[str]:
        basis = []
        if resume_detail:
            basis.append(f"简历：{resume_detail.filename}")
        if latest_analysis and latest_analysis.overall_score is not None:
            basis.append(f"最近一次简历评分：{latest_analysis.overall_score}")
        if latest_analysis and latest_analysis.profile:
            project_count = len(latest_analysis.profile.projects)
            tech_count = len(latest_analysis.profile.tech_stacks)
            basis.append(f"识别项目 {project_count} 个、技术栈 {tech_count} 个")
        basis.append("已提供目标 JD" if jd_text.strip() else "未提供目标 JD")
        return basis

    @staticmethod
    def _score_explanation(
        score: int,
        latest_analysis: AnalysisHistoryDTO | None,
        resume_text: str,
        jd_text: str,
    ) -> str:
        parts = []
        if latest_analysis and latest_analysis.overall_score is not None:
            parts.append(f"基于简历评分 {latest_analysis.overall_score}，结合项目分和技能匹配分修正")
        else:
            parts.append("当前缺少已完成的简历分析，采用岗位准备度基线")
        if not resume_text.strip():
            parts.append("缺少简历材料扣分")
        if not jd_text.strip():
            parts.append("缺少目标 JD 扣分")
        parts.append(f"当前准备度为 {score} 分")
        return "；".join(parts)

    @staticmethod
    def _weakness_summary(weaknesses: list[DiagnosisItemDTO]) -> str:
        high_count = sum(1 for item in weaknesses if item.severity == "HIGH")
        if high_count >= 3:
            return "当前最需要处理的是简历证据、岗位匹配和项目追问预案。"
        if high_count >= 1:
            return "已有一定基础，但存在会影响首轮通过率的关键风险。"
        return "基础条件不错，下一步重点是把回答训练到稳定、具体、可追问。"

    @staticmethod
    def _readiness_level(score: int) -> str:
        if score >= 82:
            return "可冲刺"
        if score >= 72:
            return "有基础"
        if score >= 60:
            return "需补强"
        return "高风险"

    @staticmethod
    def _severity_from_priority(priority: str) -> str:
        if priority in {"高", "HIGH", "high", "严重"}:
            return "HIGH"
        if priority in {"低", "LOW", "low"}:
            return "LOW"
        return "MEDIUM"

    @staticmethod
    def _priority_rank(priority: str) -> int:
        if priority in {"高", "HIGH", "high", "严重"}:
            return 0
        if priority in {"中", "MEDIUM", "medium"}:
            return 1
        return 2

    @staticmethod
    def _contains_any(text: str, keywords: Iterable[str]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    @staticmethod
    def _dedupe_items(items: list[DiagnosisItemDTO]) -> list[DiagnosisItemDTO]:
        seen: set[str] = set()
        result: list[DiagnosisItemDTO] = []
        for item in items:
            if item.title in seen:
                continue
            seen.add(item.title)
            result.append(item)
        return result

    @staticmethod
    def _dedupe_risks(items: list[RiskQuestionDTO]) -> list[RiskQuestionDTO]:
        seen: set[str] = set()
        result: list[RiskQuestionDTO] = []
        for item in items:
            if item.question in seen:
                continue
            seen.add(item.question)
            result.append(item)
        return result


interview_diagnosis_service = InterviewDiagnosisService()
