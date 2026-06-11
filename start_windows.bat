@echo off
chcp 65001 >nul
echo ================================================
echo   古代水利工程遗迹功能复原与可持续性评估系统
echo   启动脚本 (Windows)
echo ================================================
echo.

:check_python
echo [1/5] 检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未检测到Python，请先安装Python 3.9+
    pause
    exit /b 1
)
python --version
echo ✅ Python环境就绪
echo.

:check_backend
echo [2/5] 检查并安装后端依赖...
cd /d "%~dp0backend"
if not exist "venv\Scripts\activate.bat" (
    echo 创建Python虚拟环境...
    python -m venv venv
)
call venv\Scripts\activate.bat
pip install -r requirements.txt
echo ✅ 后端依赖安装完成
echo.

:generate_data
echo [3/5] 生成模拟数据...
cd /d "%~dp0scripts"
cd /d "%~dp0"
python scripts\generate_data.py
echo ✅ 数据生成完成
echo.

:init_db
echo [4/5] 提示：请确保PostgreSQL已安装并运行，且已创建数据库
echo   1. 创建数据库: CREATE DATABASE water_heritage;
echo   2. 在数据库中执行: CREATE EXTENSION postgis;
echo   3. 然后执行 scripts\init_database.sql 初始化表结构
echo   或在启动后使用API导入数据
echo.
copy /y "%~dp0backend\.env.example" "%~dp0backend\.env" >nul

:start_backend
echo [5/5] 启动FastAPI后端服务...
cd /d "%~dp0backend"
if not exist "venv\Scripts\activate.bat" (
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
)
call venv\Scripts\activate.bat

echo.
echo ================================================
echo   后端服务地址: http://localhost:8000
echo   API文档:      http://localhost:8000/docs
echo ================================================
echo   前端: 请在浏览器打开 frontend\index.html
echo   或使用任意静态HTTP服务器 (如: npx serve frontend)
echo ================================================
echo.

cd /d "%~dp0backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

pause
