"""O que falta nesta máquina antes de o Sentury funcionar: e como resolver.

    python -m sentury.doctor
    python -m sentury.doctor --json

Para gravar um case em qualquer máquina, a pergunta "por que não funcionou?"
tinha que ser respondida depois, no erro. Aqui ela é respondida antes: cada
checagem diz `ok`, `aviso` ou `falta`, e toda que não é `ok` diz o que fazer.
Sai com código 1 se alguma coisa FALTA: aviso não bloqueia.

Nada aqui chama modelo nem rede: é o que dá para saber olhando a máquina.
"""
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List

OK, AVISO, FALTA = "ok", "aviso", "falta"
RAIZ = Path(__file__).resolve().parents[1]


@dataclass
class Checagem:
    nome: str
    estado: str
    detalhe: str
    como_resolver: str = ""


def _python() -> Checagem:
    versao = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] == (3, 13):
        return Checagem("Python", OK, versao)
    return Checagem(
        "Python", AVISO if sys.version_info >= (3, 11) else FALTA, versao,
        "o ambiente válido é o 3.13: `py -3.13 -m venv .venv` (Windows) ou "
        "`python3.13 -m venv .venv`, e reinstale as dependências",
    )


# Os que o servidor importa ao subir. O resto e opcional e tem checagem propria.
_DEPENDENCIAS = ("fastapi", "uvicorn", "pydantic", "httpx", "pandas", "numpy",
                 "matplotlib", "openpyxl", "yaml", "markitdown", "robinbandit")


def _dependencias() -> Checagem:
    faltando = []
    for nome in _DEPENDENCIAS:
        try:
            importlib.import_module(nome)
        except Exception:
            faltando.append(nome)
    if not faltando:
        return Checagem("Dependências", OK, f"{len(_DEPENDENCIAS)} pacotes importam")
    return Checagem("Dependências", FALTA, "não importam: " + ", ".join(faltando),
                    '`pip install -e .` dentro do venv')


def _navegador() -> Checagem:
    try:
        importlib.import_module("playwright")
    except ImportError:
        return Checagem("Navegador (Playwright)", AVISO, "pacote não instalado",
                        '`pip install -e ".[extras]"` e `playwright install chromium`; '
                        "sem ele a ferramenta `browser` fica fora da mesa")
    from .tools.browser_playwright_provider import chromium_baixado
    from .tools.navegador_local import precisa_do_chromium

    # Com o Chrome ou o Edge instalado, o Playwright abre ele e o Chromium sobra.
    baixado = chromium_baixado() if precisa_do_chromium() else True
    if baixado is False:
        return Checagem("Navegador (Playwright)", FALTA,
                        "pacote instalado, sem Chrome, Edge nem Chromium",
                        "instale o Chrome ou rode `playwright install chromium`; sem um deles "
                        "a falha só apareceria na primeira ação")
    if baixado is None:
        return Checagem("Navegador (Playwright)", AVISO, "não consegui conferir o Chromium",
                        "se o navegador falhar, rode `playwright install chromium`")
    from .tools.browser_sobreposicao import navegador_visivel

    if navegador_visivel():
        return Checagem("Navegador (Playwright)", OK, "pronto; abre numa janela com a seta da Sentury")
    return Checagem("Navegador (Playwright)", OK, "pronto; sem tela, roda escondido",
                    "para ver a janela: SENTURY_BROWSER_VISIVEL=sim (precisa de tela)")


def _robin():
    from robinbandit import RobinConfig

    from .config import settings

    caminho = Path(settings.SENTURY_ROBINBANDIT_CONFIG)
    if not caminho.is_absolute():
        caminho = RAIZ / caminho
    return RobinConfig.from_yaml(caminho), settings


def _provedores() -> Checagem:
    try:
        from robinbandit import describe_from_config

        config, settings = _robin()
        prontos = [p["key"] for p in describe_from_config(config, settings)
                   if p.get("configured") and p.get("key") != "fallback"]
    except Exception as exc:
        return Checagem("Provedor de modelo", FALTA, f"não consegui ler a configuração: {exc}",
                        "confira SENTURY_ROBINBANDIT_CONFIG e o YAML do RobinBandit")
    if not prontos:
        return Checagem("Provedor de modelo", FALTA, "nenhum provedor com chave",
                        "ponha ao menos uma chave (ex.: GROQ_API_KEY no .env, ou pela tela "
                        "Provedores > Configurar); sem ela só responde o modo demo")
    return Checagem("Provedor de modelo", OK, ", ".join(prontos))


def _modos() -> Checagem:
    try:
        from robinbandit import account_config

        ligados = [nome for nome in ("reforcado", "dedicado") if account_config.selecao_do_modo(nome)]
    except Exception as exc:
        return Checagem("Reforçado e Dedicado", AVISO, f"não consegui ler: {exc}")
    if len(ligados) == 2:
        return Checagem("Reforçado e Dedicado", OK, "os dois configurados")
    rotulos = {"reforcado": "Reforçado", "dedicado": "Dedicado"}
    desligados = [rotulos[n] for n in ("reforcado", "dedicado") if n not in ligados]
    return Checagem("Reforçado e Dedicado", AVISO, "desligado: " + ", ".join(desligados),
                    "opcional: escolha conta e modelo em Provedores > Modos; sem isso, o "
                    "Router escolhe sozinho")


def _bash() -> Checagem:
    from .tools.script import linguagem_padrao

    padrao = linguagem_padrao()
    if padrao == "bash":
        return Checagem("Bash (executar_script)", OK, "scripts rodam em bash")
    como = ("`winget install Git.Git` (traz o Git Bash)" if sys.platform.startswith("win")
            else "instale o bash pelo gerenciador de pacotes")
    return Checagem("Bash (executar_script)", AVISO, f"sem bash; o padrão cai em {padrao}",
                    f"{como}: o modelo escreve bash melhor que PowerShell")


def _pasta_de_trabalho() -> Checagem:
    from .tools.arquivos import pastas_extras, raiz_de_trabalho, tudo_liberado

    raiz = raiz_de_trabalho()
    if not raiz.is_dir():
        return Checagem("Pasta de trabalho", FALTA, f"'{raiz}' não existe",
                        "escolha a pasta em Harness > Onde ele pode mexer")
    extras = len(pastas_extras())
    detalhe = f"{raiz}" + (f" + {extras} liberada(s)" if extras else "")
    if tudo_liberado():
        return Checagem("Pasta de trabalho", AVISO, detalhe + "; a máquina inteira está liberada",
                        "se não for de propósito, desligue em Harness > Onde ele pode mexer")
    return Checagem("Pasta de trabalho", OK, detalhe)


def _interface() -> Checagem:
    if (RAIZ / "sentury" / "client" / "dist" / "index.html").is_file():
        return Checagem("Interface", OK, "sentury/client/dist pronto")
    return Checagem("Interface", AVISO, "a interface não foi construída",
                    "`npm ci && npm run build` em sentury/client; a API sobe sem ela")


def _casa() -> Checagem:
    from .tools.arquivos import casa_do_sentury

    casa = casa_do_sentury()
    try:
        casa.mkdir(parents=True, exist_ok=True)
        teste = casa / ".doctor"
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
    except OSError as exc:
        return Checagem("Pasta do Sentury", FALTA, f"'{casa}' não aceita escrita: {exc}",
                        "ajuste a permissão da pasta ou aponte SENTURY_HOME para outra")
    tamanho = sum(f.stat().st_size for f in casa.rglob("*") if f.is_file())
    mb = tamanho / 1024 / 1024
    detalhe = f"{casa} ({mb:.0f} MB)"
    if mb > 500:
        return Checagem("Pasta do Sentury", AVISO, detalhe,
                        "o diário compacta sozinho acima de 20 MB; veja o que cresce em "
                        "rascunho/ e tracos/")
    return Checagem("Pasta do Sentury", OK, detalhe)


CHECAGENS: List[Callable[[], Checagem]] = [
    _python, _dependencias, _provedores, _navegador, _modos, _bash,
    _pasta_de_trabalho, _casa, _interface,
]


def diagnosticar() -> List[Checagem]:
    saida = []
    for checar in CHECAGENS:
        try:
            saida.append(checar())
        except Exception as exc:  # uma checagem quebrada nao esconde as outras
            saida.append(Checagem(checar.__name__.strip("_"), AVISO, f"a checagem falhou: {exc}"))
    return saida


_MARCA = {OK: "ok   ", AVISO: "aviso", FALTA: "FALTA"}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sentury.doctor", description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    resultado = diagnosticar()
    if args.json:
        print(json.dumps([asdict(c) for c in resultado], ensure_ascii=False, indent=2))
    else:
        for c in resultado:
            print(f"[{_MARCA[c.estado]}] {c.nome}: {c.detalhe}")
            if c.como_resolver:
                print(f"         -> {c.como_resolver}")
        faltas = sum(c.estado == FALTA for c in resultado)
        avisos = sum(c.estado == AVISO for c in resultado)
        print()
        print("Pronto." if not faltas else f"{faltas} coisa(s) faltando.", f"{avisos} aviso(s)." if avisos else "")
    return 1 if any(c.estado == FALTA for c in resultado) else 0


if __name__ == "__main__":
    raise SystemExit(main())
