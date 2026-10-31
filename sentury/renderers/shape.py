"""Decide qual lista de linhas (tabela) e quais campos-resumo (escalares)
cada ferramenta de análise expõe para renderização/exportação: único lugar
que conhece o formato de saída de cada ferramenta, para que ascii/chart/
xlsx/csv/pdf concordem sempre na mesma tabela."""
from typing import Any, Dict, List, Tuple


def tabela_e_resumo(tool: str, result: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if isinstance(result, list):
        return result, {}

    if tool == "analyze_nps":
        return result.get("tendencia_mensal", []), _resumo(result, "tendencia_mensal")
    if tool == "analyze_segments":
        return result.get("segmentos", []), _resumo(result, "segmentos")
    if tool == "analyze_business_units":
        return result.get("unidades", []), _resumo(result, "unidades", "principais_causas_detratoras")
    if tool == "analyze_sentiment":
        dist = result.get("distribuicao_sentimento", {})
        tabela = [{"sentimento": k, "pct": v} for k, v in dist.items()]
        return tabela, _resumo(result, "distribuicao_sentimento", "exemplos_comentarios")
    if tool == "analyze_surveys":
        return result.get("por_categoria", []), _resumo(result, "por_categoria", "por_subcategoria")
    if tool == "analyze_distribution":
        return result.get("funil_por_canal", []), _resumo(result, "funil_por_canal", "por_status_envio")
    if tool == "analyze_survey_completion":
        return result.get("por_bloco_abandono", []), _resumo(result, "por_bloco_abandono")
    if tool == "analyze_contact_health":
        return result.get("por_status", []), _resumo(result, "por_status")
    if tool == "analyze_quotas":
        return result.get("cotas", []), _resumo(result, "cotas")
    if tool == "analyze_tickets":
        return result.get("por_motivo", []), _resumo(result, "por_motivo")
    if tool == "compare_periods":
        tabela = [
            {"periodo": "A", **result.get("periodo_a", {})},
            {"periodo": "B", **result.get("periodo_b", {})},
        ]
        return tabela, _resumo(result, "periodo_a", "periodo_b")
    if tool == "correlate":
        return result.get("pontos", []), _resumo(result, "pontos")
    if tool == "root_cause":
        return result.get("cadeia_causal", []), _resumo(result, "cadeia_causal")
    if tool == "executive_summary":
        return result.get("ranking_regioes", []), _resumo(result, "ranking_regioes", "principais_causas")
    if tool == "generate_recommendations":
        return result.get("recomendacoes", []), _resumo(result, "recomendacoes", "principais_fatores")

    return [], result if isinstance(result, dict) else {}


def _resumo(result: Dict[str, Any], *omitir: str) -> Dict[str, Any]:
    return {k: v for k, v in result.items() if k not in omitir}
