"""Sobe o Sentury inteiro com um comando.

    python sentury.py            interface e API juntas, em http://127.0.0.1:8000
    python sentury.py --dev      acrescenta o Vite, para mexer na interface
    python sentury.py --api      só a API, com a documentação em /docs

Ter de lembrar de subir duas coisas em duas janelas é atrito diário, e atrito
diário vira "esqueci de subir o backend" no meio de um teste.

Em `--dev` os dois sobem: o Vite recarrega a interface a cada salvo, e o
backend responde no que ele chamar. Fora do `--dev`, um processo só serve as
duas coisas na mesma origem: sem CORS, sem porta extra.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CLIENT = RAIZ / "sentury" / "client"
DIST = CLIENT / "dist"


def _npm() -> str | None:
    """No Windows o npm é `npm.cmd`; sem isto o build simplesmente não roda."""
    return shutil.which("npm") or shutil.which("npm.cmd")


def construir_interface() -> bool:
    npm = _npm()
    if not npm:
        print("npm nao encontrado: a API sobe, a interface nao.", file=sys.stderr)
        return False
    if not (CLIENT / "node_modules").is_dir():
        print("Instalando dependencias da interface (primeira vez)...")
        if subprocess.run([npm, "install"], cwd=CLIENT).returncode != 0:
            return False
    print("Construindo a interface...")
    return subprocess.run([npm, "run", "build"], cwd=CLIENT).returncode == 0


def precisa_construir() -> bool:
    """Reconstrói quando o código está mais novo que o build.

    Comparar o arquivo mais recente do `src` com o do `dist` evita os dois
    erros: reconstruir sempre (lento) e nunca reconstruir (você olha a versão
    de ontem sem saber).
    """
    if not (DIST / "index.html").is_file():
        return True
    fontes = list((CLIENT / "src").rglob("*")) + [CLIENT / "index.html", CLIENT / "package.json"]
    mais_novo = max((a.stat().st_mtime for a in fontes if a.is_file()), default=0)
    return mais_novo > (DIST / "index.html").stat().st_mtime


def quem_ocupa(porta: int) -> str:
    """Quem já está escutando nessa porta, quando dá para saber.

    Sem isto o Windows devolve `WinError 10013` ("acesso a um soquete de uma
    maneira proibida") que não diz que a porta está ocupada, e a pessoa fica
    olhando para o servidor ANTIGO achando que subiu o novo.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as teste:
        teste.settimeout(0.3)
        if teste.connect_ex(("127.0.0.1", porta)) != 0:
            return ""

    try:
        saida = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-NetTCPConnection -LocalPort {porta} -State Listen"
             " -ErrorAction SilentlyContinue).OwningProcess"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip().splitlines()
        if saida and saida[0].strip().isdigit():
            return saida[0].strip()
    except Exception:
        pass
    return "?"


def encerrar(pid: str) -> bool:
    try:
        if os.name == "nt":
            return subprocess.run(["taskkill", "/PID", pid, "/F"],
                                  capture_output=True).returncode == 0
        os.kill(int(pid), 15)
        return True
    except Exception:
        return False


def subir_api(porta: int, recarregar: bool, docs: bool = False) -> subprocess.Popen:
    comando = [sys.executable, "-m", "uvicorn", "sentury.main:app",
               "--host", "127.0.0.1", "--port", str(porta)]
    if recarregar:
        comando.append("--reload")
    # A documentação da API é ferramenta de quem desenvolve; no uso normal fica fechada.
    ambiente = {**os.environ, "SENTURY_DOCS": "true"} if docs else None
    return subprocess.Popen(comando, cwd=RAIZ, env=ambiente)


def subir_vite() -> subprocess.Popen | None:
    npm = _npm()
    if not npm:
        return None
    return subprocess.Popen([npm, "run", "dev"], cwd=CLIENT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sobe o Sentury.")
    parser.add_argument("--dev", action="store_true",
                        help="modo desenvolvimento: Vite com recarga + API com --reload")
    parser.add_argument("--api", action="store_true", help="só a API")
    parser.add_argument("--porta", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--sem-build", action="store_true",
                        help="não reconstruir a interface antes de subir")
    parser.add_argument("--trocar", action="store_true",
                        help="encerrar quem já estiver na porta e subir no lugar")
    args = parser.parse_args()

    processos: list[subprocess.Popen] = []
    try:
        if not args.api and not args.dev and not args.sem_build and precisa_construir():
            if not construir_interface():
                print("Build falhou; subindo so a API.", file=sys.stderr)

        ocupada = quem_ocupa(args.porta)
        if ocupada:
            print(f"\nA porta {args.porta} ja esta em uso (processo {ocupada}).")
            print("Provavelmente e um Sentury de antes — e e ELE que voce veria no navegador.")
            if args.trocar:
                if encerrar(ocupada):
                    print("Encerrado. Subindo o novo.\n")
                    time.sleep(1.0)
                else:
                    print("Nao consegui encerrar; escolha outra porta com --porta.\n")
                    return 1
            else:
                print("Rode com --trocar para encerrar o antigo, ou use --porta N.\n")
                return 1

        processos.append(subir_api(args.porta, recarregar=args.dev, docs=args.api or args.dev))

        if args.dev:
            # Um instante para a API abrir a porta antes do proxy do Vite
            # bater nela: o primeiro pedido falharia e o console mostraria um
            # erro que não é erro.
            time.sleep(1.5)
            vite = subir_vite()
            if vite:
                processos.append(vite)
                print("\nInterface (com recarga): http://127.0.0.1:5173")
            print(f"API: http://127.0.0.1:{args.porta}\n")
        elif args.api:
            print(f"\nAPI: http://127.0.0.1:{args.porta}\n")
        else:
            print(f"\nSentury: http://127.0.0.1:{args.porta}\n")

        # Se um cair, os outros vão junto: meia stack de pé engana mais do que
        # ajuda: a tela abre e nada responde.
        while True:
            for processo in processos:
                codigo = processo.poll()
                if codigo is not None:
                    return codigo or 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for processo in processos:
            if processo.poll() is None:
                processo.terminate()
        for processo in processos:
            try:
                processo.wait(timeout=5)
            except subprocess.TimeoutExpired:
                processo.kill()


if __name__ == "__main__":
    raise SystemExit(main())
