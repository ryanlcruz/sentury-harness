"""Rotas para recuperar uma execução que falhou de um jeito conhecido.

As rotas moram em `policies/rotas.yaml`. Aqui fica só o que não se muda por
arquivo: pedido de permissão nunca ganha rota, porque desviar dele seria
ensinar o modelo a contornar a regra.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..exec.contrato import CodigoDeErro


@dataclass(frozen=True)
class Rota:
    alternativa: str
    instrucao: str


def _declaradas() -> Dict[str, Any]:
    from ..policies import carregar

    return carregar("rotas", {"rotas": [], "aviso": "[ROTA DE RECUPERACAO] {instrucao}"})


def _casa(rota: Dict[str, Any], ferramenta: str, codigo: str, motivo: str) -> bool:
    if str(rota.get("ferramenta") or "") != ferramenta:
        return False
    if rota.get("codigo_erro"):
        return str(rota["codigo_erro"]) == codigo
    trecho = str(rota.get("motivo_contem") or "").lower()
    return bool(trecho) and trecho in motivo


def rota_para(ferramenta: str, resultado: Any) -> Optional[Rota]:
    if not isinstance(resultado, dict):
        return None
    codigo = str(resultado.get("codigo_erro") or "")
    if codigo == CodigoDeErro.PRECISA_PERMISSAO or resultado.get("precisa_permissao"):
        return None
    motivo = str(resultado.get("erro") or resultado.get("motivo") or "").lower()
    rotas: List[Dict[str, Any]] = [r for r in _declaradas().get("rotas") or [] if isinstance(r, dict)]
    for rota in rotas:
        if _casa(rota, str(ferramenta), codigo, motivo):
            shell = "powershell" if os.name == "nt" else "bash"
            instrucao = " ".join(str(rota.get("instrucao") or "").split()).replace("{shell}", shell)
            return Rota(str(rota.get("alternativa") or ""), instrucao)
    return None


def dica_de_rota(ferramenta: str, resultado: Any) -> str:
    rota = rota_para(ferramenta, resultado)
    if rota is None:
        return ""
    aviso = " ".join(str(_declaradas().get("aviso") or "{instrucao}").split())
    return aviso.replace("{instrucao}", rota.instrucao)


def e_alternativa(ferramenta: str, resultado: Any, proxima: str) -> bool:
    rota = rota_para(ferramenta, resultado)
    return bool(rota and rota.alternativa == str(proxima))


class RastreadorDeRota:
    """Mantem o estado de recuperacao fora do laco principal do agente."""

    def __init__(self) -> None:
        self._ultima_falha = None
        self._avisado = False
        self._deu_certo_depois = False

    def aviso_se_parou(self) -> str:
        """O fato para o modelo quando ele responde sem tentar a rota de uma
        falha que acabou de acontecer. Uma vez por falha, e só se nada deu certo
        depois dela: anunciar a rota não executa nada."""
        if not self._ultima_falha or self._avisado or self._deu_certo_depois:
            return ""
        origem, _, resultado = self._ultima_falha
        rota = rota_para(origem, resultado)
        if rota is None:
            return ""
        self._avisado = True
        modelo = " ".join(str(_declaradas().get("rota_pendente") or "").split())
        return modelo.replace("{origem}", origem).replace("{alternativa}", rota.alternativa)

    def preparar(self, budget: Any, ferramenta: str, argumentos: Any) -> Optional[bool]:
        """Retorna se esta e a primeira tentativa, ou ``None`` se nao e rota."""
        if not self._ultima_falha:
            return None
        origem, args_origem, resultado = self._ultima_falha
        if not e_alternativa(origem, resultado, ferramenta):
            return None
        return budget.registrar_rota(origem, args_origem, ferramenta, argumentos)

    def falhou(self, ferramenta: str, argumentos: Any, resultado: Any) -> None:
        self._ultima_falha = (ferramenta, dict(argumentos or {}), resultado)
        # A rota aponta uma ferramenta que pode não estar na mesa desta chamada;
        # sem ela, o modelo só consegue anunciar o caminho, não segui-lo.
        rota = rota_para(ferramenta, resultado)
        if rota is not None:
            from .descoberta import carregar

            carregar(rota.alternativa)
        self._avisado = False
        self._deu_certo_depois = False

    def concluiu(self, budget: Any, tentativa: Optional[bool], telemetry: dict) -> None:
        self._deu_certo_depois = True
        if tentativa is None:
            return
        budget.rota_bem_sucedida(tentativa)
        if tentativa:
            telemetry["route_switches"] = telemetry.get("route_switches", 0) + 1
        self._ultima_falha = None
