"""O que nao roda nunca: nem com "permitir tudo" ligado.

A lista e curta de proposito. Ela nao cobre o que e caro mas recuperavel
(`git reset --hard`, apagar um arquivo do projeto): isso passa pela aprovacao
normal, porque confiar o trabalho ao agente e justamente o que o dono escolhe ao
ligar a permissao ampla. Aqui ficam so os comandos que destroem a maquina, tomam
privilegio ou trazem codigo de fora para executar: decisoes que ninguem toma no
automatico, e que um "sim" distraido nao deveria autorizar.

Isto e uma LISTA DE RECUSA: os comandos abaixo aparecem aqui para serem
barrados, nunca executados.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Inicio de comando: comeco do texto, depois de `;`, `&&`, `||`, `|`, quebra de
# linha, ou dentro de `$(`. Sem esta ancora, a palavra dentro de uma string
# (`echo "nao reboot isso"`) dispararia a recusa.
_INICIO = r"(?:^|[\n;&|]|\$\(|`)\s*"

# A raiz do disco chega de tres formas: `C:\`, `C:/` e `$env:SystemDrive`.
_RAIZ = r"(?:[a-z]:[\\/]?\s*$|\$env:systemdrive)"

_PADROES: Tuple[Tuple[str, str], ...] = (
    # --- traz codigo de fora e executa
    (_INICIO + r"(?:iex|invoke-expression)\b", "executa texto baixado como codigo"),
    (r"(?i)\b(?:downloadstring|downloadfile)\s*\(", "baixa e executa conteudo remoto"),
    (r"(?i)\b(?:curl|wget|irm|iwr)\b[^\n|]*\|\s*(?:ba)?sh\b", "canaliza download direto para o shell"),
    (r"(?i)-e(?:nc|ncodedcommand)\s+[A-Za-z0-9+/=]{16,}", "comando embaralhado em base64"),
    # O PowerShell aceita qualquer abreviacao de -EncodedCommand (`-e`, `-ec`,
    # `/en`...); fora dele `-e` e comum (`grep -e`), entao o programa ancora.
    (r"(?i)\b(?:powershell|pwsh)(?:\.exe)?\b[^\n]*?(?<!\S)(?:--?|/)e(?:c|n(?:c(?:o(?:d(?:e(?:d(?:c(?:o(?:m(?:m(?:a(?:nd?)?)?)?)?)?)?)?)?)?)?)?)?\s+[\"']?[A-Za-z0-9+/=]{16,}",
     "comando embaralhado em base64"),
    # --- toma privilegio ou afrouxa a maquina
    (r"(?i)\bset-executionpolicy\b", "afrouxa a politica de execucao do Windows"),
    (r"(?i)\bstart-process\b[^\n]*-verb\s+runas", "pede elevacao de privilegio"),
    (_INICIO + r"sudo\s+-S\b", "tenta senha de root pela entrada padrao"),
    (r"(?i)\bnew-service\b|\bschtasks\s+/create\b", "instala servico ou tarefa agendada"),
    (r"(?i)\bnet\s+user\b[^\n]*/add", "cria usuario no sistema"),
    # --- destroi a maquina
    (r"(?i)\bformat-volume\b|\bvssadmin\b|\bbcdedit\b", "mexe em disco, backup ou boot"),
    (r"(?i)\bremove-item\b[^\n]*-recurse[^\n]*-force[^\n]*" + _RAIZ, "apaga recursivamente a raiz"),
    (_INICIO + r"rm\s+(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\s+/\s*$", "apaga a raiz do sistema"),
    (r"(?i)\bmkfs(?:\.[a-z0-9]+)?\b|\bdd\b[^\n]*\bof=/dev/", "formata ou sobrescreve o disco"),
    (_INICIO + r"(?:shutdown|reboot|halt|poweroff)\b", "desliga a maquina"),
    (r"(?i)\breg\s+(?:add|delete)\b", "altera o registro do Windows"),
    (r"(?i)\bchmod\s+777\s+/\s*$", "abre permissao da raiz"),
)

_COMPILADOS = tuple((re.compile(padrao, re.IGNORECASE | re.MULTILINE), motivo)
                    for padrao, motivo in _PADROES)


def _sem_comentarios(texto: str) -> str:
    """Tira o comentario antes de avaliar: o que vale e o que roda.

    Sem isso, `rm -rf / # so um exemplo` escaparia da analise por estar
    comentado: e o texto de um comentario tambem nao deve disparar recusa.
    """
    linhas: List[str] = []
    for linha in (texto or "").splitlines():
        linhas.append(re.sub(r"(?<!\S)#.*$", "", linha))
    return "\n".join(linhas)


# Remoção da raiz da pasta pessoal ou de pastas do sistema é bloqueada mesmo
# com permissão ampla; apagar arquivos dentro de uma pasta segue a aprovação.
_VERBO_DE_APAGAR = re.compile(
    r"(?:(?<![\w.-])(?:rm|rmdir|unlink|shred|srm|del|erase|rd|ri|remove-item)(?![\w-])"
    r"|\b(?:rmtree|removedirs|rmSync|rmdirSync|unlinkSync)\s*\("
    r"|\bos\.(?:remove|unlink|rmdir)\s*\("
    r"|\bfind\b(?=[^\n]*(?:-delete\b|-exec\s+(?:rm|shred)\b)))",
    re.IGNORECASE,
)
# Fim do alvo: o que vem depois do caminho mostra que ele parou ali, espaco,
# aspas, `;`, `)`, `,`, fim de linha: ou que so vem o curinga (`/*`).
_FIM = r"(?:[\\/]?\*?)(?=[\s\"');,&|]|$)"
_ALVO_SENSIVEL = re.compile(
    # raiz da pasta do usuario
    r"(?:(?<![\w/.~-])~" + _FIM
    + r"|[\"']?\$\{?home\}?[\"']?" + _FIM
    + r"|%userprofile%" + _FIM
    + r"|\$env:(?:userprofile|homepath)" + _FIM
    + r"|expanduser\(\s*[\"']~[\"']\s*\)|path\.home\(\)|os\.homedir\(\)"
    + r"|(?<![\w.~-])/(?:home|users)/[^/\s\"';)]+" + _FIM
    + r"|(?<![\w.~-])/root" + _FIM
    + r"|[a-z]:\\users\\[^\\\s\"';)]+" + _FIM
    # raiz do disco e pastas do sistema, inteiras ou por dentro
    + r"|(?<![\w.~$-])/\*?(?=[\s\"');,&|]|$)"
    + r"|(?<![\w.~$-])/(?:etc|usr|bin|sbin|lib|lib32|lib64|var|boot|opt|sys|proc|dev|srv"
    + r"|system|library|applications|private)(?![\w-])"
    + r"|[a-z]:\\?\*?(?=[\s\"');,&|]|$)"
    + r"|[a-z]:\\(?:windows|program files(?: \(x86\))?|programdata)(?![\w-])"
    + r"|\$env:(?:systemroot|windir|programfiles|programdata)\b|%(?:systemroot|windir|programfiles)%)",
    re.IGNORECASE,
)


def _dentro_de_aspas(linha: str, posicao: int) -> bool:
    """`echo 'nao rode rm -rf ~'` e texto, nao comando. So o VERBO e olhado
    assim: o alvo entre aspas (`rm -rf "$HOME"`) continua sendo alvo."""
    antes = linha[:posicao]
    return antes.count("'") % 2 == 1 or antes.count('"') % 2 == 1


def _remocao_sensivel(corpo: str) -> Optional[str]:
    for linha in corpo.splitlines():
        for verbo in _VERBO_DE_APAGAR.finditer(linha):
            if _dentro_de_aspas(linha, verbo.start()):
                continue
            if _ALVO_SENSIVEL.search(linha, verbo.start()):
                return "apaga a pasta do usuario ou uma pasta do sistema"
    return None


def recusar(texto: str) -> Optional[str]:
    """O motivo da recusa, ou None quando nada casa."""
    corpo = _sem_comentarios(texto or "")
    for regex, motivo in _COMPILADOS:
        if regex.search(corpo):
            return motivo
    return _remocao_sensivel(corpo)
