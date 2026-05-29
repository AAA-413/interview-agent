from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable


@dataclass(frozen=True)
class TopicDef:
    topic_key: str
    label: str
    pack: str
    skill_key: str
    description: str
    aliases: tuple[str, ...] = ()
    supported_question_types: tuple[str, ...] = ("PROJECT", "KNOWLEDGE", "SYSTEM_DESIGN")


@dataclass(frozen=True)
class TopicPack:
    key: str
    label: str
    topics: tuple[TopicDef, ...] = ()


@dataclass(frozen=True)
class TopicNormalizationResult:
    topic_key: str
    skill_key: str
    label: str
    confidence: float
    fallback_reason: str | None = None
    raw_topic: str | None = None
    pack: str | None = None
    matched_aliases: tuple[str, ...] = field(default_factory=tuple)


QUESTION_TYPE_FALLBACKS = {
    "PROJECT": ("custom_project_topic", "项目主题无法稳定归一化"),
    "KNOWLEDGE": ("other_knowledge", "知识主题无法稳定归一化"),
    "SYSTEM_DESIGN": ("other_system_design", "系统设计主题无法稳定归一化"),
}


def _topic(
    key: str,
    label: str,
    pack: str,
    skill: str,
    description: str,
    aliases: Iterable[str],
    supported: tuple[str, ...] = ("PROJECT", "KNOWLEDGE", "SYSTEM_DESIGN"),
) -> TopicDef:
    return TopicDef(
        topic_key=key,
        label=label,
        pack=pack,
        skill_key=skill,
        description=description,
        aliases=tuple(aliases),
        supported_question_types=supported,
    )


TOPIC_PACKS: tuple[TopicPack, ...] = (
    TopicPack(
        key="common_engineering",
        label="通用工程能力",
        topics=(
            _topic(
                "project_metric_validation",
                "项目指标与效果验证",
                "common_engineering",
                "project_proof",
                "围绕项目效果指标、baseline、评估集、验证口径和上线收益的主题。",
                ("指标", "效果验证", "baseline", "评估集", "提升", "准确率", "召回率", "转化率"),
            ),
            _topic(
                "project_role_ownership",
                "项目职责与个人贡献",
                "common_engineering",
                "ownership",
                "围绕个人职责、贡献边界、独立推进和项目真实性的主题。",
                ("个人贡献", "职责", "主导", "负责", "项目真实性", "贡献边界", "独立完成"),
            ),
            _topic(
                "technical_tradeoff_analysis",
                "技术取舍分析",
                "common_engineering",
                "tradeoff",
                "围绕方案选型、替代方案比较、成本、复杂度和边界条件的主题。",
                ("技术取舍", "方案选型", "替代方案", "权衡", "成本", "复杂度", "边界"),
            ),
            _topic(
                "production_incident_troubleshooting",
                "线上问题排查",
                "common_engineering",
                "troubleshooting",
                "围绕线上故障定位、排障步骤、恢复动作和复盘的主题。",
                ("线上问题", "故障", "排查", "排障", "复盘", "事故", "报警", "告警"),
            ),
            _topic(
                "testing_quality_assurance",
                "测试与质量保障",
                "common_engineering",
                "quality",
                "围绕单元测试、集成测试、回归测试和质量保障的主题。",
                ("测试", "质量保障", "单元测试", "集成测试", "回归测试", "pytest", "测试覆盖"),
            ),
            _topic(
                "deployment_release_process",
                "部署与发布流程",
                "common_engineering",
                "deployment",
                "围绕部署、发布、回滚、环境配置和上线流程的主题。",
                ("部署", "发布", "上线", "回滚", "CI/CD", "灰度", "环境配置"),
            ),
            _topic(
                "logging_observability",
                "日志与可观测性",
                "common_engineering",
                "observability",
                "围绕日志、指标、链路追踪、监控和告警的主题。",
                ("日志", "可观测性", "监控", "链路追踪", "metrics", "trace", "告警"),
            ),
            _topic(
                "performance_optimization",
                "性能优化",
                "common_engineering",
                "performance",
                "围绕性能瓶颈、压测、延迟、吞吐和优化验证的主题。",
                ("性能优化", "瓶颈", "压测", "延迟", "吞吐", "QPS", "响应时间"),
            ),
            _topic(
                "security_basic_awareness",
                "基础安全意识",
                "common_engineering",
                "security",
                "围绕输入校验、权限、注入、数据安全和基础安全意识的主题。",
                ("安全", "注入", "权限", "越权", "敏感数据", "XSS", "CSRF"),
            ),
            _topic(
                "team_collaboration_communication",
                "协作与沟通",
                "common_engineering",
                "communication",
                "围绕跨角色沟通、任务拆解、评审和协作推进的主题。",
                ("协作", "沟通", "评审", "需求澄清", "任务拆解", "推进"),
            ),
        ),
    ),
    TopicPack(
        key="frontend",
        label="前端开发",
        topics=(
            _topic(
                "frontend_component_design",
                "前端组件设计",
                "frontend",
                "component",
                "围绕组件拆分、复用、状态边界和交互封装的前端主题。",
                ("组件设计", "组件拆分", "组件复用", "UI 组件", "受控组件", "表单组件"),
            ),
            _topic(
                "react_state_management",
                "React 状态管理",
                "frontend",
                "react",
                "围绕 React 状态、Hooks、Context、Redux/Zustand 和数据流的主题。",
                ("React 状态", "React state", "Hooks", "useState", "useReducer", "Context", "Redux", "Zustand"),
            ),
            _topic(
                "vue_state_management",
                "Vue 状态管理",
                "frontend",
                "vue",
                "围绕 Vue 响应式、Pinia/Vuex 和组件通信的主题。",
                ("Vue 状态", "Pinia", "Vuex", "响应式", "组合式 API", "组件通信"),
            ),
            _topic(
                "frontend_routing_permission",
                "前端路由与权限",
                "frontend",
                "routing",
                "围绕前端路由、权限守卫、菜单和鉴权状态的主题。",
                ("路由", "权限守卫", "菜单权限", "React Router", "Vue Router", "鉴权"),
            ),
            _topic(
                "frontend_performance_optimization",
                "前端性能优化",
                "frontend",
                "frontend_performance",
                "围绕首屏、懒加载、缓存、打包体积和渲染性能的主题。",
                ("首屏", "懒加载", "打包体积", "渲染性能", "虚拟列表", "前端性能"),
            ),
            _topic(
                "browser_rendering_event_loop",
                "浏览器渲染与事件循环",
                "frontend",
                "browser",
                "围绕浏览器渲染、事件循环、宏任务、微任务和页面生命周期的主题。",
                ("浏览器渲染", "事件循环", "宏任务", "微任务", "Event Loop", "重排", "重绘"),
            ),
            _topic(
                "frontend_network_error_handling",
                "前端网络与异常处理",
                "frontend",
                "network",
                "围绕接口请求、错误处理、重试、超时和用户反馈的主题。",
                ("前端网络", "请求重试", "超时", "错误处理", "Axios", "Fetch"),
            ),
            _topic(
                "typescript_type_design",
                "TypeScript 类型设计",
                "frontend",
                "typescript",
                "围绕 TypeScript 类型建模、泛型、联合类型和类型安全的主题。",
                ("TypeScript", "泛型", "类型设计", "联合类型", "类型守卫", "类型安全"),
            ),
            _topic(
                "frontend_build_engineering",
                "前端工程化构建",
                "frontend",
                "build",
                "围绕 Vite/Webpack、构建优化、代码分割和工程规范的主题。",
                ("Vite", "Webpack", "前端工程化", "构建", "代码分割", "Tree Shaking"),
            ),
            _topic(
                "frontend_form_validation",
                "表单与校验",
                "frontend",
                "form",
                "围绕表单状态、校验、提交、错误提示和复杂表单体验的主题。",
                ("表单", "校验", "表单状态", "字段校验", "提交", "错误提示"),
            ),
            _topic(
                "frontend_ui_state_consistency",
                "UI 状态一致性",
                "frontend",
                "ui_state",
                "围绕加载态、空态、错误态、乐观更新和 UI 一致性的主题。",
                ("UI 状态", "加载态", "空态", "错误态", "乐观更新", "状态一致性"),
            ),
            _topic(
                "frontend_accessibility_basic",
                "前端可访问性基础",
                "frontend",
                "accessibility",
                "围绕语义化、键盘访问、ARIA 和可访问性基础的主题。",
                ("可访问性", "无障碍", "ARIA", "语义化", "键盘访问"),
            ),
        ),
    ),
    TopicPack(
        key="backend_common",
        label="后端通用",
        topics=(
            _topic(
                "api_design_contract",
                "API 设计与契约",
                "backend_common",
                "api",
                "围绕 REST API、请求响应契约、错误码和接口演进的主题。",
                ("API", "接口设计", "REST", "错误码", "请求响应", "契约", "OpenAPI"),
            ),
            _topic(
                "auth_permission_control",
                "认证与权限控制",
                "backend_common",
                "auth",
                "围绕登录认证、JWT、RBAC、权限校验和多租户隔离的主题。",
                ("认证", "权限", "JWT", "RBAC", "鉴权", "登录", "多租户"),
            ),
            _topic(
                "async_task_pipeline",
                "异步任务流水线",
                "backend_common",
                "async_task",
                "围绕异步任务、队列、状态流转、重试和幂等的主题。",
                ("异步任务", "任务流水线", "队列", "后台任务", "任务状态", "重试"),
            ),
            _topic(
                "concurrency_control",
                "并发控制",
                "backend_common",
                "concurrency",
                "围绕并发写、锁、事务、竞态条件和一致性的主题。",
                ("并发", "竞态", "锁", "并发控制", "线程安全", "一致性"),
            ),
            _topic(
                "idempotency_design",
                "幂等设计",
                "backend_common",
                "idempotency",
                "围绕重复提交、请求去重、幂等键和补偿的主题。",
                ("幂等", "重复提交", "幂等键", "去重", "补偿", "重复请求"),
            ),
            _topic(
                "rate_limit_degradation",
                "限流与降级",
                "backend_common",
                "resilience",
                "围绕限流、熔断、降级、超时和服务保护的主题。",
                ("限流", "降级", "熔断", "超时", "服务保护", "削峰"),
            ),
            _topic(
                "backend_error_handling",
                "后端异常处理",
                "backend_common",
                "error_handling",
                "围绕异常分类、错误响应、日志和用户友好提示的主题。",
                ("异常处理", "错误响应", "错误码", "异常分类", "错误日志"),
            ),
            _topic(
                "file_upload_storage",
                "文件上传与存储",
                "backend_common",
                "file_storage",
                "围绕文件校验、对象存储、去重、安全和生命周期的主题。",
                ("文件上传", "对象存储", "文件校验", "去重", "OSS", "S3"),
            ),
            _topic(
                "background_job_reliability",
                "后台任务可靠性",
                "backend_common",
                "job_reliability",
                "围绕任务失败恢复、重试、死信、监控和一致性的主题。",
                ("任务可靠性", "失败恢复", "死信", "补偿", "重试", "后台任务"),
            ),
            _topic(
                "api_pagination_filtering",
                "分页、过滤与查询",
                "backend_common",
                "query",
                "围绕分页、筛选、排序、查询条件和性能的主题。",
                ("分页", "筛选", "过滤", "排序", "查询条件", "游标分页"),
            ),
        ),
    ),
    TopicPack(
        key="java_backend",
        label="Java 后端",
        topics=(
            _topic(
                "spring_ioc_aop",
                "Spring IOC 与 AOP",
                "java_backend",
                "spring",
                "Spring 容器、依赖注入、AOP 和代理机制。",
                ("Spring", "IOC", "AOP", "Bean", "依赖注入"),
            ),
            _topic(
                "spring_transaction_management",
                "Spring 事务管理",
                "java_backend",
                "spring",
                "Spring 事务传播、隔离级别和失效场景。",
                ("Spring 事务", "事务传播", "Transactional", "事务失效"),
            ),
            _topic(
                "spring_mvc_request_lifecycle",
                "Spring MVC 请求链路",
                "java_backend",
                "spring_mvc",
                "Spring MVC 请求处理、拦截器、过滤器和参数绑定。",
                ("Spring MVC", "DispatcherServlet", "拦截器", "过滤器"),
            ),
            _topic(
                "mybatis_sql_mapping",
                "MyBatis 与 SQL 映射",
                "java_backend",
                "mybatis",
                "MyBatis 映射、动态 SQL、分页和性能问题。",
                ("MyBatis", "SQL 映射", "动态 SQL", "Mapper"),
            ),
            _topic(
                "jvm_memory_gc",
                "JVM 内存与 GC",
                "java_backend",
                "jvm",
                "JVM 内存区域、GC、调优和问题定位。",
                ("JVM", "GC", "堆", "元空间", "垃圾回收", "内存溢出"),
            ),
            _topic(
                "java_thread_pool_tuning",
                "Java 线程池调优",
                "java_backend",
                "thread_pool",
                "Java 线程池参数、拒绝策略、队列和调优。",
                ("线程池", "ThreadPoolExecutor", "拒绝策略", "核心线程", "队列"),
            ),
            _topic(
                "java_concurrent_collections",
                "Java 并发集合",
                "java_backend",
                "concurrency",
                "Java 并发集合、锁和并发工具类。",
                ("ConcurrentHashMap", "并发集合", "ReentrantLock", "CountDownLatch"),
            ),
            _topic(
                "distributed_lock_java",
                "分布式锁",
                "java_backend",
                "distributed_lock",
                "Java 后端分布式锁、锁续期和安全释放。",
                ("分布式锁", "Redisson", "锁续期", "锁释放"),
            ),
            _topic(
                "spring_boot_configuration",
                "Spring Boot 配置管理",
                "java_backend",
                "spring_boot",
                "Spring Boot 配置加载、Profile 和外部化配置。",
                ("Spring Boot", "配置管理", "Profile", "配置加载"),
            ),
            _topic(
                "java_exception_design",
                "Java 异常设计",
                "java_backend",
                "exception",
                "Java 异常分类、业务异常、全局异常处理。",
                ("Java 异常", "业务异常", "全局异常", "Exception"),
            ),
            _topic(
                "spring_ai_integration",
                "Spring AI 集成",
                "java_backend",
                "spring_ai",
                "Spring AI、LLM 调用和工具集成。",
                ("Spring AI", "AI 集成", "LLM 调用"),
            ),
        ),
    ),
    TopicPack(
        key="python_backend",
        label="Python 后端",
        topics=(
            _topic(
                "fastapi_request_lifecycle",
                "FastAPI 请求链路",
                "python_backend",
                "fastapi",
                "FastAPI 路由、依赖注入、中间件和请求响应链路。",
                ("FastAPI", "依赖注入", "中间件", "路由", "请求链路"),
            ),
            _topic(
                "python_asyncio_concurrency",
                "Python asyncio 并发",
                "python_backend",
                "asyncio",
                "Python asyncio、协程、任务调度和并发边界。",
                ("asyncio", "协程", "async", "await", "事件循环"),
            ),
            _topic(
                "sqlalchemy_async_session",
                "SQLAlchemy 异步会话",
                "python_backend",
                "sqlalchemy",
                "SQLAlchemy 异步 Session、事务和连接池。",
                ("SQLAlchemy", "AsyncSession", "异步会话", "连接池"),
            ),
            _topic(
                "python_dependency_management",
                "Python 依赖管理",
                "python_backend",
                "dependency",
                "Python 依赖、虚拟环境、锁文件和部署一致性。",
                ("依赖管理", "requirements", "pyproject", "虚拟环境", "uv"),
            ),
            _topic(
                "python_project_structure",
                "Python 工程结构",
                "python_backend",
                "project_structure",
                "Python 分层架构、模块划分和可测试性。",
                ("工程结构", "模块划分", "分层架构", "包结构"),
            ),
            _topic(
                "python_background_tasks",
                "Python 后台任务",
                "python_backend",
                "background_task",
                "Python 后台任务、Celery/Redis、调度和可靠性。",
                ("后台任务", "Celery", "ARQ", "Redis 队列", "任务调度"),
            ),
            _topic(
                "pydantic_data_validation",
                "Pydantic 数据校验",
                "python_backend",
                "pydantic",
                "Pydantic 模型、字段校验、别名和结构化输出。",
                ("Pydantic", "数据校验", "BaseModel", "Field", "别名"),
            ),
            _topic(
                "python_exception_handling",
                "Python 异常处理",
                "python_backend",
                "exception",
                "Python 异常分类、业务异常、日志和错误响应。",
                ("Python 异常", "异常处理", "try", "except", "业务异常"),
            ),
            _topic(
                "python_testing_pytest",
                "Pytest 测试",
                "python_backend",
                "pytest",
                "Pytest 单元测试、异步测试、fixture 和 monkeypatch。",
                ("pytest", "fixture", "monkeypatch", "异步测试", "测试覆盖"),
            ),
            _topic(
                "python_performance_profiling",
                "Python 性能分析",
                "python_backend",
                "profiling",
                "Python 性能分析、瓶颈定位和优化。",
                ("性能分析", "profiling", "cProfile", "瓶颈", "优化"),
            ),
        ),
    ),
    TopicPack(
        key="database_cache_mq",
        label="数据库缓存消息队列",
        topics=(
            _topic(
                "mysql_index_optimization",
                "MySQL 索引优化",
                "database_cache_mq",
                "mysql",
                "MySQL 索引、执行计划、覆盖索引和慢查询优化。",
                ("MySQL 索引", "索引优化", "执行计划", "覆盖索引", "慢查询"),
            ),
            _topic(
                "mysql_transaction_isolation",
                "MySQL 事务隔离",
                "database_cache_mq",
                "mysql",
                "MySQL 事务隔离级别、锁和一致性问题。",
                ("事务隔离", "隔离级别", "幻读", "脏读", "MVCC"),
            ),
            _topic(
                "sql_query_optimization",
                "SQL 查询优化",
                "database_cache_mq",
                "sql",
                "SQL 查询改写、连接、分页和性能优化。",
                ("SQL 优化", "查询优化", "Join", "分页优化", "慢 SQL"),
            ),
            _topic(
                "redis_cache_consistency",
                "Redis 缓存一致性",
                "database_cache_mq",
                "redis",
                "Redis 缓存更新、双写一致性、失效策略和数据回源。",
                ("Redis 缓存", "缓存一致性", "双写一致性", "缓存更新", "缓存失效"),
            ),
            _topic(
                "redis_cache_penetration_hotkey",
                "缓存穿透与热点 Key",
                "database_cache_mq",
                "redis",
                "缓存穿透、击穿、雪崩、热点 Key 和限流保护。",
                ("缓存穿透", "缓存击穿", "缓存雪崩", "热点 Key", "布隆过滤器"),
            ),
            _topic(
                "redis_distributed_lock",
                "Redis 分布式锁",
                "database_cache_mq",
                "redis",
                "Redis 分布式锁、过期时间、续期和安全释放。",
                ("Redis 分布式锁", "SETNX", "RedLock", "锁续期", "安全释放"),
            ),
            _topic(
                "redis_streams_queue",
                "Redis Streams 队列",
                "database_cache_mq",
                "redis_streams",
                "Redis Streams、消费者组、确认、重试和积压处理。",
                ("Redis Streams", "消费者组", "XADD", "XACK", "pending", "消息队列"),
            ),
            _topic(
                "message_queue_reliability",
                "消息队列可靠性",
                "database_cache_mq",
                "mq",
                "消息队列可靠投递、重复消费、顺序和死信。",
                ("消息队列", "MQ", "可靠投递", "重复消费", "死信", "顺序消息"),
            ),
            _topic(
                "database_schema_design",
                "数据库表结构设计",
                "database_cache_mq",
                "schema",
                "数据库表结构、索引、约束和演进设计。",
                ("表结构", "Schema", "数据库设计", "唯一约束", "外键"),
            ),
            _topic(
                "pgvector_vector_storage",
                "pgvector 向量存储",
                "database_cache_mq",
                "vector_db",
                "pgvector 向量存储、相似度查询和索引。",
                ("pgvector", "向量存储", "向量数据库", "cosine", "embedding 存储"),
            ),
        ),
    ),
    TopicPack(
        key="ai_agent",
        label="AI Agent",
        topics=(
            _topic(
                "agent_planning_execution",
                "Agent 规划与执行",
                "ai_agent",
                "agent",
                "Agent 任务规划、执行、反思和状态推进。",
                ("Agent 规划", "任务规划", "执行链路", "Planning", "Plan", "Execute"),
            ),
            _topic(
                "multi_agent_collaboration",
                "多 Agent 协作",
                "ai_agent",
                "agent",
                "多 Agent 分工、协作、通信和冲突处理。",
                ("多 Agent", "Multi-Agent", "协作", "角色分工", "Agent 通信"),
            ),
            _topic(
                "agent_memory_context",
                "Agent 记忆与上下文",
                "ai_agent",
                "agent_memory",
                "Agent 记忆、上下文压缩、会话状态和长期记忆。",
                ("Agent memory", "记忆", "长期记忆", "上下文", "context", "上下文压缩"),
            ),
            _topic(
                "agent_tool_selection",
                "Agent 工具选择",
                "ai_agent",
                "tool",
                "Agent 工具选择、参数构造和调用结果判断。",
                ("工具选择", "Tool Selection", "工具调用", "参数构造", "函数调用"),
            ),
            _topic(
                "mcp_tool_integration",
                "MCP 工具集成",
                "ai_agent",
                "mcp",
                "MCP 服务、工具注册、调用协议和权限隔离。",
                ("MCP", "Model Context Protocol", "MCP 工具", "MCP Server", "MCP 服务", "工具集成"),
            ),
            _topic(
                "agent_quality_evaluation",
                "Agent 质量评估",
                "ai_agent",
                "evaluation",
                "Agent 成功率、质量评估、回归集和人工抽检。",
                ("Agent 评估", "质量评估", "成功率", "回归集", "评测"),
            ),
            _topic(
                "agent_failure_recovery",
                "Agent 失败恢复",
                "ai_agent",
                "recovery",
                "Agent 执行失败、重试、降级、回滚和用户兜底。",
                ("失败恢复", "重试", "降级", "回滚", "执行失败"),
            ),
            _topic(
                "agent_state_management",
                "Agent 状态管理",
                "ai_agent",
                "state",
                "Agent 状态机、步骤记录、恢复和一致性。",
                ("Agent 状态", "状态管理", "状态机", "步骤记录", "恢复"),
            ),
            _topic(
                "react_agent_reasoning",
                "ReAct 推理范式",
                "ai_agent",
                "reasoning",
                "ReAct 的思考-行动-观察循环和边界。",
                ("ReAct", "Thought", "Action", "Observation", "推理范式"),
            ),
            _topic(
                "plan_execute_agent_pattern",
                "Plan-and-Execute 模式",
                "ai_agent",
                "agent",
                "Plan-and-Execute 模式、任务拆解和执行校验。",
                ("Plan-and-Execute", "计划执行", "任务拆解", "执行校验"),
            ),
        ),
    ),
    TopicPack(
        key="llm_application",
        label="LLM 应用",
        topics=(
            _topic(
                "rag_multi_channel_retrieval",
                "RAG 多通道检索",
                "llm_application",
                "rag",
                "向量召回、关键词召回、混合检索、重排序和召回评估。",
                ("RAG", "多通道检索", "多路召回", "BM25", "向量检索", "Cross-Encoder", "重排序", "Query Rewrite"),
            ),
            _topic(
                "embedding_vector_search",
                "Embedding 与向量检索",
                "llm_application",
                "embedding",
                "Embedding、向量相似度、向量库和召回效果。",
                ("Embedding", "向量检索", "向量相似度", "语义检索", "向量库"),
            ),
            _topic(
                "reranking_cross_encoder",
                "Cross-Encoder 重排序",
                "llm_application",
                "rerank",
                "Cross-Encoder、重排序策略、延迟和效果评估。",
                ("Cross-Encoder", "重排序", "rerank", "reranking", "排序模型"),
            ),
            _topic(
                "query_rewrite_strategy",
                "查询改写策略",
                "llm_application",
                "query_rewrite",
                "Query Rewrite、多轮改写、意图补全和召回优化。",
                ("Query Rewrite", "查询改写", "意图改写", "问题改写", "召回优化"),
            ),
            _topic(
                "prompt_engineering",
                "Prompt 工程",
                "llm_application",
                "prompt",
                "Prompt 结构、约束、模板、少样本和稳定输出。",
                ("Prompt", "提示词", "Few-shot", "模板", "系统提示词"),
            ),
            _topic(
                "function_calling_tool_calling",
                "Function Calling 与工具调用",
                "llm_application",
                "tool_calling",
                "Function Calling、工具参数、结果校验和安全边界。",
                ("Function Calling", "Tool Calling", "函数调用", "工具调用", "参数校验"),
            ),
            _topic(
                "llm_context_cost_control",
                "上下文与成本控制",
                "llm_application",
                "cost",
                "上下文裁剪、token 成本、缓存和模型选择。",
                ("上下文", "成本控制", "token", "Token", "上下文压缩", "模型成本"),
            ),
            _topic(
                "llm_output_structuring",
                "LLM 结构化输出",
                "llm_application",
                "structured_output",
                "JSON Schema、结构化输出、解析和重试。",
                ("结构化输出", "JSON Schema", "Pydantic", "输出解析", "格式约束"),
            ),
            _topic(
                "llm_evaluation_metrics",
                "LLM 应用评估指标",
                "llm_application",
                "evaluation",
                "LLM 应用评估、准确率、人工抽检和回归数据集。",
                ("LLM 评估", "评估指标", "准确率", "人工抽检", "评测集"),
            ),
            _topic(
                "streaming_response_sse",
                "流式输出与 SSE",
                "llm_application",
                "streaming",
                "SSE、流式输出、取消、错误恢复和前端展示。",
                ("SSE", "流式输出", "streaming", "EventSource", "增量输出"),
            ),
            _topic(
                "knowledge_base_chunking",
                "知识库切分策略",
                "llm_application",
                "chunking",
                "知识库切分、重叠窗口、结构化切块和召回效果。",
                ("知识库切分", "chunk", "分块", "重叠窗口", "切片"),
            ),
            _topic(
                "rag_permission_filtering",
                "RAG 权限过滤",
                "llm_application",
                "permission",
                "RAG 多租户权限、检索过滤和引用安全。",
                ("RAG 权限", "权限过滤", "多租户", "检索过滤", "引用安全"),
            ),
        ),
    ),
    TopicPack(
        key="llm_finetuning_rl",
        label="LLM 微调与强化学习",
        topics=(
            _topic(
                "sft_data_preparation",
                "SFT 数据构造",
                "llm_finetuning_rl",
                "sft",
                "SFT 数据收集、清洗、格式和质量控制。",
                ("SFT", "监督微调", "数据构造", "数据清洗"),
            ),
            _topic(
                "lora_qlora_finetuning",
                "LoRA/QLoRA 微调",
                "llm_finetuning_rl",
                "finetune",
                "LoRA/QLoRA 参数高效微调、显存和效果评估。",
                ("LoRA", "QLoRA", "微调", "参数高效"),
            ),
            _topic(
                "instruction_tuning_basics",
                "指令微调基础",
                "llm_finetuning_rl",
                "instruction_tuning",
                "指令微调数据、模板和泛化能力。",
                ("指令微调", "instruction tuning", "指令数据"),
            ),
            _topic(
                "dpo_preference_optimization",
                "DPO 偏好优化",
                "llm_finetuning_rl",
                "dpo",
                "DPO 偏好数据、训练目标和效果评估。",
                ("DPO", "偏好优化", "偏好数据"),
            ),
            _topic(
                "rlhf_pipeline_basics",
                "RLHF 流程基础",
                "llm_finetuning_rl",
                "rlhf",
                "RLHF 数据、奖励模型和策略优化基础。",
                ("RLHF", "奖励模型", "人类反馈"),
            ),
            _topic(
                "ppo_rl_training_basics",
                "PPO 强化学习训练基础",
                "llm_finetuning_rl",
                "ppo",
                "PPO、策略优化和稳定训练基础。",
                ("PPO", "强化学习", "策略优化"),
            ),
            _topic(
                "reward_modeling_basics",
                "奖励模型基础",
                "llm_finetuning_rl",
                "reward_model",
                "奖励模型数据、训练和评估。",
                ("奖励模型", "Reward Model", "偏好打分"),
            ),
            _topic(
                "finetuning_evaluation",
                "微调效果评估",
                "llm_finetuning_rl",
                "evaluation",
                "微调模型评估、基准集、过拟合和人工评审。",
                ("微调评估", "效果评估", "基准集"),
            ),
            _topic(
                "dataset_quality_filtering",
                "数据质量过滤",
                "llm_finetuning_rl",
                "dataset",
                "训练数据质量、去重、过滤和分布控制。",
                ("数据质量", "数据过滤", "去重", "数据分布"),
            ),
            _topic(
                "model_overfitting_and_generalization",
                "过拟合与泛化",
                "llm_finetuning_rl",
                "generalization",
                "过拟合、泛化、验证集和正则化。",
                ("过拟合", "泛化", "验证集", "正则化"),
            ),
        ),
    ),
    TopicPack(
        key="system_design",
        label="系统设计",
        topics=(
            _topic(
                "high_concurrency_design",
                "高并发系统设计",
                "system_design",
                "system_design",
                "高并发系统容量、削峰、缓存和瓶颈定位。",
                ("高并发", "秒杀", "削峰", "容量", "QPS"),
                ("SYSTEM_DESIGN", "PROJECT"),
            ),
            _topic(
                "scalability_design",
                "可扩展性设计",
                "system_design",
                "system_design",
                "服务拆分、水平扩展、数据分片和演进路径。",
                ("可扩展", "水平扩展", "扩展性", "分片", "演进"),
                ("SYSTEM_DESIGN", "PROJECT"),
            ),
            _topic(
                "availability_fault_tolerance",
                "高可用与容错",
                "system_design",
                "system_design",
                "高可用、容错、降级、熔断和故障恢复。",
                ("高可用", "容错", "故障恢复", "降级", "熔断"),
                ("SYSTEM_DESIGN", "PROJECT"),
            ),
            _topic(
                "data_consistency_design",
                "数据一致性设计",
                "system_design",
                "system_design",
                "分布式数据一致性、事务、补偿和最终一致性。",
                ("数据一致性", "最终一致性", "分布式事务", "补偿"),
                ("SYSTEM_DESIGN", "PROJECT"),
            ),
            _topic(
                "distributed_system_tradeoffs",
                "分布式系统取舍",
                "system_design",
                "system_design",
                "分布式系统 CAP、延迟、一致性和复杂度取舍。",
                ("分布式", "CAP", "取舍", "一致性", "延迟"),
                ("SYSTEM_DESIGN", "PROJECT", "KNOWLEDGE"),
            ),
            _topic(
                "observability_design",
                "可观测性设计",
                "system_design",
                "observability",
                "系统日志、指标、链路追踪、告警和定位设计。",
                ("可观测性设计", "监控设计", "链路追踪", "告警设计"),
                ("SYSTEM_DESIGN", "PROJECT"),
            ),
            _topic(
                "cost_latency_tradeoff",
                "成本与延迟取舍",
                "system_design",
                "system_design",
                "成本、延迟、吞吐、模型调用和缓存之间的设计取舍。",
                ("成本", "延迟", "成本控制", "低延迟", "吞吐"),
                ("SYSTEM_DESIGN", "PROJECT"),
            ),
            _topic(
                "system_capacity_estimation",
                "容量评估",
                "system_design",
                "capacity",
                "容量估算、流量模型、存储和峰值评估。",
                ("容量评估", "容量估算", "流量模型", "峰值", "存储估算"),
                ("SYSTEM_DESIGN",),
            ),
            _topic(
                "security_permission_design",
                "安全与权限设计",
                "system_design",
                "security",
                "系统权限、数据隔离、审计和安全边界设计。",
                ("权限设计", "安全设计", "数据隔离", "审计", "访问控制"),
                ("SYSTEM_DESIGN", "PROJECT"),
            ),
            _topic(
                "workflow_orchestration_design",
                "工作流编排设计",
                "system_design",
                "workflow",
                "多步骤任务、状态机、失败恢复和编排设计。",
                ("工作流", "编排", "状态机", "任务编排", "流程引擎"),
                ("SYSTEM_DESIGN", "PROJECT"),
            ),
        ),
    ),
    TopicPack(
        key="fallback",
        label="兜底主题",
        topics=(
            _topic(
                "custom_project_topic",
                "自定义项目主题",
                "fallback",
                "custom",
                "无法归一化但仍可作为项目题保存的主题。",
                ("自定义项目",),
                ("PROJECT",),
            ),
            _topic(
                "other_project_experience",
                "其他项目经历",
                "fallback",
                "project",
                "其他项目经历主题。",
                ("其他项目",),
                ("PROJECT",),
            ),
            _topic(
                "other_knowledge",
                "其他知识点",
                "fallback",
                "knowledge",
                "其他知识点主题。",
                ("其他知识",),
                ("KNOWLEDGE",),
            ),
            _topic(
                "other_system_design",
                "其他系统设计",
                "fallback",
                "system_design",
                "其他系统设计主题。",
                ("其他系统设计",),
                ("SYSTEM_DESIGN",),
            ),
            _topic(
                "uncertain_topic",
                "不确定主题",
                "fallback",
                "uncertain",
                "信息不足时的兜底主题。",
                ("不确定",),
                ("PROJECT", "KNOWLEDGE", "SYSTEM_DESIGN"),
            ),
        ),
    ),
)


class TopicRegistryService:
    def __init__(self, packs: tuple[TopicPack, ...] = TOPIC_PACKS):
        self._packs = {pack.key: pack for pack in packs}
        self._topics = {topic.topic_key: topic for pack in packs for topic in pack.topics}

    @property
    def packs(self) -> dict[str, TopicPack]:
        return self._packs

    @property
    def topics(self) -> dict[str, TopicDef]:
        return self._topics

    def get_topic(self, topic_key: str) -> TopicDef | None:
        return self._topics.get(topic_key)

    def get_topics_for_packs(self, pack_keys: Iterable[str]) -> list[TopicDef]:
        result: list[TopicDef] = []
        for key in pack_keys:
            pack = self._packs.get(key)
            if pack:
                result.extend(pack.topics)
        return result

    def select_pack_keys(
        self,
        target_role: str | None = None,
        skill_id: str | None = None,
        role_domain: str | None = None,
        jd_text: str | None = None,
        resume_text: str | None = None,
    ) -> list[str]:
        text = " ".join(part for part in [target_role, skill_id, role_domain, jd_text, resume_text] if part).lower()
        packs = {"common_engineering", "backend_common", "system_design"}

        if role_domain == "frontend" or any(k in text for k in ["frontend", "前端", "react", "vue", "typescript"]):
            packs.update({"frontend"})
        if role_domain == "java_backend" or any(k in text for k in ["java", "spring", "mybatis", "jvm"]):
            packs.update({"java_backend", "database_cache_mq"})
        if role_domain == "python_backend" or any(
            k in text for k in ["python", "fastapi", "django", "flask", "sqlalchemy"]
        ):
            packs.update({"python_backend", "database_cache_mq"})
        if role_domain == "ai_agent" or any(k in text for k in ["agent", "mcp", "智能体", "工具调用", "multi-agent"]):
            packs.update({"python_backend", "ai_agent", "llm_application", "database_cache_mq"})
        if role_domain == "llm_application" or any(k in text for k in ["llm", "rag", "prompt", "embedding", "向量"]):
            packs.update({"python_backend", "llm_application", "database_cache_mq"})
        if role_domain == "llm_finetuning_rl" or any(k in text for k in ["微调", "finetune", "rlhf", "lora", "dpo"]):
            packs.update({"python_backend", "llm_application", "llm_finetuning_rl"})
        if any(k in text for k in ["redis", "mysql", "postgres", "mq", "消息队列", "缓存", "数据库"]):
            packs.update({"database_cache_mq"})

        packs.add("fallback")
        ordered = [pack.key for pack in TOPIC_PACKS if pack.key in packs]
        return ordered

    def normalize(
        self,
        raw_topic: str | None,
        evidence_snippet: str | None = None,
        question_type: str | None = None,
        target_role: str | None = None,
        skill_id: str | None = None,
        role_domain: str | None = None,
    ) -> TopicNormalizationResult:
        q_type = self._normalize_question_type(question_type)
        text = self._normalize_text(" ".join(part for part in [raw_topic, evidence_snippet] if part))
        if not text:
            return self._fallback(q_type, raw_topic, "输入主题为空")

        pack_keys = self.select_pack_keys(target_role, skill_id, role_domain, text, evidence_snippet)
        candidates = self.get_topics_for_packs(pack_keys)
        scored = [self._score_topic(topic, text, q_type, pack_keys) for topic in candidates]
        scored.sort(key=lambda item: item[0], reverse=True)

        if not scored or scored[0][0] < 0.58:
            return self._fallback(q_type, raw_topic, "低置信主题进入 fallback")

        score, topic, matched_aliases = scored[0]
        confidence = min(round(score, 2), 0.99)
        return TopicNormalizationResult(
            topic_key=topic.topic_key,
            skill_key=topic.skill_key,
            label=topic.label,
            confidence=confidence,
            raw_topic=raw_topic,
            pack=topic.pack,
            matched_aliases=tuple(matched_aliases[:5]),
        )

    def _score_topic(
        self,
        topic: TopicDef,
        normalized_text: str,
        question_type: str,
        active_pack_keys: list[str],
    ) -> tuple[float, TopicDef, list[str]]:
        aliases = (topic.topic_key, topic.label, topic.skill_key, *topic.aliases)
        matched_aliases: list[str] = []
        alias_score = 0.0
        for alias in aliases:
            normalized_alias = self._normalize_text(alias)
            if not normalized_alias:
                continue
            if normalized_alias in normalized_text:
                matched_aliases.append(alias)
                alias_score += 0.34 if len(normalized_alias) >= 4 else 0.18
                continue
            if len(normalized_alias) >= 6:
                ratio = SequenceMatcher(None, normalized_alias, normalized_text).ratio()
                if ratio >= 0.72:
                    matched_aliases.append(alias)
                    alias_score += 0.18

        if not matched_aliases:
            return (0.0, topic, matched_aliases)

        alias_score = min(alias_score, 0.76)
        pack_score = 0.14 if topic.pack in active_pack_keys else 0.04
        type_score = 0.10 if question_type in topic.supported_question_types else -0.18
        return (alias_score + pack_score + type_score, topic, matched_aliases)

    def _fallback(self, question_type: str, raw_topic: str | None, reason: str) -> TopicNormalizationResult:
        topic_key, fallback_reason = QUESTION_TYPE_FALLBACKS.get(question_type, ("uncertain_topic", reason))
        topic = self._topics[topic_key]
        return TopicNormalizationResult(
            topic_key=topic.topic_key,
            skill_key=topic.skill_key,
            label=topic.label,
            confidence=0.32,
            fallback_reason=reason or fallback_reason,
            raw_topic=raw_topic,
            pack=topic.pack,
        )

    @staticmethod
    def _normalize_question_type(question_type: str | None) -> str:
        value = (question_type or "KNOWLEDGE").strip().upper()
        aliases = {
            "PROJECT": "PROJECT",
            "项目": "PROJECT",
            "KNOWLEDGE": "KNOWLEDGE",
            "知识": "KNOWLEDGE",
            "SYSTEM_DESIGN": "SYSTEM_DESIGN",
            "SYSTEM": "SYSTEM_DESIGN",
            "系统设计": "SYSTEM_DESIGN",
        }
        return aliases.get(value, value if value in QUESTION_TYPE_FALLBACKS else "KNOWLEDGE")

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        if not value:
            return ""
        return " ".join(value.lower().replace("_", " ").replace("-", " ").split())


topic_registry_service = TopicRegistryService()
