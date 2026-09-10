# =============================================================================
# saude.py
# --------
# Monitora a SAÚDE DOS FEEDS por veículo (item "confiabilidade"):
#
#   - A cada execução, registra em JSON (Logs\saude_feeds.json) uma "fotografia"
#     da coleta: para cada veículo, o status no run (ok / vazio / falhou) e o
#     total de notícias deduplicadas dentro da janela.
#   - Se um veículo ficar SEM matérias por N runs consecutivos
#     (config.FEED_ALERTA_RUNS_SEM_MATERIA), um ALERTA é logado no início do
#     próximo run — sinal clássico de feed morto / bloqueio permanente / página
#     de erro hospedada no lugar do RSS.
#
# Status derivado por veículo:
#     "ok"     -> ao menos 1 notícia deduplicada na janela (veio de qualquer
#                 camada: RSS direto, Lupa ou fallback GN).
#     "falhou" -> ZERO notícias E os feeds diretos acusaram erro no run
#                 (HTTP != 200, feed inválido/vazio, exceção). O fallback GN
#                 pode ter coberto o veículo (status seguirá "falhou", pois o
#                 feed está oficialmente doente).
#     "vazio"  -> ZERO notícias SEM erro explícito de feed direto (ex.: jornada
#                 sem publicação dentro da janela — comum em fins de semana).
#
# Disclaimer de engenharia: "runs" != "dias". Uma mesma janela rodada 2x passa
# a contar 2 runs. O alerta é um gancho de atenção, não um diagnóstico.
# =============================================================================

import json
import logging
import os

import config

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# LEITURA / GRAVAÇÃO DO HISTÓRICO
# -----------------------------------------------------------------------------
def carregar_historico():
    """
    Lê o JSON de histórico de saúde do disco.

    Retorna: dict {"runs": [...]} (vazio se o arquivo não existir ou estiver
    corrompido — leitura nunca levanta).
    """
    try:
        if os.path.isfile(config.ARQUIVO_SAUDE_FEEDS):
            with open(config.ARQUIVO_SAUDE_FEEDS, "r", encoding="utf-8") as fh:
                dados = json.load(fh)
            if isinstance(dados, dict) and isinstance(dados.get("runs"), list):
                return dados
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível ler o histórico de saúde: %s", exc)
    return {"runs": []}


def _status_do_veiculo(nome, motor, total):
    """
    Deriva o status de UM veículo para a fotografia do run atual.
    Ver docstring do módulo para a semântica de ok/falhou/vazio.
    """
    falhou = nome in getattr(motor, "_feed_erros", set())
    if total and total > 0:
        return "ok"
    return "falhou" if falhou else "vazio"


def registrar_run(historico, motor, rotulo):
    """
    Adiciona a fotografia do run atual ao histórico e devolve o histórico
    atualizado (limitado a config.SAUDE_RUNS_MAXIMO runs — o mais antigo é
    descartado).
    """
    por_veiculo = {}
    for nome, total in getattr(motor, "_saude_run", {}).items():
        por_veiculo[nome] = {
            "status": _status_do_veiculo(nome, motor, total),
            "n": total,
        }

    historico.setdefault("runs", []).append(
        {
            "quando": config.agora_brasilia().isoformat(timespec="seconds"),
            "janela": str(rotulo or ""),
            "por_veiculo": por_veiculo,
        }
    )
    historico["runs"] = historico["runs"][-config.SAUDE_RUNS_MAXIMO:]
    return historico


# -----------------------------------------------------------------------------
# ALERTAS DE VEÍCULO SEM MATÉRIAS
# -----------------------------------------------------------------------------
def verificar_alertas(historico, limite=None):
    """
    Varre o histórico (mais recente primeiro) e devolve a lista de alertas:
    veículos sem matérias por 'limite' runs CONSECUTIVOS.

    Parâmetros:
        historico (dict): histórico carregado por carregar_historico().
        limite (int | None): nº de runs consecutivos sem matérias que disparam
                             o alerta. Padrão: config.FEED_ALERTA_RUNS_SEM_MATERIA.

    Retorna: lista de strings prontas para log (vazia se tudo saudável).
    """
    limite = limite or config.FEED_ALERTA_RUNS_SEM_MATERIA
    runs = historico.get("runs", [])
    alertas = []
    if not runs:
        return alertas

    for veiculo in config.VEICULOS:
        sem_materia_seguidos = 0
        for run in reversed(runs):
            info = run.get("por_veiculo", {}).get(veiculo) or {}
            if info.get("status") == "ok":
                break
            sem_materia_seguidos += 1
        if sem_materia_seguidos >= limite:
            alertas.append(
                f"ALERTA: '{veiculo}' sem matérias há {sem_materia_seguidos} run(s) "
                f"consecutivo(s) (limite: {limite}). Verifique se o feed está "
                f"morto ou bloqueado."
            )
    return alertas


def salvar_historico(historico):
    """
    Grava o histórico em disco (gravação atômica: .tmp + os.replace).
    Falha de gravação é não-fatal.
    """
    try:
        os.makedirs(config.DIR_LOGS, exist_ok=True)
        destino_tmp = config.ARQUIVO_SAUDE_FEEDS + ".tmp"
        with open(destino_tmp, "w", encoding="utf-8") as fh:
            json.dump(historico, fh, ensure_ascii=False, indent=1)
        os.replace(destino_tmp, config.ARQUIVO_SAUDE_FEEDS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao salvar o histórico de saúde: %s", exc)