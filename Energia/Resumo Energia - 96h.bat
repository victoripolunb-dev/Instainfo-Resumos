@echo off
cd /d "%~dp0"
echo.
echo ============================================
echo    Motor de Energia - Resumo das 96 horas
echo ============================================
python main.py --horas 96
echo.
pause