"""O protocolo de execução fica no workspace, sem acesso ao processo da HQ."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

RAIZ = Path("/workspace")
TETO = 200_000


def caminho(texto):
    bruto = Path(str(texto or "."))
    alvo = (bruto if bruto.is_absolute() else RAIZ / bruto).resolve()
    if not alvo.is_relative_to(RAIZ.resolve()):
        raise ValueError("O caminho está fora do workspace da caixa.")
    return alvo


def processo(argv, cwd, prazo):
    with tempfile.TemporaryFile() as saida, tempfile.TemporaryFile() as erro:
        p = subprocess.Popen(argv, cwd=cwd, stdout=saida, stderr=erro, start_new_session=True)
        acabou = True
        try:
            p.wait(timeout=prazo)
        except subprocess.TimeoutExpired:
            acabou = False
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        saida.seek(0)
        erro.seek(0)
        out, err = saida.read(TETO + 1), erro.read(TETO + 1)
        return {"ok": acabou and p.returncode == 0, "codigo": p.returncode,
                "saida": out[:TETO].decode("utf-8", errors="replace"),
                "erro": err[:TETO].decode("utf-8", errors="replace"),
                "timeout": not acabou, "truncado": len(out) > TETO or len(err) > TETO}


def executar(op, args):
    if op == "comando":
        return processo(["bash", "--noprofile", "--norc", "-c", str(args.get("comando") or args.get("command") or "")], caminho(args.get("diretorio")), min(300, max(1, float(args.get("timeout") or 60))))
    if op in ("script", "python"):
        linguagem = str(args.get("linguagem") or args.get("language") or ("python" if op == "python" else "bash"))
        interpretadores = {"python": ["python"], "bash": ["bash", "--noprofile", "--norc"], "sh": ["sh"], "node": ["node"]}
        argv = interpretadores.get(linguagem)
        if argv is None:
            raise ValueError("Linguagem indisponível na caixa: python, bash, sh ou node.")
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = args.get("arquivo")
            script = caminho(arquivo) if arquivo else Path(pasta) / "script"
            if not arquivo:
                script.write_text(str(args.get("conteudo") or args.get("content") or args.get("codigo") or args.get("code") or ""), encoding="utf-8")
            argumentos = args.get("argumentos") or args.get("args") or []
            if not isinstance(argumentos, list):
                raise ValueError("Argumentos precisam ser uma lista.")
            return processo([*argv, str(script), *map(str, argumentos)], caminho(args.get("diretorio")), min(300, max(1, float(args.get("timeout") or 120))))
    alvo = caminho(args.get("caminho") or args.get("path"))
    if op == "listar":
        padrao = str(args.get("padrao") or "*")
        if Path(padrao).is_absolute() or ".." in Path(padrao).parts:
            raise ValueError("O padrão deve ficar dentro da pasta.")
        itens = []
        for item in alvo.glob(padrao):
            if not item.resolve().is_relative_to(RAIZ.resolve()):
                continue
            itens.append({"caminho": str(item.relative_to(RAIZ)), "tipo": "pasta" if item.is_dir() else "arquivo"})
            if len(itens) >= 2000:
                break
        return {"ok": True, "arquivos": itens, "truncado": len(itens) == 2000}
    if op == "ler":
        inicio = max(1, int(args.get("inicio") or 1))
        linhas = min(2000, max(1, int(args.get("linhas") or 2000)))
        partes, tamanho = [], 0
        truncado = False
        with alvo.open(encoding="utf-8") as arquivo:
            for indice, linha in enumerate(arquivo, 1):
                if indice < inicio:
                    continue
                if len(partes) >= linhas or tamanho + len(linha) > TETO:
                    truncado = True
                    break
                partes.append(linha)
                tamanho += len(linha)
        return {"ok": True, "conteudo": "".join(partes), "truncado": truncado, "caminho": str(alvo)}
    if op in ("escrever", "editar"):
        conteudo = str(args.get("conteudo") or "")
        if op == "editar":
            antes = str(args.get("antes") or "")
            texto = alvo.read_text(encoding="utf-8")
            if not antes or texto.count(antes) != 1:
                raise ValueError("O trecho precisa aparecer exatamente uma vez.")
            conteudo = texto.replace(antes, str(args.get("depois") or ""), 1)
        if len(conteudo.encode()) > TETO:
            raise ValueError("O arquivo passa do teto de escrita da caixa.")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=alvo.parent, delete=False) as arquivo:
            temporario = Path(arquivo.name)
            arquivo.write(conteudo.encode("utf-8"))
        temporario.replace(alvo)
        return {"ok": True, "caminho": str(alvo)}
    raise ValueError("Operação não disponível na caixa.")


if __name__ == "__main__":
    try:
        pedido = json.loads(sys.stdin.buffer.read(1_000_001))
        resultado = executar(pedido["op"], pedido["args"])
    except Exception as exc:
        resultado = {"ok": False, "erro": str(exc)}
    print(json.dumps(resultado, ensure_ascii=False))
