"""Quem faz as tarefas laterais: compactar o histórico, dar título à conversa e
resumir página longa.

A pessoa escolhe em Configurações. `atual` (padrão) usa o mesmo modelo que
responde: resume com o mesmo entendimento da conversa e não depende de nada
configurado. `auxiliar` manda para um modelo à parte, mais barato: a rota
`SENTURY_AUXILIARY_ROUTE` do YAML do RobinBandit, ou o Router quando ela não
foi declarada, sempre sem a conta do Reforçado nem a do Dedicado.
"""
import inspect
import json
import logging

from robinbandit import build_route

logger = logging.getLogger(__name__)

ATUAL, AUXILIAR = "atual", "auxiliar"
ARQUIVO = "tarefas_laterais.json"


class AuxiliarIndisponivel(RuntimeError):
    pass


def _arquivo():
    from ..tools.arquivos import casa_do_sentury

    return casa_do_sentury() / ARQUIVO


def modelo_lateral() -> str:
    try:
        valor = json.loads(_arquivo().read_text(encoding="utf-8")).get("modelo")
    except Exception:
        return ATUAL
    return valor if valor in (ATUAL, AUXILIAR) else ATUAL


def definir_modelo_lateral(valor: str) -> str:
    if valor not in (ATUAL, AUXILIAR):
        raise ValueError(f"escolha '{ATUAL}' ou '{AUXILIAR}'")
    arquivo = _arquivo()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps({"modelo": valor}, ensure_ascii=False), encoding="utf-8")
    return valor


class _PeloRouter:
    """A cadeia comum chamada sem o alvo fixo do Reforçado e do Dedicado."""

    def __init__(self, cadeia):
        self.cadeia = cadeia

    def __getattr__(self, nome):
        return getattr(self.cadeia, nome)

    async def complete(self, messages, **kwargs):
        from robinbandit.sentury import no_ultra

        with no_ultra():
            return await self.cadeia.complete(messages, **kwargs)


def _aceita(funcao, argumento: str) -> bool:
    try:
        parametros = inspect.signature(funcao).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == argumento or p.kind is inspect.Parameter.VAR_KEYWORD for p in parametros)


class MotorAuxiliar:
    def __init__(self, config, settings, atual=None):
        self.config = config
        self.settings = settings
        self.atual = atual
        self._montada = None

    def invalidar(self):
        self._montada = None

    def rota_declarada(self) -> bool:
        nome = str(getattr(self.settings, "SENTURY_AUXILIARY_ROUTE", "") or "")
        return nome in (getattr(self.config, "routes", None) or {})

    def _cadeia(self):
        escolha = modelo_lateral()
        if self._montada and self._montada[0] == escolha:
            return self._montada[1]
        if escolha == ATUAL and self.atual is not None:
            cadeia = self.atual
        elif self.rota_declarada() or self.atual is None:
            cadeia = build_route(self.config, self.settings.SENTURY_AUXILIARY_ROUTE, self.settings)
        else:
            logger.info("Rota auxiliar não declarada; as tarefas laterais usam o Router.")
            cadeia = _PeloRouter(self.atual)
        self._montada = (escolha, cadeia)
        return cadeia

    async def complete(self, messages, temperature=0.1, complexity="SIMPLE", **kwargs):
        try:
            cadeia = self._cadeia()
            # Esforço baixo vai só para quem o aceita: a cadeia da conversa não tem
            # esse argumento, e passá-lo derrubava toda tarefa lateral.
            if _aceita(cadeia.complete, "reasoning_effort"):
                kwargs.setdefault("reasoning_effort", "low")
            else:
                kwargs.pop("reasoning_effort", None)
            resposta = await cadeia.complete(messages, temperature=temperature, complexity=complexity, **kwargs)
            providers = getattr(cadeia, "providers", [])
            usado = getattr(cadeia, "last_provider", None)
            if any(getattr(p, "name", None) == usado and getattr(p, "e_aviso", False) for p in providers):
                raise AuxiliarIndisponivel("A rota auxiliar devolveu um aviso, não um resultado de modelo.")
            if not isinstance(resposta, str) or not resposta.strip():
                raise AuxiliarIndisponivel("A rota auxiliar não devolveu texto.")
            return resposta
        except AuxiliarIndisponivel:
            raise
        except Exception as exc:
            raise AuxiliarIndisponivel("A rota auxiliar está indisponível.") from exc
