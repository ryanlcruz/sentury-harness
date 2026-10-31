"""A HQ cria caixas sem compartilhar ambiente, socket ou disco de outros residentes."""
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading

from .manifesto import NOME_VALIDO

logger = logging.getLogger(__name__)
_TRAVAS = {}
_LOCK = threading.Lock()


def nomes(agente):
    if not NOME_VALIDO.fullmatch(agente.nome):
        raise ValueError("Nome de residente inválido para a caixa.")
    geracao = hashlib.sha256(f"{agente.nome}:{agente.criado_em}".encode()).hexdigest()[:16]
    return f"sentury-caixa-{agente.nome}-{geracao}", f"sentury-workspace-{agente.nome}-{geracao}"


def montagem(volume):
    if not volume.startswith("sentury-workspace-") or not all(c.isalnum() or c == "-" for c in volume):
        raise ValueError("A caixa só monta o volume próprio, nunca um caminho ou socket do host.")
    return f"type=volume,source={volume},target=/workspace"


def comando_criar(agente, imagem, *, rede="none", proxy=""):
    nome, volume = nomes(agente)
    from .rede_da_caixa import nome_da_rede

    if rede != (nome_da_rede(agente) if agente.rede == "internet" else "none"):
        raise ValueError("A caixa usa apenas a rede própria declarada no manifesto.")
    ambiente = []
    if proxy:
        ambiente = [item for chave in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
                    for item in ("--env", f"{chave}={proxy}")]
    return ["docker", "run", "-d", "--name", nome, "--label", "sentury.servico=caixa",
            "--label", f"sentury.residente={agente.nome}", "--label", "sentury.politica=1",
            "--read-only", "--network", rede, "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--user", "1000:1000", "--cpus", "1", "--memory", "512m", "--memory-swap", "512m",
            "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
            "--mount", montagem(volume), "--workdir", "/workspace", "--log-opt", "max-size=5m",
            "--log-opt", "max-file=2", *ambiente, imagem, "sleep", "infinity"]


def _docker(argv, **kwargs):
    from ..exec.ambiente import bandeiras_de_processo
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=kwargs.pop("timeout", 20), **bandeiras_de_processo(), **kwargs)


def disponivel():
    if not shutil.which("docker"):
        return False
    try:
        return _docker(["docker", "info", "--format", "{{.ServerVersion}}"]).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _segura(dados, agente, imagem, rede="none", proxy=""):
    _, volume = nomes(agente)
    conf, host = dados.get("Config", {}), dados.get("HostConfig", {})
    mounts = [m for m in dados.get("Mounts", []) if m.get("Type") != "tmpfs"]
    tmpfs = [m for m in dados.get("Mounts", []) if m.get("Type") == "tmpfs"]
    return (conf.get("Image") == imagem and conf.get("User") == "1000:1000"
            and conf.get("Labels", {}).get("sentury.politica") == "1"
            and conf.get("Labels", {}).get("sentury.residente") == agente.nome
            and host.get("ReadonlyRootfs") is True and host.get("NetworkMode") == rede
            and host.get("Privileged") is not True and "ALL" in host.get("CapDrop", [])
            and not host.get("CapAdd") and "no-new-privileges:true" in host.get("SecurityOpt", [])
            and host.get("PidMode", "") != "host" and host.get("IpcMode", "") != "host"
            and not host.get("Devices") and not host.get("PortBindings")
            and all(m.get("Destination") == "/tmp" for m in tmpfs)
            and set(host.get("Tmpfs") or {}) <= {"/tmp"}
            and _limites_seguros(host, mounts, volume)
            and _rede_segura(dados, agente, rede, proxy))


def _rede_segura(dados, agente, rede, proxy):
    if agente.rede == "nenhuma":
        conexoes = dados.get("NetworkSettings", {}).get("Networks", {})
        return rede == "none" and set(conexoes) <= {"none"}
    from .rede_da_caixa import nome_da_rede

    conexoes = dados.get("NetworkSettings", {}).get("Networks", {})
    ambiente = dados.get("Config", {}).get("Env", [])
    return rede == nome_da_rede(agente) and set(conexoes) == {rede} and all(
        f"{chave}={proxy}" in ambiente for chave in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"))


def _volume_seguro(volume):
    visto = _docker(["docker", "volume", "inspect", volume])
    if visto.returncode:
        return
    dados = json.loads(visto.stdout)[0]
    if dados.get("Driver") != "local" or dados.get("Options"):
        raise ValueError("O volume da caixa usa uma montagem externa. Crie um volume local sem opções.")


def _limites_seguros(host, mounts, volume):
    return (0 < host.get("Memory", 0) <= 512 * 1024 * 1024
            and 0 < host.get("MemorySwap", 0) <= 512 * 1024 * 1024
            and 0 < host.get("NanoCpus", 0) <= 1_000_000_000
            and 0 < host.get("PidsLimit", 0) <= 128
            and len(mounts) == 1 and mounts[0].get("Type") == "volume"
            and mounts[0].get("Name") == volume and mounts[0].get("Destination") == "/workspace")


def garantir(agente):
    nome, volume = nomes(agente)
    _volume_seguro(volume)
    imagem = os.environ.get("SENTURY_CAIXA_IMAGE", "sentury-caixa:local")
    rede, proxy = "none", ""
    if agente.rede == "internet":
        from .rede_da_caixa import garantir as garantir_rede, PORTA

        rede, ip_proxy = garantir_rede(agente)
        proxy = f"http://{ip_proxy}:{PORTA}"
    visto = _docker(["docker", "inspect", nome])
    if visto.returncode == 0:
        dados = json.loads(visto.stdout)[0]
        if dados.get("Config", {}).get("Labels", {}).get("sentury.residente") != agente.nome:
            raise ValueError("Já existe um container com esse nome que não pertence ao residente.")
        if _segura(dados, agente, imagem, rede, proxy):
            if not dados.get("State", {}).get("Running"):
                iniciado = _docker(["docker", "start", nome])
                if iniciado.returncode:
                    raise RuntimeError("Não consegui iniciar a caixa do residente.")
            if agente.rede == "internet":
                from .rede_da_caixa import iniciar_proxy
                iniciar_proxy(agente)
            return nome
        removido = _docker(["docker", "rm", "-f", nome])
        if removido.returncode:
            raise RuntimeError("Não consegui recriar a caixa do residente.")
    criado = _docker(comando_criar(agente, imagem, rede=rede, proxy=proxy), timeout=60)
    if criado.returncode:
        raise RuntimeError("Não consegui criar a caixa. Confira a imagem configurada e o Docker da HQ.")
    if agente.rede == "internet":
        from .rede_da_caixa import iniciar_proxy
        iniciar_proxy(agente)
    return nome


def _executar(agente, op, args):
    with _LOCK:
        trava = _TRAVAS.setdefault(nomes(agente)[0], threading.Lock())
    with trava:
        nome = garantir(agente)
        programa = Path(__file__).with_name("caixa_exec.py").read_text(encoding="utf-8")
        pedido = json.dumps({"op": op, "args": args}, ensure_ascii=False)
        if len(pedido.encode()) > 1_000_000:
            return {"ok": False, "erro": "O pedido passa do teto de entrada da caixa."}
        prazo = min(300, max(1, float(args.get("timeout") or 120))) + 10
        retorno = _docker(["docker", "exec", "-i", nome, "python", "-c", programa], input=pedido, timeout=prazo)
        if retorno.returncode:
            return {"ok": False, "erro": "A execução na caixa foi interrompida.", "modo": "caixa"}
        dados = json.loads(retorno.stdout)
        return {**dados, "modo": "caixa", "residente": agente.nome}


async def tentar(op, args):
    from .escopo import agente_do_turno
    agente = agente_do_turno()
    if not agente or not op:
        return None, ""
    if not await asyncio.to_thread(disponivel):
        # Na HQ em container, rodar "local" é rodar ao lado do docker.sock: o
        # residente viraria dono da máquina. Ali, sem caixa não roda nada.
        from .destino import caixa_obrigatoria

        if caixa_obrigatoria():
            return {"ok": False, "modo": "caixa", "erro": (
                "a caixa deste residente não está disponível, e nesta HQ nada roda fora dela; "
                "a ferramenta não foi executada; considere outra ferramenta de estado da HQ "
                "ou peça à pessoa que disponibilize a caixa")}, ""
        aviso = "Docker indisponível: esta ferramenta usa o modo local, sem isolamento de caixa."
        logger.warning(aviso)
        return None, aviso
    try:
        return await asyncio.to_thread(_executar, agente, op, args), ""
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "erro": str(exc), "modo": "caixa"}, ""


def receber_anexo(agente, origem, destino):
    """Ingresso pedido pela pessoa, sem montar a pasta de recebidos da HQ na caixa."""
    import base64

    nome = garantir(agente)
    programa = Path(__file__).with_name("caixa_receber.py").read_text(encoding="utf-8")
    retorno = _docker(["docker", "exec", "-i", nome, "python", "-c", programa, destino],
                      input=base64.b64encode(origem.read_bytes()).decode("ascii"))
    if retorno.returncode:
        raise ValueError("Não consegui copiar o anexo para a caixa do residente.")
