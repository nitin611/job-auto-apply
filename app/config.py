from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    claude_transport: str = "claude_cli"
    claude_bin: str = "claude"
    dry_run: bool = True

    db_path: str = "./data/jobs.db"
    log_level: str = "INFO"

    gmail_address: str = ""
    gmail_app_password: str = ""

    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def db_url(self) -> str:
        path = (ROOT / self.db_path).resolve() if not self.db_path.startswith("/") else Path(self.db_path)
        return f"sqlite:///{path}"

    @property
    def profile_dir(self) -> Path:
        return ROOT / "profile"

    @property
    def logs_dir(self) -> Path:
        return ROOT / "logs"

    @property
    def browser_state_dir(self) -> Path:
        return ROOT / "browser_state"


settings = Settings()
