@echo off
chcp 65001 >nul
title 智慧农业多语言一体机 · 一键启动
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"
set "BACKEND_PORT=8002"
set "FRONTEND_PORT=5189"

echo ==========================================================
echo   智慧农业多语言一体机服务系统 · 一键启动
echo ==========================================================
echo.

rem ---------- 1. 检查运行时 ----------
echo [1/5] 检查 Python 与 Node...
python --version >nul 2>&1
if errorlevel 1 (
  echo   [X] 未检测到 Python，请先安装 Python 3.10 或更高版本
  echo       下载地址：https://www.python.org/downloads/
  goto :fail
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [OK] Python %%v

node --version >nul 2>&1
if errorlevel 1 (
  echo   [X] 未检测到 Node.js，请先安装 Node 18 或更高版本
  echo       下载地址：https://nodejs.org/
  goto :fail
)
for /f %%v in ('node --version 2^>^&1') do echo   [OK] Node %%v

rem ---------- 2. 释放被占用的端口 ----------
echo.
echo [2/5] 检查端口 %BACKEND_PORT% 与 %FRONTEND_PORT% ...
for %%P in (%BACKEND_PORT% %FRONTEND_PORT%) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
    echo   端口 %%P 被进程 %%a 占用，正在结束该进程...
    taskkill /F /PID %%a >nul 2>&1
  )
)
echo   [OK] 端口已就绪

rem ---------- 3. 后端依赖与环境 ----------
echo.
echo [3/5] 准备后端环境...
cd /d "%BACKEND_DIR%"

if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo   [提示] 已根据 .env.example 生成 .env
    echo          默认不配置大模型密钥，农事问答会自动降级为本地知识库，功能不受影响。
    echo          如需接入大模型，请编辑 backend\.env 填写 AI_PROVIDER 与对应厂商的 API Key。
  ) else (
    echo   [!] 未找到 .env.example，将使用内置默认配置启动
  )
)

python -c "import fastapi, uvicorn, sqlalchemy, aiosqlite, jwt, passlib, PIL, httpx" >nul 2>&1
if errorlevel 1 (
  echo   正在安装后端依赖（首次运行需要几分钟）...
  python -m pip install --upgrade pip >nul 2>&1
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo   [X] 后端依赖安装失败，请检查网络后重试
    echo       如果下载慢，可加国内镜像：
    echo       python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    goto :fail
  )
) else (
  echo   [OK] 后端依赖已就绪
)

if not exist "data" mkdir "data"
if not exist "uploads" mkdir "uploads"

rem ---------- 4. 前端依赖 ----------
echo.
echo [4/5] 准备前端环境...
cd /d "%FRONTEND_DIR%"
if not exist "node_modules" (
  echo   正在安装前端依赖（首次运行需要几分钟）...
  call npm install
  if errorlevel 1 (
    echo   [X] 前端依赖安装失败，请检查网络后重试
    echo       如果下载慢，可先执行：npm config set registry https://registry.npmmirror.com
    goto :fail
  )
) else (
  echo   [OK] 前端依赖已就绪
)

rem ---------- 5. 启动两个服务 ----------
echo.
echo [5/5] 正在启动服务...

start "后端 · 一体机 API（:%BACKEND_PORT%）" cmd /k "cd /d "%BACKEND_DIR%" && python -m uvicorn app.main:app --host 0.0.0.0 --port %BACKEND_PORT%"

rem 等后端把端口监听起来，避免前端首屏请求打空
echo   等待后端就绪...
set /a WAIT_COUNT=0
:wait_backend
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":%BACKEND_PORT% " | findstr LISTENING >nul 2>&1
if errorlevel 1 (
  set /a WAIT_COUNT+=1
  if !WAIT_COUNT! lss 30 goto :wait_backend
  echo   [!] 后端 30 秒内未就绪，前端仍会启动，请查看"后端"窗口的报错信息
) else (
  echo   [OK] 后端已就绪
)

start "前端 · 一体机界面（:%FRONTEND_PORT%）" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"

echo.
echo ==========================================================
echo   启动完成
echo ----------------------------------------------------------
echo   终端端（一体机大屏）  http://localhost:%FRONTEND_PORT%/
echo   管理后台              http://localhost:%FRONTEND_PORT%/admin.html
echo   后端接口文档          http://127.0.0.1:%BACKEND_PORT%/docs
echo ----------------------------------------------------------
echo   管理后台演示账号：admin / admin123
echo   终端端：填姓名即可进入，也可点「游客模式」
echo ==========================================================
echo.
echo 按任意键打开终端端界面（关掉本窗口不会停止服务）
pause >nul
start "" "http://localhost:%FRONTEND_PORT%/"
exit /b 0

:fail
echo.
echo 启动未完成。请按上面的提示处理后重新运行本脚本。
echo.
pause
exit /b 1
