import os
from pathlib import Path

# 自动加载 .env 文件
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")


class Settings:
    APP_NAME: str = "长期任务规划师"
    APP_VERSION: str = "1.0.0"

    # MySQL
    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "ib_assistant")
    DB_SOCKET: str = os.getenv("DB_SOCKET", "/tmp/mysql.sock")

    # DeepSeek（备选）
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # Ark（豆包 - 主 AI 引擎）
    ARK_API_KEY: str = os.getenv("ARK_API_KEY", "")
    ARK_BASE_URL: str = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    ARK_MODEL: str = os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628")

    # JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "ib-assistant-secret-key-change-me")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    @property
    def database_url(self) -> str:
        base = (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )
        if self.DB_SOCKET:
            base += f"&unix_socket={self.DB_SOCKET}"
        return base


settings = Settings()
