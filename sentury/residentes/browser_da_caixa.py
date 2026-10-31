"""O navegador isolado usa o mesmo despachante e as mesmas permissões do chat."""
import asyncio
import json
import shutil

from ..tools.browser_contracts import Observation
from ..tools.browser_provider import BrowserProvider
from . import caixa, registro


def executar(agente, action):
    nome = caixa.garantir(agente)
    retorno = caixa._docker(["docker", "exec", "-i", nome, "python", "/opt/sentury/caixa_cdp.py"],
                            input=json.dumps(action.para_dict(), ensure_ascii=False) + "\n", timeout=40)
    if retorno.returncode:
        raise RuntimeError("O navegador da caixa não respondeu.")
    resultado = json.loads(retorno.stdout)
    if not resultado.get("ok"):
        raise RuntimeError(resultado.get("erro") or "Falha no navegador da caixa.")
    return resultado


class Sessao:
    def __init__(self, agente, task_id):
        self.agente = agente
        self.session_id = f"caixa:{agente.nome}:{task_id}"
        self._epoch = 0
        self._encerrada = False

    def esta_viva(self):
        return not self._encerrada

    async def execute(self, action):
        from ..tools.web import validar_url

        if action.tipo == "navegar":
            validar_url(str(action.argumentos.get("url") or ""), rede_interna=False)
        agente = registro.carregar(self.agente.nome) or self.agente
        from .controle_da_tela import passo

        async with passo(agente.nome):
            resultado = await asyncio.to_thread(executar, agente, action)
        self._epoch += 1
        return Observation("browser", resultado.get("dados"), epoch=self._epoch,
                           interativa=action.tipo in ("clicar", "digitar", "rolar", "navegar"),
                           metadados={"residente": agente.nome, "modo": "caixa", "screenshot": bool(resultado.get("screenshot")),
                                      "aviso": resultado.get("aviso", "")})


class Provedor(BrowserProvider):
    def __init__(self, agente):
        self.agente = agente
        self.sessoes = {}

    @property
    def name(self):
        return caixa.nomes(self.agente)[0]

    def is_available(self):
        return bool(shutil.which("docker"))

    def create_session(self, task_id):
        sessao = Sessao(self.agente, task_id)
        self.sessoes[sessao.session_id] = sessao
        return sessao

    def close_session(self, session_id):
        from ..tools.browser_contracts import Action

        sessao = self.sessoes.pop(session_id, None)
        if sessao is None:
            return False
        executar(sessao.agente, Action("encerrar", {}))
        sessao._encerrada = True
        return True

    def emergency_cleanup(self, session_id):
        self.close_session(session_id)


async def despachar(args, state):
    from .escopo import agente_do_turno
    from ..tools import browser_registry
    from ..tools.browser_contracts import Action

    agente = agente_do_turno()
    provedor = Provedor(agente)
    if browser_registry.resolver(provedor.name) is None:
        browser_registry.registrar(provedor)
    resultado = await browser_registry.despachar(Action.de_argumentos(args), state, provider_name=provedor.name)
    return {**resultado, "modo": "caixa", "residente": agente.nome}
