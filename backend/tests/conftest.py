"""测试环境：独立的临时数据库与上传目录，强制关闭模型网关。

必须在导入 app 之前设置环境变量，因为 settings 在导入时就读取了。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="shenlun-test-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
# 测试不能连真实网关：关掉「复用系统环境变量网关」
os.environ["SHENLUN_NO_GATEWAY_FALLBACK"] = "1"
os.environ["SEED_SAMPLE_PAPERS"] = "true"
os.environ["SEED_REAL_PAPERS"] = "false"
os.environ["APP_SECRET_KEY"] = "test-secret"
os.environ["SEED_DEMO_ACCOUNTS"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
