"""A caixa recebe o arquivo no volume próprio, sem executar o conteúdo."""
import base64
from pathlib import Path
import sys


def receber(destino, corpo):
    raiz = Path("/workspace/recebidos")
    alvo = Path(destino)
    if (not raiz.resolve().is_relative_to(Path("/workspace").resolve()) or
            not alvo.is_relative_to(raiz) or not alvo.resolve().is_relative_to(raiz.resolve())):
        raise ValueError("O anexo precisa ficar na pasta de recebidos da caixa.")
    conteudo = base64.b64decode(corpo, validate=True)
    if not conteudo or len(conteudo) > 8 * 1024 * 1024:
        raise ValueError("O anexo passa do limite de 8 MB ou está vazio.")
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(conteudo)


if __name__ == "__main__":
    receber(sys.argv[1], sys.stdin.read(11_500_001))
