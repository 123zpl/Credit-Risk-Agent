from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "credit_user"
    mysql_password: str = "credit_pass_123"
    mysql_database: str = "credit_risk_db"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # LLM
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # Embedding (独立配置，可与 LLM 使用不同服务商)
    embedding_model: str = "text-embedding-v3"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Milvus
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "regulation_docs"
    credit_policy_collection: str = "credit_policies"

    # Data
    data_sample_size: int = 50000
    data_raw_path: str = "data/lending_club_raw.csv"
    data_clean_path: str = "data/lending_club_clean.csv"

    # LangSmith：false=仅 workflow 顶层 trace（默认）；true=各节点额外 run_name/tags
    langsmith_node_tracing: bool = False

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def project_root(self) -> Path:
        return Path(__file__).parent.parent

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
