from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Venture Agent API"
    app_env: str = "dev"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "neo4j"
    neo4j_database: str = ""
    llm_provider: str = "mock"
    llm_model: str = "qwen-plus"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.siliconflow.cn/v1"
    llm_fast_model: str = "Qwen/Qwen2.5-14B-Instruct"
    llm_reason_model: str = "Qwen/Qwen2.5-72B-Instruct"

    # config.py -> app -> backend -> apps -> BDSC (workspace root)
    workspace_root: Path = Path(__file__).resolve().parents[3]
    data_root: Path = workspace_root / "data"
    upload_root: Path = data_root / "uploads" / "student_submissions"
    teacher_examples_root: Path = data_root / "corpus" / "teacher_examples"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()