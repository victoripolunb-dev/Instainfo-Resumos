@echo off
cd /d "%~dp0"
echo.
echo ============================================
echo    Motor de Energia - Resumo das 48 horas
echo ============================================
python main.py --horas 48
echo.
pause