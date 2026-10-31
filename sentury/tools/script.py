"""Escrever um script e roda-lo: com o conteudo aprovado antes.

Por que existe, sendo que ja ha `executar_comando`: porque `executar_comando`
roda uma linha sem shell, e recusa `|`, `>` e `&&`. Isso protege contra a linha
do modelo ser reinterpretada por um shell, e essa protecao nao volta atras.
O que muda aqui e ONDE os metacaracteres podem existir: dentro de um arquivo,
que o dono le inteiro antes de aprovar, em vez de escondidos numa linha.

O argv continua fixo e montado por nos (`shell=False`): o interpretador recebe
`-File caminho`, e nada do texto do agente e interpretado deste lado.

A aprovacao e do CONTEUDO (ver `permissoes.assinatura`): aprovar um script nao
aprova o proximo, e reescrever o arquivo invalida a aprovacao anterior.
"""
from __future__ import annotations

import logging
import os
import hashlib
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..exec import hardline
from ..exec.ambiente import bandeiras_de_processo, preparar_env
from ..exec.contrato import CodigoDeErro, Resultado, pendente, recusa
from ..exec.limites import matar_arvore
from ..exec.saida import preparar

logger = logging.getLogger(__name__)

TIMEOUT_PADRAO_S = 120.0

# Cada linguagem: extensao, candidatos a interpretador e as bandeiras que o
# deixam previsivel (sem perfil do usuario, sem prompt interativo).
_LINGUAGENS: Dict[str, Dict[str, Any]] = {
    "powershell": {
        "extensao": ".ps1",
        "binarios": ("pwsh", "powershell"),
        # `-ExecutionPolicy Bypass` vale so para ESTA chamada; nao muda a
        # politica da maquina, que e o que a lista de recusa barra.
        "bandeiras": ("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"),
    },
    "bash": {"extensao": ".sh", "binarios": ("bash",), "bandeiras": ("--noprofile", "--norc")},
    "sh": {"extensao": ".sh", "binarios": ("sh",), "bandeiras": ()},
    "python": {"extensao": ".py", "binarios": (), "bandeiras": ()},
    "node": {"extensao": ".js", "binarios": ("node",), "bandeiras": ()},
}

_APELIDOS = {"ps1": "powershell", "ps": "powershell", "pwsh": "powershell",
             "py": "python", "shell": "bash", "js": "node", "javascript": "node"}
_LINGUAGEM_DA_EXTENSAO = {
    ".ps1": "powershell", ".sh": "bash", ".py": "python", ".js": "node",
}
_TAMANHO_MAXIMO_SKILL_SCRIPT = 2 * 1024 * 1024


def linguagens_disponiveis() -> List[str]:
    """As que existem NESTA maquina. PowerShell nao existe em Linux puro."""
    return [nome for nome in _LINGUAGENS if _interpretador(nome)]


def _bash_do_windows() -> Optional[str]:
    """O bash do Git, nunca o lancador do WSL.

    `System32\\bash.exe` abre um Linux separado, com outros caminhos, e pode
    pedir para instalar uma distribuicao. O do Git fica ao lado do `git`.
    """
    candidatos: List[Path] = []
    achado = shutil.which("bash")
    if achado and not any(p in achado.lower() for p in ("system32", "windowsapps")):
        candidatos.append(Path(achado))
    git = shutil.which("git")
    if git:
        for pasta in Path(git).resolve().parents:
            if pasta.name.lower() == "git":
                candidatos.append(pasta / "bin" / "bash.exe")
                break
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidatos.append(Path(base) / "Git" / "bin" / "bash.exe")
    return next((str(c) for c in candidatos if c.is_file()), None)


def linguagem_padrao() -> str:
    """Bash quando existe: o modelo escreve bash melhor e o script roda igual
    em Linux, Mac e aqui. PowerShell e a reserva do Windows sem Git Bash."""
    for nome in ("bash", "powershell", "sh"):
        if _interpretador(nome):
            return nome
    return "python"


def _interpretador(linguagem: str) -> Optional[str]:
    spec = _LINGUAGENS.get(linguagem) or {}
    if linguagem == "python":
        # O Python do venv, nao o do sistema: e onde as dependencias estao.
        return sys.executable or shutil.which("python")
    if linguagem == "bash" and os.name == "nt":
        return _bash_do_windows()
    for nome in spec.get("binarios", ()):
        achado = shutil.which(nome)
        if achado:
            return achado
    return None


def _recusar_alvo_sensivel_no_corpo(conteudo: str) -> Optional[str]:
    """Alvo proibido vale para o corpo do script, nao so para argumentos.

    Um alvo so esta protegido se estiver barrado em TODO verbo que o alcanca.
    Barrar `cat .env` e deixar passar um script que le o mesmo arquivo e uma
    porta destrancada ao lado de uma trancada.
    """
    from .shell import politica

    baixo = (conteudo or "").lower()
    for alvo in (politica().get("alvos_proibidos") or []):
        if str(alvo).lower() in baixo:
            return f"o script menciona '{alvo}', que guarda credencial"
    for pasta in (politica().get("pastas_proibidas") or []):
        marca = str(pasta).lower()
        if f"/{marca}" in baixo or f"\\{marca}" in baixo:
            return f"o script acessa a pasta '{pasta}', que guarda credencial"
    return None


_SAIDA_UTF8_DO_POWERSHELL = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
)


def _gravar_no_rascunho(conteudo: str, extensao: str, session_id: str) -> Path:
    """Grava no rascunho com nome derivado do conteudo.

    A chave da permissao inclui o nome do arquivo: o mesmo script e sempre o
    mesmo arquivo, e um script diferente e outro, que pede aprovacao de novo.
    """
    from .arquivos import pasta_de_rascunho

    pasta = Path(pasta_de_rascunho(session_id))
    pasta.mkdir(parents=True, exist_ok=True)
    impressao = hashlib.sha256(conteudo.encode("utf-8", "replace")).hexdigest()[:12]
    alvo = pasta / f"script-{impressao}{extensao}"
    if extensao == ".ps1":
        # O PowerShell 5.1 le .ps1 sem BOM como ANSI e escreve na pagina do
        # console: sem o BOM e a linha de saida, caminho com acento nao e achado
        # e a saida volta ilegivel.
        alvo.write_text(_SAIDA_UTF8_DO_POWERSHELL + conteudo, encoding="utf-8-sig")
    else:
        # O padrao do Windows e ANSI, e acento no script vira erro de sintaxe.
        alvo.write_text(conteudo, encoding="utf-8")
    return alvo


def _ler_script_de_skill(caminho: str) -> tuple[str, Path, Path, str]:
    """Le somente ``scripts/`` de uma skill e barra fuga por symlink.

    O manifesto da skill delimita o pacote. Um caminho que parece estar em
    ``scripts/`` mas resolve para fora da pasta não é um recurso da skill.
    """
    informado = Path(str(caminho or "")).expanduser()
    if not informado.is_absolute():
        raise ValueError("o arquivo da skill precisa usar caminho absoluto")

    raiz_declarada = None
    for candidata in (informado.parent, *informado.parents):
        if (candidata / "SKILL.md").is_file():
            raiz_declarada = candidata
            break
    if raiz_declarada is None:
        raise ValueError("o arquivo nao pertence a uma pasta com SKILL.md")

    try:
        raiz = raiz_declarada.resolve(strict=True)
        alvo = informado.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"arquivo da skill indisponivel: {exc}") from exc
    if not alvo.is_file() or not alvo.is_relative_to(raiz):
        raise ValueError("o arquivo resolve para fora da skill")
    relativo = alvo.relative_to(raiz)
    if not relativo.parts or relativo.parts[0].lower() != "scripts":
        raise ValueError("somente arquivos dentro de scripts/ podem ser executados")
    linguagem = _LINGUAGEM_DA_EXTENSAO.get(alvo.suffix.lower())
    if linguagem is None:
        raise ValueError("extensao de script da skill nao suportada")
    if alvo.stat().st_size > _TAMANHO_MAXIMO_SKILL_SCRIPT:
        raise ValueError("script da skill excede 2 MiB")
    try:
        conteudo = alvo.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError("script da skill nao esta em UTF-8") from exc
    return conteudo, alvo, raiz, linguagem



# A tela mostra a saida como terminal: linhas na ordem em que sairam, com a
# origem (`out` ou `err`). Ler os dois fluxos em paralelo tambem evita o
# travamento de quem enche um pipe enquanto o outro espera.
MAX_LINHAS_DA_TELA = 2000


def _ler_em_ordem(processo, ao_linha: Optional[Callable[[str, str], None]]):
    linhas: List[Tuple[str, str]] = []
    trava = threading.Lock()

    def drenar(fluxo, origem: str) -> None:
        try:
            for linha in iter(fluxo.readline, ""):
                texto = linha.rstrip("\r\n")
                with trava:
                    linhas.append((origem, texto))
                if ao_linha is not None:
                    try:
                        ao_linha(origem, texto)
                    except Exception:
                        pass
        except (ValueError, OSError):
            pass
        finally:
            try:
                fluxo.close()
            except Exception:
                pass

    leitores = [
        threading.Thread(target=drenar, args=(processo.stdout, "out"), daemon=True),
        threading.Thread(target=drenar, args=(processo.stderr, "err"), daemon=True),
    ]
    for leitor in leitores:
        leitor.start()
    return linhas, leitores


def _esperar_leitores(leitores) -> None:
    # Um neto que herdou o pipe pode segurar a leitura aberta: 5 s bastam.
    for leitor in leitores:
        leitor.join(timeout=5)


def _juntar(linhas: List[Tuple[str, str]], origem: str) -> str:
    texto = "\n".join(t for o, t in linhas if o == origem)
    return texto + "\n" if texto else ""

def executar_script(
    conteudo: str = "",
    linguagem: str = "",
    *,
    arquivo: Optional[str] = None,
    argumentos: Optional[List[str]] = None,
    diretorio: Optional[str] = None,
    timeout: float = TIMEOUT_PADRAO_S,
    habilitado: bool = False,
    session_id: str = "",
    ao_linha: Optional[Callable[[str, str], None]] = None,
    leitura_validada: bool = False,
) -> Dict[str, Any]:
    """Executa conteudo novo ou um auxiliar de ``scripts/`` de uma skill.

    `leitura_validada`: o shell ja conferiu que cada trecho do comando e
    leitura (`shell.executar`). Pula so a pergunta de permissao; hardline e
    alvo sensivel valem sempre.
    """
    origem_skill: Optional[Path] = None
    raiz_skill: Optional[Path] = None
    linguagem_do_arquivo = ""
    if arquivo:
        try:
            conteudo, origem_skill, raiz_skill, linguagem_do_arquivo = _ler_script_de_skill(arquivo)
        except ValueError as exc:
            return recusa("skill script", str(exc), CodigoDeErro.SANDBOX_NEGADO).para_dict()

    escolhida_bruta = str(linguagem or linguagem_do_arquivo or linguagem_padrao()).strip().lower()
    escolhida = _APELIDOS.get(escolhida_bruta, escolhida_bruta)
    comando_visivel = f"{escolhida} script"
    if not habilitado:
        return recusa(comando_visivel, "execucao de comandos desligada (SENTURY_SHELL)",
                      CodigoDeErro.DESLIGADO).para_dict()

    corpo_bruto = str(conteudo or "")
    # Arquivo de skill e aprovado byte a byte (com newline normalizado pelo
    # modo texto). Conteudo escrito pelo modelo mantem o contrato antigo de
    # ignorar espaco nas pontas.
    corpo = corpo_bruto if origem_skill else corpo_bruto.strip()
    if not corpo.strip():
        return recusa(comando_visivel, "script vazio").para_dict()

    if escolhida not in _LINGUAGENS:
        return recusa(
            comando_visivel,
            f"linguagem '{linguagem}' nao e suportada; disponiveis: {', '.join(linguagens_disponiveis())}",
        ).para_dict()
    if linguagem_do_arquivo and escolhida != linguagem_do_arquivo:
        return recusa(
            comando_visivel,
            f"a extensao de '{origem_skill.name}' exige linguagem '{linguagem_do_arquivo}'",
            CodigoDeErro.SANDBOX_NEGADO,
        ).para_dict()

    # Ordem: o que nunca roda vem antes de qualquer permissao, inclusive da
    # permissao ampla. "Permitir tudo" e confianca no trabalho do agente, nao
    # autorizacao para formatar o disco.
    #
    # E vem antes tambem de procurar o interpretador: se a maquina nao tiver
    # PowerShell, `Set-ExecutionPolicy Bypass` era recusado por "nao existe
    # nesta maquina": verdade, mas a resposta errada. A recusa sai do CORPO do
    # script, entao ela precisa ser a mesma no Windows do dono e no Linux do CI.
    motivo_hardline = hardline.recusar(corpo)
    if motivo_hardline:
        return recusa(comando_visivel, f"recusado sem apelacao: {motivo_hardline}").para_dict()

    motivo_alvo = _recusar_alvo_sensivel_no_corpo(corpo)
    if motivo_alvo:
        return recusa(comando_visivel, motivo_alvo, CodigoDeErro.ALVO_SENSIVEL).para_dict()

    binario = _interpretador(escolhida)
    if not binario:
        return recusa(
            comando_visivel,
            f"'{escolhida}' nao existe nesta maquina; disponiveis: {', '.join(linguagens_disponiveis())}",
            CodigoDeErro.NAO_ENCONTRADO,
        ).para_dict()

    spec = _LINGUAGENS[escolhida]
    caminho_aprovacao = _gravar_no_rascunho(corpo, spec["extensao"], session_id)
    caminho_execucao = origem_skill or caminho_aprovacao

    # A permissão considera o conteúdo gravado, não apenas o nome do arquivo.
    from .permissoes import avaliar

    from ..exec.criticas import no_diretorio

    comando_para_permissao = no_diretorio(
        f'{Path(binario).stem} "{caminho_aprovacao}"', diretorio or "",
    )
    decisao = ({"precisa_perguntar": False, "permitido": True, "motivo": "leitura", "chave": ""}
               if leitura_validada else avaliar(comando_para_permissao, session_id))
    if decisao["precisa_perguntar"]:
        # `comando` aqui e o comando DE VERDADE, nao um rotulo bonito: quem
        # responde a pergunta chama `permissoes.responder(comando, ...)`, que
        # recalcula a assinatura a partir dele. Com um rotulo, o sim do dono
        # gravaria outra chave e a pergunta voltaria na tentativa seguinte.
        resposta = pendente(comando_para_permissao, decisao["motivo"]).para_dict()
        resposta.update({
            "chave": decisao["chave"],
            "so_desta_vez": bool(decisao.get("so_desta_vez")),
            "nesta_conversa": decisao.get("nesta_conversa") or "",
            "script": str(caminho_execucao),
            "conteudo": corpo,
            "linguagem": escolhida,
        })
        if raiz_skill:
            resposta.update({"origem": "skill", "skill_dir": str(raiz_skill)})
        return resposta
    if not decisao["permitido"]:
        return recusa(comando_visivel, decisao["motivo"]).para_dict()

    # A aprovacao cobriu estes bytes. Confere outra vez imediatamente antes de
    # iniciar o arquivo original para detectar edicao entre leitura e decisao.
    if origem_skill:
        try:
            if origem_skill.read_text(encoding="utf-8") != corpo:
                return recusa(
                    comando_visivel, "o script da skill mudou depois da aprovacao; revise de novo",
                    CodigoDeErro.RECUSADO_POLITICA,
                ).para_dict()
        except OSError as exc:
            return recusa(comando_visivel, f"script da skill indisponivel: {exc}").para_dict()

    argv = [binario, *spec["bandeiras"], str(caminho_execucao), *[str(a) for a in (argumentos or [])]]
    from .arquivos import raiz_de_trabalho

    raiz = Path(diretorio or raiz_de_trabalho()).resolve()
    inicio = time.time()

    try:
        processo = subprocess.Popen(
            argv, cwd=str(raiz), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
            env=preparar_env({"SENTURY_SKILL_DIR": str(raiz_skill)}) if raiz_skill else preparar_env(),
            **bandeiras_de_processo(),
        )
    except OSError as exc:
        return recusa(comando_visivel, f"{type(exc).__name__}: {exc}",
                      CodigoDeErro.FALHA_INFRA).para_dict()

    linhas, leitores = _ler_em_ordem(processo, ao_linha)
    try:
        processo.wait(timeout=max(1.0, float(timeout)))
    except subprocess.TimeoutExpired:
        # O `wait(timeout)` nao encerra nada sozinho, e um script que chamou
        # outro programa deixa neto vivo. A arvore inteira cai.
        matar_arvore(processo)
        processo.wait()
        _esperar_leitores(leitores)
        resultado = Resultado(
            comando=comando_visivel, timeout=True, modo="interprete",
            motivo=f"passou de {int(timeout)}s e foi encerrado junto com o que ele abriu",
            codigo_erro=CodigoDeErro.TIMEOUT, diretorio=str(raiz),
            duracao_ms=int((time.time() - inicio) * 1000),
        )
        resposta = resultado.para_dict()
        resposta["script"] = str(caminho_execucao)
        if raiz_skill:
            resposta.update({"origem": "skill", "skill_dir": str(raiz_skill)})
        return resposta

    _esperar_leitores(leitores)
    stdout, stderr = _juntar(linhas, "out"), _juntar(linhas, "err")

    from .shell import limite_de_saida

    teto = limite_de_saida()
    saida, cortou_saida = preparar(stdout or "", teto)
    erro, cortou_erro = preparar(stderr or "", teto)
    resultado = Resultado(
        comando=comando_visivel, codigo_saida=processo.returncode,
        stdout=saida, stderr=erro, truncado=cortou_saida or cortou_erro,
        duracao_ms=int((time.time() - inicio) * 1000),
        diretorio=str(raiz), modo="interprete",
    )
    resposta = resultado.para_dict()
    resposta["script"] = str(caminho_execucao)
    resposta["linguagem"] = escolhida
    resposta["linhas"] = linhas[-MAX_LINHAS_DA_TELA:]
    resposta["linhas_cortadas"] = max(0, len(linhas) - MAX_LINHAS_DA_TELA)
    if raiz_skill:
        resposta.update({"origem": "skill", "skill_dir": str(raiz_skill)})
    return resposta
