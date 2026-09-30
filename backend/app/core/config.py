"""全局配置。

模型网关走 OpenAI 兼容协议（DeepSeek、通义千问、智谱、OpenAI、各类中转网关都支持），
换厂商只改 .env，不改代码。网关未配置时系统仍可完整运行：
识别改为手动录入，批改改由规则引擎完成，界面会明确标注「规则评分，非模型评分」。
"""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
PROJECT_ROOT = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "浙考申论智阅"
    app_version: str = "0.1.0"
    # 不用 8000：同机器上的其他 FastAPI 项目（如招聘平台）默认都占 8000
    app_port: int = 8100

    # ---------- 模型网关（OpenAI 兼容）----------
    llm_base_url: str = ""
    llm_api_key: str = ""
    # 评分用中档模型；证据校验不通过的评分点送大模型复核；OCR 用视觉模型
    llm_model_medium: str = "claude-sonnet-5"
    llm_model_large: str = "claude-opus-5"
    llm_model_vision: str = "claude-sonnet-5"
    llm_timeout: int = 180
    # 知情同意文案里要写明图片发给了谁，所以这里是给人看的名字
    llm_provider_label: str = "未配置"

    # ---------- 存储 ----------
    database_url: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"

    # ---------- 上传限制 ----------
    max_upload_mb: int = 10
    max_pages: int = 8

    # ---------- 认证 ----------
    secret_key: str = ""
    token_ttl_hours: int = 72
    # 首次启动是否创建演示账号。密码随机生成并打印在启动日志里，不写死在代码中。
    seed_demo_accounts: bool = True
    # 启动时导入 app/data/papers/*.json 里的真题（幂等，已导入的跳过）
    seed_real_papers: bool = True
    # 自编示例题：只给测试用（带关键词评分点，规则引擎能批）。正式题库用真题和 AI 模拟卷
    seed_sample_papers: bool = False

    cors_origins: list[str] = ["http://localhost:5174", "http://127.0.0.1:5174"]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)


def _gateway_fallback(s: "Settings") -> None:
    """.env 没配模型网关时，复用系统环境变量里的网关（与 Claude Code、招聘平台共用）。

    这个网关同时兼容 OpenAI 协议，地址后补 /v1。密钥只从环境变量读，不落盘。
    """
    if s.llm_base_url or s.llm_api_key:
        return
    base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    if base and token:
        s.llm_base_url = base if base.endswith("/v1") else base + "/v1"
        s.llm_api_key = token
        if s.llm_provider_label == "未配置":
            s.llm_provider_label = "系统环境变量中的模型网关"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not os.environ.get("SHENLUN_NO_GATEWAY_FALLBACK"):
        _gateway_fallback(s)
    Path(s.upload_dir).mkdir(parents=True, exist_ok=True)
    s.secret_key = s.secret_key or _load_or_create_secret()
    return s


def _load_or_create_secret() -> str:
    """令牌密钥：优先环境变量，其次 data/secret.key，都没有就新建。

    每台机器首次启动自动生成自己的密钥，仓库里不存在任何默认密钥。
    """
    env = os.environ.get("APP_SECRET_KEY", "")
    if env:
        return env
    key_file = BASE_DIR / "data" / "secret.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        v = key_file.read_text(encoding="utf-8").strip()
        if v:
            return v
    v = secrets.token_urlsafe(48)
    key_file.write_text(v, encoding="utf-8")
    return v


settings = get_settings()
