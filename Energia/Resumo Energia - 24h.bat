@echo off
cd /d "%~dp0"
echo.
echo ============================================
echo    Motor de Energia - Resumo das 24 horas
echo ============================================
python main.py --horas 24
echo.
pause