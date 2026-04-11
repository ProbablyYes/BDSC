from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Venture Agent API"
    app_env: str = "dev"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "neo4j"
    neo4j_database: str = ""
    aura_instanceid: str = ""
    aura_instancename: str = ""
    llm_provider: str = "mock"
    llm_model: str = "Qwen/Qwen2.5-14B-Instruct"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.siliconflow.cn/v1"
    llm_fast_model: str = "Qwen/Qwen2.5-14B-Instruct"
    llm_structured_model: str = "Qwen/Qwen3-32B"
    llm_reason_model: str = "deepseek-ai/DeepSeek-V3.2"
    llm_synthesis_model: str = "deepseek-ai/DeepSeek-V3.2"
    # 可选：用于生成海报插图等的视觉/图像模型（OpenAI/SiliconFlow 兼容接口）
    llm_image_model: str = ""

    # RAG 检索配置：多路检索与混合权重
    rag_retrieval_mode: str = "auto"  # "auto" | "keyword" | "vector" | "hybrid"
    rag_hybrid_alpha: float = 0.6      # hybrid 模式下向量相似度的权重

    max_parse_file_mb: float = 30.0  # modify default file size limit in MB

    # config.py -> app -> backend -> apps -> BDSC (workspace root)
    workspace_root: Path = Path(__file__).resolve().parents[3]
    data_root: Path = workspace_root / "data"
    upload_root: Path = data_root / "uploads" / "student_submissions"
    teacher_examples_root: Path = data_root / "corpus" / "teacher_examples"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()