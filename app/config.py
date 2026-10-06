from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POSTGRES_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    host: str = "localhost"
    port: int = 5432
    db: str = "interview_guide"
    user: str = "postgres"
    password: str = "password"

    @property
    def dsn(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None

    @property
    def dsn(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class AiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bailian_api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    temperature: float = 0.2
    structured_max_attempts: int = 2
    structured_include_last_error: bool = True
    structured_retry_use_repair_prompt: bool = True
    embedding_model: str = "text-embedding-v2"
    embedding_api_key: str = ""  # Embedding API 单独配置（默认使用 bailian_api_key）
    embedding_provider: str = "zhipu"  # zhipu | dashscope
    zhipu_api_key: str = ""  # 智谱 API key


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_STORAGE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    endpoint: str = "http://localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket: str = "interview-guide"
    region: str = "us-east-1"


class CorsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CORS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    allowed_origins: str = (
        "http://localhost:5173,http://localhost:5174,http://localhost:5176,"
        "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5176"
    )

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


class InterviewSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_INTERVIEW_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    follow_up_count: int = 1
    evaluation_batch_size: int = 8
    default_skill_id: str = "java-backend"
    default_difficulty: str = "mid"
    # LLM 追问/转场生成开关：关闭后链路自动回退到规则模板，保证面试不中断
    question_realizer_enabled: bool = True
    # 单次 QuestionRealizer 的超时上限（秒），超时即回退模板，避免卡住答题链路
    question_realizer_timeout_seconds: float = 25.0
    # Hybrid Answer Evaluator（LLM 语义评分）：关闭时直接走 heuristic fallback，不是错误
    answer_evaluator_enabled: bool = True
    # 单次 answer evaluation 的超时上限（秒），超时即回退 heuristic
    answer_evaluator_timeout_seconds: float = 12.0


class ResumeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_RESUME_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    upload_dir: str = "/tmp/ai-interview/resumes"
    max_file_size: int = 10 * 1024 * 1024
    allowed_types: list[str] = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
    ]

    # ---- PR4：Canonical Resume 事实抽取 ----
    # 关闭时跳过 canonical 抽取，继续原 Resume Grading；不能把 analyze 当失败。
    canonical_extractor_enabled: bool = True
    # canonical 超时不能让 background task 一直卡住
    canonical_extractor_timeout_seconds: float = 30.0


class GitHubSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GITHUB_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tokens: str = ""  # 逗号分隔的 GitHub Personal Access Token 列表

    @property
    def token_list(self) -> list[str]:
        return [t.strip() for t in self.tokens.split(",") if t.strip()]


class VoiceInterviewSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_VOICE_INTERVIEW_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_provider: str = "dashscope"
    stt_provider: str = "local_whisper"
    stt_model: str = "small"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    stt_hf_endpoint: str = "https://hf-mirror.com"
    max_audio_size_mb: int = 25
    user_utterance_debounce_ms: int = 2500
    min_silence_before_commit_ms: int = 2500
    min_commit_chars: int = 20
    max_wait_for_continuation_ms: int = 7000
    ai_question_max_chars: int = 120

    # ---- 流式 STT (FunASR) ----
    # 主用模型: SenseVoice-Small（中文 CER 7.81%，CPU 17x 实时，多语种/情感标签）
    funasr_model: str = "iic/SenseVoiceSmall"
    funasr_device: str = "cpu"  # cpu / cuda
    funasr_quantize: bool = True  # int8 量化（CPU 模式推荐）
    funasr_hf_endpoint: str = "https://hf-mirror.com"
    # WebSocket 流式分块
    streaming_stt_chunk_ms: int = 200  # 每帧时长 (ms)
    streaming_stt_sample_rate: int = 16000  # PCM 采样率 (Hz)
    streaming_stt_max_session_seconds: int = 600  # 单次会话硬上限 (s)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Interview Platform"
    debug: bool = False
    strict_config: bool = False

    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    ai: AiSettings = AiSettings()
    storage: StorageSettings = StorageSettings()
    cors: CorsSettings = CorsSettings()
    interview: InterviewSettings = InterviewSettings()
    resume: ResumeSettings = ResumeSettings()
    voice_interview: VoiceInterviewSettings = VoiceInterviewSettings()
    github: GitHubSettings = GitHubSettings()


settings = Settings()
