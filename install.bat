@echo off
REM ASCII-only bootstrap. Keep every byte above the marker pure ASCII:
REM cmd.exe mis-parses UTF-8 lines under code page 936 (Chinese Windows).
REM Switch code page, then re-enter this file in a NEW cmd process.
if not "%~1"=="__utf8" (
    chcp 65001 >nul
    cmd /d /c call "%~f0" __utf8
    exit /b %errorlevel%
)
REM ==================== end of bootstrap =====================
setlocal enabledelayedexpansion
title 浙考申论智阅 - 安装
cd /d "%~dp0"
echo ================================================================
echo   浙考申论智阅 · 首次安装
echo ================================================================
echo   1. 创建 Python 虚拟环境并安装后端依赖
echo   2. 安装前端依赖并构建界面（需要 Node.js 18+）
echo   3. 生成 backend\.env 配置文件
echo.
pause
set PY=
where python >nul 2>&1 && set PY=python
if "!PY!"=="" ( where py >nul 2>&1 && set PY=py )
if "!PY!"=="" (
    echo [错误] 未检测到 Python。请安装 Python 3.11 或更高版本，并勾选 Add Python to PATH。
    pause & exit /b 1
)
echo [1/3] 安装后端依赖...
if not exist ".venv\Scripts\python.exe" !PY! -m venv .venv
".venv\Scripts\python.exe" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend\requirements.txt
if errorlevel 1 (
    echo     镜像源失败，改用官方源重试...
    ".venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt
    if errorlevel 1 ( echo [错误] 后端依赖安装失败，请检查网络。 & pause & exit /b 1 )
)
echo [2/3] 构建前端...
where node >nul 2>&1
if errorlevel 1 ( echo [错误] 未检测到 Node.js，请先安装 Node.js 18+。 & pause & exit /b 1 )
pushd frontend
call npm install --no-audit --no-fund --registry=https://registry.npmmirror.com
if errorlevel 1 call npm install --no-audit --no-fund
call npm run build
if errorlevel 1 ( echo [错误] 前端构建失败。 & popd & pause & exit /b 1 )
popd
echo [3/3] 准备配置文件...
if not exist "backend\.env" copy "backend\.env.example" "backend\.env" >nul
echo.
echo 安装完成。
echo   启动：双击 scripts\start.bat，浏览器访问 http://127.0.0.1:8100
echo   演示账号的随机密码会在首次启动时打印在窗口里。
echo   要启用模型批改与拍照识别，编辑 backend\.env 填写 LLM_BASE_URL 与 LLM_API_KEY。
pause
