"""A pessoa controla entre ações; o worker retoma com a observação atual."""
import asyncio
from contextlib import asynccontextmanager
import json
import weakref

from . import registro, tarefas

_LACOS = weakref.WeakKeyDictionary()
MOTIVO = "pessoa no controle"


def _arquivo(nome):
    return registro.pasta_do(nome) / "controle.json"


def estado(nome):
    try:
        return json.loads(_arquivo(nome).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"pessoa": False, "geracao": 0, "tarefa": "", "fatos": ""}


def _gravar(nome, dados):
    alvo = _arquivo(nome)
    tmp = alvo.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    tmp.replace(alvo)


def _sinais(nome):
    lacos = _LACOS.setdefault(asyncio.get_running_loop(), {})
    if nome not in lacos:
        evento = asyncio.Event()
        if not estado(nome).get("pessoa"):
            evento.set()
        lacos[nome] = asyncio.Lock(), evento
    return lacos[nome]


@asynccontextmanager
async def passo(nome):
    trava, evento = _sinais(nome)
    while True:
        await evento.wait()
        await trava.acquire()
        if not estado(nome).get("pessoa"):
            break
        trava.release()
        evento.clear()
    try:
        yield
    finally:
        trava.release()


async def assumir(nome):
    if registro.carregar(nome) is None:
        raise ValueError("O residente não existe.")
    trava, evento = _sinais(nome)
    async with trava:
        dados = estado(nome)
        if dados.get("pessoa"):
            return dados
        rodando = tarefas.listar(nome, (tarefas.RODANDO,))
        identidade = rodando[0].id if rodando else ""
        dados = {**dados, "pessoa": True, "tarefa": identidade, "geracao": dados["geracao"] + 1}
        _gravar(nome, dados)
        evento.clear()
        if identidade:
            tarefas.esperar(identidade, MOTIVO)
        return dados


async def devolver(nome, fatos):
    from . import worker

    trava, evento = _sinais(nome)
    async with trava:
        dados = estado(nome)
        if not dados.get("pessoa"):
            return dados
        dados = {**dados, "pessoa": False, "fatos": str(fatos)[:6000]}
        _gravar(nome, dados)
        tarefa = tarefas.carregar(dados["tarefa"]) if dados.get("tarefa") else None
        if tarefa and tarefa.estado == tarefas.ESPERANDO and tarefa.motivo == MOTIVO:
            tarefas.devolver_a_fila(tarefa.id, dados["fatos"], por="pessoa_controle")
            if worker.acordado(nome):
                tarefas.retomar_controle(tarefa.id)
            else:
                worker.acordar(nome)
        evento.set()
        return dados


async def esperar_devolucao(nome):
    _, evento = _sinais(nome)
    await evento.wait()


async def rodar(agente, tarefa, executar):
    await esperar_devolucao(agente.nome)
    geracao = estado(agente.nome)["geracao"]
    resultado = await executar(agente, tarefa)
    while True:
        await esperar_devolucao(agente.nome)
        atual = estado(agente.nome)
        if atual["geracao"] == geracao:
            return resultado
        geracao = atual["geracao"]
        tarefa = tarefas.carregar(tarefa.id)
        if tarefa is None or tarefa.estado != tarefas.RODANDO:
            return {"controle_interrompido": True}
        custo = (resultado.get("telemetry") or {}).get("custo_usd") if isinstance(resultado, dict) else None
        tarefas.registrar_custo(tarefa.id, custo)
        from . import orcamento

        if motivo := orcamento.corte(agente):
            tarefas.esperar(tarefa.id, motivo)
            return {"controle_interrompido": True}
        resultado = await executar(agente, tarefa)
