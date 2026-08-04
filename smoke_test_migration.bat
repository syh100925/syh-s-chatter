@echo off
setlocal
cd /d "%~dp0"

set "SOURCE=%~1"
if not defined SOURCE set /p "SOURCE=Legacy server root (Enter for this project): "
if not defined SOURCE set "SOURCE=%CD%"

set "MONGO_URI=%~2"
if not defined MONGO_URI set /p "MONGO_URI=MongoDB URI (Enter for localhost): "
if not defined MONGO_URI set "MONGO_URI=mongodb://127.0.0.1:27017"

python "%~dp0migration_smoke_test.py" --source "%SOURCE%" --mongo-uri "%MONGO_URI%"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Migration smoke test passed.
) else (
  echo Migration smoke test found blocking issues. Use --json or --report for details.
)
pause
exit /b %EXIT_CODE%
