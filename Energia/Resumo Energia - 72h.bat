@echo off
cd /d "%~dp0"
echo.
echo ============================================
echo    Motor de Energia - Resumo das 72 horas
echo ============================================
python main.py --horas 72
echo.
pause