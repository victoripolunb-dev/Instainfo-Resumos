@echo off
REM ===========================================================================
REM  Monitoramento Inteligente - rodar.bat
REM  Executa o motor genérico de monitoramento de mídia a partir da demanda.
REM
REM  Uso:
REM    rodar.bat                                  usa o demandas/demanda.json desta pasta
REM    rodar.bat --demanda caminho\demanda.json  usa outra demanda
REM    rodar.bat --de 08/09/2026 --ate 10/09/2026  sobrepõe a janela da demanda
REM    rodar.bat --horas 48                        últimas 48h (ignora as datas)
REM    rodar.bat --nao-arquivar                    não move relatórios antigos
REM ===========================================================================
cd /d "%~dp0"
python main.py %*
pause