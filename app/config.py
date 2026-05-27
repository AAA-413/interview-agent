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

    allowed_origins: str = "http://localhost:5173,http://localhost:5174,http://localhost:5176"

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
