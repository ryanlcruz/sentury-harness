"""Execução de comandos, com o mínimo de poder necessário.

Três decisões que valem a pena estarem escritas, porque cada uma protege algo
específico:

1. **Desligado por padrão** (`SENTURY_SHELL`). Uma capacidade de execução que
   nasce ligada é ligada por descuido, não por decisão.
2. **Sem shell interpretado.** O comando é dividido em argumentos e executado
   direto. Sem `shell=True` não existe pipe, redirecionamento, `&&` nem
   expansão de variável: que é como um comando aparentemente inofensivo vira
   outro.
3. **Lista de permissão, não lista de bloqueio.** Bloquear `rm` deixa passar
   `find -delete`. Só o que está declarado roda; o resto é recusado com o
   motivo.

Escrita fica atrás de `permitir_escrita`, que quem chama só liga quando houve
aprovação explícita naquele passo.
"""
from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
import time
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..exec.contrato import CodigoDeErro

logger = logging.getLogger(__name__)

# A política mora em sentury/config/shell.yaml, não aqui: o que pode rodar
# muda por instalação, por cliente e por sistema, e não deve exigir release.
# Este módulo só lê e aplica.
_CONFIG: Dict[str, Any] = {}
_CONFIG_FONTE = None
_CONFIG_TRAVA = threading.RLock()


def caminho_da_politica() -> Path:
    """Arquivo de política. `SENTURY_SHELL_CONFIG` aponta para outro."""
    escolhido = os.environ.get("SENTURY_SHELL_CONFIG")
    if escolhido:
        return Path(escolhido).expanduser()
    from ..policies import pasta_de_config

    return pasta_de_config() / "shell.yaml"


def _padrao() -> Dict[str, Any]:
    """Sem arquivo legível, a política é a mais fechada possível: nada roda."""
    return {
        "leitura": {}, "escrita": {}, "executa": {}, "negados": [],
        "alvos_proibidos": [], "pastas_proibidas": [],
        "limites": {"saida_chars": 20_000, "timeout_padrao_s": 60},
        "com_subcomando": [], "opcoes_com_valor": {}, "consulta_de_versao": {},
        "confirmar_na_hora": {}, "script_que_apaga": [],
    }


def politica(recarregar: bool = False) -> Dict[str, Any]:
    with _CONFIG_TRAVA:
        return _ler_politica(recarregar)


def _ler_politica(recarregar: bool) -> Dict[str, Any]:
    global _CONFIG, _CONFIG_FONTE
    caminho = caminho_da_politica()
    try:
        estado = caminho.stat()
        fonte = (str(caminho.resolve()), estado.st_mtime_ns, estado.st_size)
    except OSError:
        fonte = (str(caminho.resolve()), None, None)
    if _CONFIG and not recarregar and fonte == _CONFIG_FONTE:
        return _CONFIG
    # A política anterior não vale quando a pasta ou o arquivo muda.
    _CONFIG_FONTE = fonte
    try:
        import yaml

        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        # Política ilegível não vira política permissiva: vira nenhuma.
        logger.warning("Politica de shell indisponivel (%s): nada sera executado", exc)
        _CONFIG = _padrao()
        return _CONFIG
    base = _padrao()
    base.update({chave: dados.get(chave, valor) for chave, valor in base.items()})
    _CONFIG = base
    return _CONFIG


def _pasta_de_trabalho() -> Path:
    from .arquivos import raiz_de_trabalho

    return raiz_de_trabalho()


def ambiente() -> Dict[str, Any]:
    """Onde o comando vai rodar.

    Sem isto o agente supunha Linux e mandava `ls` onde so existe `dir`. Nada
    e fixo: o sistema, o diretorio e o comando de listar sao descobertos na
    maquina em que o processo esta.
    """
    import platform

    from ..exec.ambiente import interpretadores

    windows = os.name == "nt"
    tem_ls = bool(shutil.which("ls"))
    return {
        "sistema": platform.system() or ("Windows" if windows else "desconhecido"),
        "windows": windows,
        "listar": "ls" if tem_ls else ("dir" if windows else "ls"),
        "separador": os.sep,
        # A mesma pasta das ferramentas de arquivo: a pasta de onde o servidor
        # subiu costuma ser a instalação, e um comando ali mexe no próprio Sentury.
        "diretorio": str(_pasta_de_trabalho()),
        "shell_ligado": False,
        # Sem isto o agente supunha o que tinha: mandava `powershell` no Linux e
        # descobria a falta depois de gastar um turno.
        "interpretadores": interpretadores(),
    }


def comandos_de_leitura() -> Dict[str, Any]:
    return politica().get("leitura") or {}


def comandos_de_escrita() -> Dict[str, Any]:
    return politica().get("escrita") or {}


def comandos_de_execucao() -> Dict[str, Any]:
    """Interpretadores. Nunca rodam como leitura; a permissao e por conteudo."""
    return politica().get("executa") or {}


def limite_de_saida() -> int:
    return int((politica().get("limites") or {}).get("saida_chars") or 20_000)


from ..exec.ambiente import bandeiras_de_processo, preparar_env
from ..exec.saida import preparar


class ComandoRecusado(Exception):
    """O comando nao passou na lista de permissao."""


def _binario(nome: str) -> Optional[str]:
    return shutil.which(nome)


def _sem_aspas(parte: str) -> str:
    if len(parte) >= 2 and parte[0] == parte[-1] and parte[0] in "\"'":
        return parte[1:-1]
    return parte


def _recusar_alvo_sensivel(argumento: str) -> None:
    """Barra o ALVO, nao o comando: ler segredo com um comando permitido
    continua sendo ler segredo, e a saida vai parar no historico."""
    caminho = str(argumento or "").strip().strip("\"'").replace("\\", "/").lower()
    if not caminho or caminho.startswith("-"):
        return
    nome = caminho.rsplit("/", 1)[-1]
    if any(nome == alvo or nome.startswith(alvo) or nome.endswith(alvo) for alvo in (politica().get("alvos_proibidos") or [])):
        raise ComandoRecusado(f"'{nome}' guarda credencial; leitura recusada")
    partes = caminho.split("/")
    for pasta in (politica().get("pastas_proibidas") or []):
        if pasta in partes:
            raise ComandoRecusado(f"a pasta '{pasta}' guarda credencial; acesso recusado")


def partes_do_comando(comando: str) -> List[str]:
    bruto = str(comando or "").strip()
    if os.name != "nt":
        return shlex.split(bruto)
    # No Windows: aspas como no POSIX, barra invertida como caractere. O modo
    # posix=False cortava aspas no meio do argumento (`--format="%h %s"` virava
    # dois) e o posix=True comia a barra dos caminhos.
    lexer = shlex.shlex(bruto, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    lexer.commenters = ""
    return list(lexer)


def verbo(partes: List[str]) -> str:
    """O subcomando, pulando opcoes e o valor das que recebem um.

    Em `git -C <pasta> log` o verbo e `log`, nao a pasta. A permissao e dada por
    verbo: aprovar `commit` numa pasta nao aprova `push` nela.
    """
    if not partes:
        return ""
    programa = Path(partes[0]).name.lower()
    programa = programa[:-4] if programa.endswith(".exe") else programa
    com_valor = set((politica().get("opcoes_com_valor") or {}).get(programa) or [])
    pular = False
    for parte in partes[1:]:
        if pular:
            pular = False
            continue
        if parte.startswith("-"):
            pular = parte in com_valor
            continue
        return parte
    return ""


# So mexem na saida de erro: nao escrevem arquivo nem trocam o que roda.
_REDIRECIONAMENTO_INOFENSIVO = ("2>&1", "2>/dev/null", "2>$null", "2>nul", "2>NUL")


def composto(comando: str) -> Optional[Tuple[List[str], bool]]:
    """Trechos de um comando com `|`, `&&`, `||` ou `;`, e se ha algo arriscado.

    Arriscado e o que a politica por trecho nao enxerga: redirecionamento
    (`>`, `<`), substituicao (`$(...)`, crase), `&` solto e chave fora de aspas,
    que no PowerShell e bloco de codigo e no `find -exec` e o alvo do comando.
    Devolve `None` para comando simples, que segue o caminho de sempre.
    Respeita aspas.
    """
    texto = str(comando or "")
    for inofensivo in _REDIRECIONAMENTO_INOFENSIVO:
        texto = texto.replace(inofensivo, " ")
    trechos, atual, aspa, arriscado, i = [], [], "", False, 0
    while i < len(texto):
        c = texto[i]
        dois = texto[i:i + 2]
        if aspa:
            atual.append(c)
            if c == aspa:
                aspa = ""
        elif c in "\"'":
            aspa = c
            atual.append(c)
        elif dois in ("&&", "||"):
            trechos.append("".join(atual)); atual = []; i += 1
        elif c in "|;":
            trechos.append("".join(atual)); atual = []
        elif c in "<>`&{" or dois == "$(":
            arriscado = True
            atual.append(c)
        else:
            atual.append(c)
        i += 1
    trechos.append("".join(atual))
    trechos = [t.strip() for t in trechos if t.strip()]
    if len(trechos) <= 1 and not arriscado:
        return None
    return trechos, arriscado


# Cmdlet e Verbo-Nome com iniciais maiusculas (`Get-ChildItem`); `apt-get` e
# `docker-compose` sao minusculos e ficam no shell padrao.
_CMDLET = re.compile(r"^[A-Z][a-z]+-[A-Z][A-Za-z]+$")
_DIALETOS = {"bash": "bash", "sh": "bash", "powershell": "powershell",
             "pwsh": "powershell", "ps": "powershell", "ps1": "powershell"}


def dialeto(comando: str, pedido: str = "") -> str:
    """O shell em que o comando roda: o que foi pedido, o PowerShell quando o
    comando foi escrito nele, ou o padrao da maquina."""
    from .script import linguagem_padrao

    escolhido = _DIALETOS.get(str(pedido or "").strip().lower())
    if escolhido:
        return escolhido
    texto = str(comando or "")
    trechos = (composto(texto) or ([texto], False))[0]
    # `(Get-Content f).Count`: o cmdlet pode vir depois de um parentese.
    primeiros = [(t.split() or [""])[0].lstrip("(") for t in trechos]
    if "$env:" in texto.lower() or any(_CMDLET.match(p) for p in primeiros):
        return "powershell"
    return linguagem_padrao()


def validar(comando: str, permitir_escrita: bool = False) -> List[str]:
    """Devolve os argumentos quando o comando e permitido; levanta se nao."""
    bruto = str(comando or "").strip()
    if not bruto:
        raise ComandoRecusado("comando vazio")

    partes = partes_do_comando(bruto)
    if not partes:
        raise ComandoRecusado("comando vazio")

    # Metacaracteres so teriam sentido com shell interpretado, que nao usamos:
    # se aparecem, o pedido esperava um comportamento que nao existe aqui.
    for parte in partes:
        if any(c in parte for c in "|;&><`$"):
            raise ComandoRecusado(
                f"'{parte}' usa metacaractere de shell; aqui o comando roda sem shell"
            )

    # Parentese de agrupamento (`(Get-Content f).Count`, subshell do bash) nao
    # muda o programa que roda.
    programa = Path(partes[0].lstrip("(")).name.lower()
    programa = programa[:-4] if programa.endswith(".exe") else programa
    if programa in set(politica().get("negados") or []):
        raise ComandoRecusado(f"'{programa}' nao e permitido em nenhum modo")

    for alvo in partes[1:]:
        _recusar_alvo_sensivel(alvo)

    versao = (politica().get("consulta_de_versao") or {}).get(programa) or []
    if len(partes) == 2 and partes[1] in versao:
        return partes

    tabelas = [comandos_de_leitura()]
    if permitir_escrita:
        tabelas += [comandos_de_escrita(), comandos_de_execucao()]
    # Junta os subcomandos de TODAS as tabelas aplicaveis antes de decidir: o
    # mesmo programa aparece em leitura e escrita (git log x git commit), e
    # decidir na primeira tabela recusava a escrita ja aprovada.
    conhecido = False
    permitidos: set = set()
    for tabela in tabelas:
        if programa not in tabela:
            continue
        conhecido = True
        subcomandos = tabela[programa]
        if subcomandos is None:
            return partes
        permitidos |= set(subcomandos)

    if conhecido:
        alvo = verbo(partes)
        if alvo in permitidos:
            return partes
        raise ComandoRecusado(
            f"'{programa} {alvo}' nao esta na lista; permitidos: {', '.join(sorted(permitidos))}"
        )

    if programa in comandos_de_escrita():
        raise ComandoRecusado(f"'{programa}' altera arquivos e exige aprovacao no passo")
    if programa in comandos_de_execucao():
        raise ComandoRecusado(
            f"'{programa}' roda codigo e exige aprovacao do conteudo do script"
        )
    raise ComandoRecusado(f"'{programa}' nao esta na lista de comandos permitidos")


_DICA_DO_SHELL: Optional[str] = None
# Erro silencioso comum: a contagem sai menor e parece certa.
_CONTAGEM_NO_POWERSHELL = (
    " No PowerShell, `Measure-Object -Line` pula linhas em branco; para contar todas as"
    " linhas, `(Get-Content arquivo).Count`."
)


def dica_do_shell() -> str:
    """O shell que roda de fato e a busca de texto que existe nesta maquina.

    Vai na descricao da ferramenta: sem ela, o modelo supoe o shell e a busca
    de texto, e o que supoe pode nao existir aqui.
    """
    global _DICA_DO_SHELL
    if _DICA_DO_SHELL is None:
        from .script import linguagem_padrao

        nome = linguagem_padrao()
        busca = next((b for b in ("rg", "grep") if shutil.which(b)), "")
        if nome == "bash":
            dica = f" Para contar ou achar texto: `{busca} -c`." if busca else ""
            if os.name == "nt":
                dica += (" PowerShell tambem roda: cmdlet vai para ele, ou passe `shell: powershell`."
                         + _CONTAGEM_NO_POWERSHELL)
            _DICA_DO_SHELL = f"Nesta maquina o shell padrao e bash.{dica}"
        elif nome == "powershell":
            _DICA_DO_SHELL = ("Nesta maquina o shell e PowerShell (sem bash). Para contar ou achar texto: "
                              "Select-String." + _CONTAGEM_NO_POWERSHELL)
        else:
            _DICA_DO_SHELL = ""
    return _DICA_DO_SHELL


def so_leitura(comando: str) -> bool:
    """O comando inteiro so le? Simples pela politica; composto, trecho por trecho.

    A pre-checagem do plano e o shell usam a mesma regra.
    """
    partes = composto(comando)
    if partes is None:
        return _e_leitura(comando)
    trechos, arriscado = partes
    return not arriscado and all(_e_leitura(t) for t in trechos)


def _e_leitura(trecho: str) -> bool:
    try:
        validar(trecho, permitir_escrita=False)
        return True
    except ComandoRecusado:
        return False


def executar(
    comando: str,
    *,
    diretorio: Optional[str] = None,
    timeout: float = 60.0,
    permitir_escrita: bool = False,
    habilitado: bool = False,
    session_id: str = "",
    segundo_plano: bool = True,
    ao_linha: Optional[Callable[[str, str], None]] = None,
    shell: str = "",
) -> Dict[str, Any]:
    """Roda um comando permitido e devolve saida, codigo e duracao.

    Leitura roda direto. O que ALTERA passa pelo registro de permissao: se
    ainda nao foi autorizado, volta `precisa_perguntar` para a interface
    levantar a pergunta: o agente nao decide isso sozinho.
    """
    if not habilitado:
        return {
            "ok": False,
            "recusado": True,
            "motivo": "execucao de comandos desligada (SENTURY_SHELL)",
            "comando": comando,
            "codigo_erro": CodigoDeErro.DESLIGADO,
        }
    # O que nunca roda vem ANTES de qualquer permissao, inclusive da ampla, e
    # antes de separar leitura de escrita: `powershell -Command "iex ..."` e
    # recusado pela allowlist como escrita, mas um interpretador permitido com
    # argumento perigoso passaria pelos dois caminhos. Ver exec/politica.py.
    from ..exec.politica import recusa_sem_apelacao

    motivo_absoluto = recusa_sem_apelacao(comando, checar_alvo=False)
    if motivo_absoluto:
        return {
            "ok": False, "recusado": True, "motivo": motivo_absoluto,
            "comando": comando, "codigo_erro": CodigoDeErro.RECUSADO_POLITICA,
        }

    from .script import executar_script, linguagens_disponiveis

    escolhido = dialeto(comando, shell)

    # Pipe e `&&`: cada trecho pela politica. Tudo leitura roda no shell sem
    # perguntar; o resto vira script com permissao pelo conteudo. Cmdlet nao e
    # executavel, entao comando de PowerShell sem binario vai pelo mesmo caminho.
    partes_do_composto = composto(comando)
    primeiro = (str(comando).split() or [""])[0]
    if partes_do_composto is None and escolhido == "powershell" and _binario(primeiro) is None:
        partes_do_composto = ([str(comando).strip()], False)
    if partes_do_composto is not None:
        disponiveis = linguagens_disponiveis()
        if escolhido not in disponiveis:
            return {
                "ok": False, "recusado": True, "comando": comando,
                "motivo": f"{escolhido} nao existe nesta maquina; disponiveis: {', '.join(disponiveis)}",
                "codigo_erro": CodigoDeErro.NAO_ENCONTRADO,
            }
        trechos, arriscado = partes_do_composto
        # Negado vale em qualquer modo: a permissao por conteudo do script nao
        # pode aprovar um `rm` escondido depois de um `ls;`.
        negados = set(politica().get("negados") or [])
        for trecho in trechos:
            nome = Path((partes_do_comando(trecho) or [""])[0].lstrip("(")).name.lower()
            nome = nome[:-4] if nome.endswith(".exe") else nome
            if nome in negados:
                return {
                    "ok": False, "recusado": True, "comando": comando,
                    "motivo": f"'{nome}' nao e permitido em nenhum modo",
                    "codigo_erro": CodigoDeErro.RECUSADO_POLITICA,
                }
        leitura = not arriscado and all(_e_leitura(t) for t in trechos)
        return executar_script(
            comando, escolhido, diretorio=diretorio, timeout=timeout,
            habilitado=habilitado, session_id=session_id, leitura_validada=leitura,
        )

    # Leitura sempre pode; para o resto, quem manda e o registro de permissao.
    try:
        validar(comando, permitir_escrita=False)
        so_leitura = True
    except ComandoRecusado:
        so_leitura = False

    if not so_leitura:
        from ..exec.politica import avaliar
        from ..exec.criticas import no_diretorio

        comando_para_permissao = no_diretorio(comando, diretorio or "")
        decisao = avaliar(comando_para_permissao, session_id)
        if decisao["precisa_perguntar"]:
            return {
                "ok": False,
                "precisa_permissao": True,
                "chave": decisao["chave"],
                "so_desta_vez": bool(decisao.get("so_desta_vez")),
                "motivo": decisao["motivo"],
                "comando": comando_para_permissao,
                "codigo_erro": CodigoDeErro.PRECISA_PERMISSAO,
            }
        if not decisao["permitido"]:
            return {
                "ok": False, "recusado": True, "motivo": decisao["motivo"],
                "comando": comando, "codigo_erro": CodigoDeErro.RECUSADO_POLITICA,
            }
        permitir_escrita = True

    try:
        partes = validar(comando, permitir_escrita=permitir_escrita)
    except ComandoRecusado as exc:
        motivo = str(exc)
        codigo_erro = (
            CodigoDeErro.ALVO_SENSIVEL if "credencial" in motivo.lower()
            else CodigoDeErro.RECUSADO_POLITICA
        )
        return {
            "ok": False, "recusado": True, "motivo": motivo,
            "comando": comando, "codigo_erro": codigo_erro,
        }

    raiz = Path(diretorio or _pasta_de_trabalho()).resolve()
    teto = limite_de_saida()

    # ``mkdir`` e comando interno do cmd.exe no Windows, nao um executavel.
    # Como esta ferramenta deliberadamente nao usa shell interpretado, chamar
    # subprocess falharia mesmo depois da pessoa autorizar a escrita. Executa
    # essa operacao especifica pela API de arquivos, preservando a mesma
    # validacao e o mesmo registro de permissao usados acima.
    programa = Path(partes[0]).name.lower()
    programa = programa[:-4] if programa.endswith(".exe") else programa
    if os.name == "nt" and programa in {"mkdir", "md"}:
        alvos = [item for item in partes[1:] if not item.startswith("-")]
        if not alvos:
            return {"ok": False, "comando": comando, "motivo": "mkdir exige um caminho"}
        inicio = time.time()
        try:
            for item in alvos:
                caminho = Path(item)
                if not caminho.is_absolute():
                    caminho = raiz / caminho
                caminho.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            return {
                "ok": False,
                "comando": comando,
                "motivo": f"{type(exc).__name__}: {exc}",
                "duracao_ms": int((time.time() - inicio) * 1000),
                "diretorio": str(raiz),
            }
        return {
            "ok": True,
            "comando": comando,
            "codigo": 0,
            "saida": "",
            "erro": "",
            "truncado": False,
            "duracao_ms": int((time.time() - inicio) * 1000),
            "diretorio": str(raiz),
        }

    if _binario(partes[0]) is None and not Path(partes[0]).exists():
        return {
            "ok": False, "recusado": True,
            "motivo": f"'{partes[0]}' nao encontrado", "comando": comando,
            "codigo_erro": CodigoDeErro.NAO_ENCONTRADO,
        }

    if not segundo_plano:
        # Caminho antigo, para quem precisa de bloqueio de verdade.
        inicio = time.time()
        try:
            processo = subprocess.run(
                partes, cwd=str(raiz), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=max(1.0, float(timeout)),
                check=False, shell=False, stdin=subprocess.DEVNULL,
                env=preparar_env(), **bandeiras_de_processo(),
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False, "comando": comando, "timeout": True,
                "motivo": f"passou de {int(timeout)}s e foi encerrado",
                "duracao_ms": int((time.time() - inicio) * 1000),
                "codigo_erro": CodigoDeErro.TIMEOUT,
            }
        except OSError as exc:
            return {
                "ok": False, "comando": comando,
                "motivo": f"{type(exc).__name__}: {exc}",
                "codigo_erro": CodigoDeErro.FALHA_INFRA,
            }
        stdout, cortou_saida = preparar(processo.stdout or "", teto)
        stderr, cortou_erro = preparar(processo.stderr or "", teto)
        return {
            "ok": processo.returncode == 0, "comando": comando,
            "codigo": processo.returncode,
            "saida": stdout,
            "erro": stderr,
            "truncado": cortou_saida or cortou_erro,
            "duracao_ms": int((time.time() - inicio) * 1000),
            "diretorio": str(raiz),
        }

    # O limite controla a espera do agente, não a duração do processo.
    # Comandos demorados continuam disponíveis para consulta posterior.
    from . import processos

    try:
        pid = processos.iniciar(partes, diretorio=str(raiz), comando=comando, teto_saida=teto,
                                ao_linha=ao_linha)
    except OSError as exc:
        return {
            "ok": False, "comando": comando,
            "motivo": f"{type(exc).__name__}: {exc}",
            "codigo_erro": CodigoDeErro.FALHA_INFRA,
        }

    resultado = processos.esperar(pid, timeout=max(1.0, float(timeout)))
    if resultado.get("rodando"):
        return {
            "ok": True,
            "comando": comando,
            "em_segundo_plano": True,
            "id": pid,
            "motivo": (
                f"passou de {int(timeout)}s e continua rodando em segundo plano. "
                f"Consulte com processos(acao='ver', id='{pid}') quando quiser o resultado."
            ),
            "saida_parcial": resultado.get("saida", "")[-2000:],
            "duracao_ms": resultado.get("duracao_ms"),
            "diretorio": str(raiz),
            "linhas": resultado.get("linhas", []),
            "linhas_cortadas": resultado.get("linhas_cortadas", 0),
        }
    return {
        "ok": resultado.get("codigo") == 0,
        "comando": comando,
        "codigo": resultado.get("codigo"),
        "saida": resultado.get("saida", ""),
        "erro": resultado.get("erro", ""),
        "truncado": resultado.get("truncado", False),
        "duracao_ms": resultado.get("duracao_ms"),
        "diretorio": str(raiz),
        "id": pid,
        "linhas": resultado.get("linhas", []),
        "linhas_cortadas": resultado.get("linhas_cortadas", 0),
    }

def agora() -> List[str]:
    """Quando e agora: dia da semana, data, hora e fuso.

    Irma de `ambiente()`: uma diz ONDE o comando roda, a outra diz QUANDO
    o turno acontece. As duas entram no contexto de todo turno, e nenhuma
    cabe no prompt fixo porque mudam.

    A data ja chegava ao PLANEJADOR, e so ela. Faltavam tres coisas:

    - o RESPONDEDOR nao recebia nada, entao "o dado vai ate julho e hoje e
      setembro" so existia na hora de planejar, nao na de escrever;
    - sem HORA, "daqui a duas horas" e incomputavel;
    - sem DIA DA SEMANA, converter "toda segunda de manha" em `0 9 * * 1`
      exige deduzir o dia da semana de uma data ISO: conta que modelo
      erra, e e exatamente o que `schedule_task` pede que ele faca.
    """
    from datetime import datetime

    dias = ("segunda-feira", "terca-feira", "quarta-feira", "quinta-feira",
            "sexta-feira", "sabado", "domingo")
    momento = datetime.now().astimezone()
    fuso = momento.strftime("%Z") or momento.strftime("%z")
    return [
        "",
        "### AGORA",
        f"- hoje e {dias[momento.weekday()]}, {momento.strftime('%d/%m/%Y')} "
        f"({momento.date().isoformat()}), {momento.strftime('%H:%M')} ({fuso}).",
        # Em cron a semana comeca no domingo, e converter de cabeca e o erro
        # mais comum de quem agenda "toda segunda".
        f"- em cron, dia da semana vai de 0=domingo a 6=sabado; hoje e "
        f"{(momento.weekday() + 1) % 7}.",
        "- mes citado sem ano e o ano corrente.",
    ]
