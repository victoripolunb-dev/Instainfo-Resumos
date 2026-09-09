@echo off
cd /d "%~dp0"
echo.
echo ==================================================
echo   Motor de Energia - Resumo por intervalo de DATA
echo ==================================================
set /p DE=Data inicial (DD/MM/AAAA): 
set /p ATE=Data final (DD/MM/AAAA): 
python main.py --de "%DE%" --ate "%ATE%"
echo.
pause