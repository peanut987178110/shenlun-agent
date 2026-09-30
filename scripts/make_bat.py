"""生成 install.bat 与 scripts/start.bat。

.bat 必须：CRLF 换行、UTF-8、开头一段纯 ASCII 引导头。
原因：中文 Windows 默认代码页 936，含中文的 UTF-8 批处理会被 cmd.exe 切碎执行，
报错形如 'cho' is not recognized。同进程 chcp 65001 后 call 自身无效，
必须新起一个 cmd 进程。LF 换行同样会坏。

所以不手写 .bat，而是用本脚本按字节生成并自检。改脚本内容请改这里，然后运行：
    python scripts/make_bat.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "REM ==================== end of bootstrap ====================="

BOOTSTRAP = [
    "@echo off",
    "REM ASCII-only bootstrap. Keep every byte above the marker pure ASCII:",
    "REM cmd.exe mis-parses UTF-8 lines under code page 936 (Chinese Windows).",
    "REM Switch code page, then re-enter this file in a NEW cmd process.",
    'if not "%~1"=="__utf8" (',
    "    chcp 65001 >nul",
    '    cmd /d /c call "%~f0" __utf8',
    "    exit /b %errorlevel%",
    ")",
    MARKER,
]

PIP = "-i https://pypi.tuna.tsinghua.edu.cn/simple"

INSTALL = [
    "setlocal enabledelayedexpansion",
    "title 浙考申论智阅 - 安装",
    'cd /d "%~dp0"',
    "echo ================================================================",
    "echo   浙考申论智阅 · 首次安装",
    "echo ================================================================",
    "echo   1. 创建 Python 虚拟环境并安装后端依赖",
    "echo   2. 安装前端依赖并构建界面（需要 Node.js 18+）",
    "echo   3. 生成 backend\\.env 配置文件",
    "echo.",
    "pause",
    "set PY=",
    "where python >nul 2>&1 && set PY=python",
    'if "!PY!"=="" ( where py >nul 2>&1 && set PY=py )',
    'if "!PY!"=="" (',
    "    echo [错误] 未检测到 Python。请安装 Python 3.11 或更高版本，并勾选 Add Python to PATH。",
    "    pause & exit /b 1",
    ")",
    "echo [1/3] 安装后端依赖...",
    'if not exist ".venv\\Scripts\\python.exe" !PY! -m venv .venv',
    f'".venv\\Scripts\\python.exe" -m pip install -q {PIP} -r backend\\requirements.txt',
    "if errorlevel 1 (",
    "    echo     镜像源失败，改用官方源重试...",
    '    ".venv\\Scripts\\python.exe" -m pip install -q -r backend\\requirements.txt',
    "    if errorlevel 1 ( echo [错误] 后端依赖安装失败，请检查网络。 & pause & exit /b 1 )",
    ")",
    "echo [2/3] 构建前端...",
    "where node >nul 2>&1",
    "if errorlevel 1 ( echo [错误] 未检测到 Node.js，请先安装 Node.js 18+。 & pause & exit /b 1 )",
    "pushd frontend",
    "call npm install --no-audit --no-fund --registry=https://registry.npmmirror.com",
    "if errorlevel 1 call npm install --no-audit --no-fund",
    "call npm run build",
    "if errorlevel 1 ( echo [错误] 前端构建失败。 & popd & pause & exit /b 1 )",
    "popd",
    "echo [3/3] 准备配置文件...",
    'if not exist "backend\\.env" copy "backend\\.env.example" "backend\\.env" >nul',
    "echo.",
    "echo 安装完成。",
    "echo   启动：双击 scripts\\start.bat，浏览器访问 http://127.0.0.1:8100",
    "echo   演示账号的随机密码会在首次启动时打印在窗口里。",
    "echo   要启用模型批改与拍照识别，编辑 backend\\.env 填写 LLM_BASE_URL 与 LLM_API_KEY。",
    "pause",
]

START = [
    "title 浙考申论智阅",
    'cd /d "%~dp0.."',
    'if not exist ".venv\\Scripts\\python.exe" (',
    "    echo [错误] 尚未安装，请先双击上层目录的 install.bat。",
    "    pause & exit /b 1",
    ")",
    "set PYTHONIOENCODING=utf-8",
    "set PYTHONUTF8=1",
    "cd backend",
    "echo 停止服务按 Ctrl+C。服务就绪后会自动打开浏览器。",
    # 端口检测、打开浏览器都在 main.py 里做：端口可在 .env 配置，bat 里不写死
    '"..\\.venv\\Scripts\\python.exe" main.py',
    "pause",
]


def build(body: list[str]) -> bytes:
    data = ("\r\n".join(BOOTSTRAP + body) + "\r\n").encode("utf-8")
    head = data[: data.index(MARKER.encode("ascii"))]
    if any(b >= 128 for b in head):
        raise SystemExit("[中止] 引导头含非 ASCII 字节")
    if any(data[i] == 0x0D and data[i + 1] != 0x0A for i in range(len(data) - 1)):
        raise SystemExit("[中止] 存在裸 CR")
    if any(data[i] == 0x0A and data[i - 1] != 0x0D for i in range(1, len(data))):
        raise SystemExit("[中止] 存在裸 LF")
    return data


def main() -> None:
    for path, body in ((ROOT / "install.bat", INSTALL), (ROOT / "scripts" / "start.bat", START)):
        path.write_bytes(build(body))
        print(f"已生成 {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
