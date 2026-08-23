@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
:: Ecommerce Agent 一键安装脚本 (Windows)
:: 用法: 双击运行 setup.bat
:: ============================================================

echo.
echo ==============================================
echo   Ecommerce Agent 一键安装向导 (Windows)
echo ==============================================
echo.

:: ---------- Step 1: 检测 Python ----------
echo [INFO] 检测 Python 版本...

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.11+
    echo   下载地址: https://www.python.org/downloads/
    echo   安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK]   Python: %PYVER%

:: ---------- Step 2: 创建虚拟环境 ----------
echo [INFO] 配置 Python 虚拟环境...

set VENV_DIR=%~dp0.venv

if exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [OK]   虚拟环境已存在: %VENV_DIR%
) else (
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [OK]   虚拟环境已创建: %VENV_DIR%
)

:: 激活虚拟环境
call "%VENV_DIR%\Scripts\activate.bat"

:: ---------- Step 3: 安装 Python 依赖 ----------
echo [INFO] 安装 Python 依赖（这可能需要几分钟）...

python -m pip install --upgrade pip -q

pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo [ERROR] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)
echo [OK]   Python 依赖安装完成

:: ---------- Step 4: 配置环境变量 ----------
echo [INFO] 配置环境变量...

set ENV_FILE=%~dp0.env
set ENV_EXAMPLE=%~dp0.env.example

if exist "%ENV_FILE%" (
    echo [WARN] .env 文件已存在，跳过配置
) else (
    copy "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
    echo [OK]   已从 .env.example 复制为 .env
    echo.
    echo   ====================================================
    echo   请编辑 .env 文件，填入以下必填配置：
    echo   ====================================================
    echo.
    echo   必填项：
    echo     LLM_API_KEY        - 大模型 API 密钥
    echo     FEISHU_APP_ID      - 飞书应用 ID
    echo     FEISHU_APP_SECRET  - 飞书应用密钥
    echo     API_KEY            - HTTP 接口鉴权密钥
    echo.
    echo   配置文件位置: %ENV_FILE%
    echo.

    set /p EDIT_ENV="是否现在编辑 .env 文件？[Y/n] "
    if /i not "!EDIT_ENV!"=="n" (
        notepad "%ENV_FILE%"
    )
)

:: ---------- Step 5: 初始化数据库 ----------
echo [INFO] 初始化数据库...
cd /d "%~dp0"
python scripts/init_db.py
echo [OK]   数据库初始化完成

:: ---------- Step 6: 创建数据目录 ----------
echo [INFO] 创建数据目录...
if not exist "%~dp0data\uploads" mkdir "%~dp0data\uploads"
if not exist "%~dp0data\vectorstore" mkdir "%~dp0data\vectorstore"
if not exist "%~dp0data\documents" mkdir "%~dp0data\documents"
if not exist "%~dp0data\reports" mkdir "%~dp0data\reports"
echo [OK]   数据目录创建完成

:: ---------- Step 7: 创建启动脚本 ----------
echo [INFO] 创建快捷启动脚本...

(
echo @echo off
echo chcp 65001 ^>nul 2^>^&1
echo setlocal enabledelayedexpansion
echo.
echo set PROJECT_DIR=%%~dp0
echo cd /d "%%PROJECT_DIR%%"
echo.
echo :: 激活虚拟环境
echo if exist "%%PROJECT_DIR%%.venv\Scripts\activate.bat" ^(
echo     call "%%PROJECT_DIR%%.venv\Scripts\activate.bat"
echo ^)
echo.
echo set MODE=%%1
echo if "%%MODE%"=="" set MODE=dev
echo.
echo if "%%MODE%"=="dev" ^(
echo     echo [INFO] 启动开发模式（热重载）...
echo     uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
echo ^) else if "%%MODE%"=="prod" ^(
echo     echo [INFO] 启动生产模式...
echo     uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
echo ^) else ^(
echo     echo 用法: start.bat [dev^|prod]
echo     echo   dev  - 开发模式（热重载, 默认）
echo     echo   prod - 生产模式
echo ^)
) > "%~dp0start.bat"

echo [OK]   启动脚本已创建: start.bat

:: ---------- 完成 ----------
echo.
echo ==============================================
echo   安装完成！
echo ==============================================
echo.
echo   后续步骤：
echo     1. 编辑配置: notepad .env  (填入 API 密钥等)
echo     2. 启动服务: start.bat        (开发模式)
echo                    start.bat prod   (生产模式)
echo     3. 访问服务: http://localhost:8000
echo     4. 健康检查: curl http://localhost:8000/health
echo.
echo   常用命令：
echo     停止服务:   Ctrl+C
echo     运行测试:   pytest tests/
echo.

pause
