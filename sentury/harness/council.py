import json
import logging
from typing import Any, Dict, List

from ..llm.action_parser import extract_plain_text

logger = logging.getLogger(__name__)


COUNCIL_MEMBERS = ("cx", "operations", "finance", "commercial", "strategy")

COUNCIL_SYSTEM_PROMPT = """Voce e o Conselho do Sentury. Em UMA unica deliberacao
interna, assuma cinco papeis: Cliente, Operacoes, Financeiro, Comercial e Estrategia.
Cada papel deve produzir um parecer independente, confrontar os demais pontos de
vista internamente e chegar a uma recomendacao executiva de consenso.

Use somente os dados fornecidos. Nao invente numeros, metas, valores, datas ou
causas. Se faltarem dados, diga qual analise e necessaria em vez de preencher a
lacuna com suposicoes. Seja especifico e objetivo.

Retorne APENAS JSON valido, sem markdown, exatamente neste formato:
{
  "perspectives": {
    "cx": "parecer do ponto de vista do cliente",
    "operations": "parecer operacional",
    "finance": "parecer financeiro",
    "commercial": "parecer comercial",
    "strategy": "parecer estrategico"
  },
  "trade_offs": ["trade-off concreto 1", "trade-off concreto 2"],
  "consensus_recommendation": "recomendacao final que concilia os cinco papeis"
}

Cada parecer deve ter no maximo 120 palavras."""


class SenturyCouncil:
    # Teto por resultado de ferramenta: evita que uma causa-raiz extensa ocupe
    # toda a janela da chamada unica do conselho.
    _MAX_RESULT_CHARS = 2500

    def __init__(self, llm_chain):
        self.llm = llm_chain

    def _cap_results(self, tool_results: List[Dict[str, Any]]) -> str:
        capped = []
        for tool_result in tool_results:
            blob = json.dumps(tool_result, ensure_ascii=False, indent=2)
            if len(blob) > self._MAX_RESULT_CHARS:
                blob = (
                    blob[: self._MAX_RESULT_CHARS]
                    + f"\n... [resultado truncado - {len(blob)} caracteres no total]"
                )
            capped.append(blob)
        return "\n".join(capped) or "Nenhum dado analitico disponivel nesta conversa."

    @staticmethod
    def _json_from_response(raw: str) -> Dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3]
        if "{" in cleaned and "}" in cleaned:
            cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("resposta do conselho nao e objeto JSON")
        return parsed

    @staticmethod
    def _clean_perspectives(value: Any) -> Dict[str, str]:
        source = value if isinstance(value, dict) else {}
        return {
            member: str(source.get(member) or "").strip()
            for member in COUNCIL_MEMBERS
            if str(source.get(member) or "").strip()
        }

    async def analyze(self, user_message: str, tool_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Executa o conselho inteiro em uma chamada com cinco papeis internos."""
        data_str = self._cap_results(tool_results)
        messages = [
            {"role": "system", "content": COUNCIL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Pedido do usuario:\n{user_message}\n\nDados da sessao:\n{data_str}",
            },
        ]
        try:
            try:
                raw = await self.llm.complete(
                    messages, temperature=0.25, complexity="CRITICAL", profile="analysis"
                )
            except TypeError:
                raw = await self.llm.complete(messages, temperature=0.25)
            parsed = self._json_from_response(extract_plain_text(raw))
            perspectives = self._clean_perspectives(parsed.get("perspectives"))
            consensus = str(parsed.get("consensus_recommendation") or "").strip()
            if not perspectives or not consensus:
                raise ValueError("resposta do conselho sem pareceres ou consenso")
            trade_offs = [
                str(item).strip()
                for item in (parsed.get("trade_offs") or [])
                if str(item).strip()
            ]
            return {
                "perspectives": perspectives,
                "peer_reviews": [],
                "trade_offs": trade_offs,
                "consensus_recommendation": consensus,
            }
        except Exception as exc:
            logger.warning("Falha na chamada unica do Conselho: %s", exc)
            return {
                "perspectives": {},
                "peer_reviews": [],
                "trade_offs": [],
                "consensus_recommendation": "Nao foi possivel estruturar o conselho com os dados deste turno.",
            }
