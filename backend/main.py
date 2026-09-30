"""浙考申论智阅 · 后端服务。

启动：建表 → 导入示例题库与演示账号 → 托管前端构建产物（如已构建）。
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.api import (assistant_api, auth_api, bank_api, profile_api, review_api,  # noqa: E402
                     sheet_api, submission_api, system_api, teacher_api)
from app.core.config import settings  # noqa: E402
from app.db.seed import ensure_seeded  # noqa: E402
from app.db.session import init_db  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    lines = await ensure_seeded()
    print("=" * 64)
    print(f"  {settings.app_name} v{settings.app_version} 已启动")
    print("=" * 64)
    if settings.llm_enabled:
        print(f"  模型网关  : {settings.llm_provider_label}（{settings.llm_base_url}）")
        print(f"  评分/复核 : {settings.llm_model_medium} / {settings.llm_model_large}")
        print(f"  识别      : {settings.llm_model_vision}")
    else:
        print("  模型网关  : 未配置。识别改为手动录入，批改由规则引擎完成（界面会标注）")
    for ln in lines:
        print(f"  {ln}")
    url = f"http://127.0.0.1:{settings.app_port}"
    print(f"  访问地址  : {url}    接口文档: {url}/docs")
    print("=" * 64)
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
              description="浙江省考申论的证据化评分、失分诊断与能力增分智能体。")

# 前端用 Bearer 令牌，不依赖 Cookie，所以不开 allow_credentials，也不放行任意来源
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])

for r in (auth_api.router, bank_api.router, sheet_api.router, submission_api.router,
          review_api.router, teacher_api.router, profile_api.router, assistant_api.router,
          system_api.router):
    app.include_router(r, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "llm": settings.llm_enabled}


@app.exception_handler(Exception)
async def unhandled(request, exc: Exception):  # noqa: ANN001
    # 不把异常详情回给前端，只在服务端日志里保留
    import traceback
    traceback.print_exception(exc)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请查看后端日志"})


# ---------- 托管前端构建产物 ----------
_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        # 前端是单页应用：非 /api 的路径都回 index.html，刷新子页面不会 404
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "接口不存在"})
        f = (_DIST / path).resolve()
        if path and f.is_file() and _DIST.resolve() in f.parents:
            return FileResponse(str(f))
        return FileResponse(str(_DIST / "index.html"))
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": settings.app_name, "docs": "/docs",
                "frontend": "未构建。请运行 install.bat，或在 frontend 目录执行 npm run build。"}


def _port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _open_browser_when_ready(url: str) -> None:
    """服务真正能响应后再打开浏览器。

    先开浏览器的话，端口被别的程序占着时，打开的就是那个程序的页面，用户会以为装错了。
    """
    import threading
    import time
    import urllib.request
    import webbrowser

    def wait():
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"{url}/api/health", timeout=1) as r:
                    if b'"status"' in r.read():
                        webbrowser.open(url)
                        return
            except Exception:  # noqa: BLE001
                time.sleep(0.5)

    threading.Thread(target=wait, daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    port = settings.app_port
    if not _port_free(port):
        print("=" * 64)
        print(f"  [错误] 端口 {port} 已被其他程序占用，本服务没有启动。")
        print(f"  如果浏览器里 http://127.0.0.1:{port} 打开的是别的系统，就是它占用了端口。")
        print("  解决：关掉那个程序，或在 backend\\.env 里把 APP_PORT 改成其他端口（如 8200）。")
        print("=" * 64)
        sys.exit(1)
    if "--no-browser" not in sys.argv:
        _open_browser_when_ready(f"http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
