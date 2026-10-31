"""O resultado de uma execucao, e o vocabulario de erro que a acompanha.

Duas regras que vieram de fora, e que mudam a ergonomia inteira:

1. **Fatos ortogonais.** `codigo_saida`, `timeout`, `recusado` e `stdout` sao
   independentes. Quem le decide o que importa; nada vem pre-digerido num
   booleano que perde informacao.
2. **Comando que falha nao e excecao.** Sair com codigo 1 e um fato do processo,
   nao um acidente do Python. So falha de infraestrutura (nao consegui criar o
   processo) levanta. Isso evita o `try/except` em volta de toda chamada e o
   costume de tratar `grep` sem resultado como catastrofe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class CodigoDeErro:
    """Codigos fechados. O modelo le a frase; o codigo e para politica e rota."""

    DESLIGADO = "EXEC_DESLIGADO"
    RECUSADO_POLITICA = "EXEC_RECUSADO_POLITICA"
    PRECISA_PERMISSAO = "EXEC_PRECISA_PERMISSAO"
    ALVO_SENSIVEL = "EXEC_ALVO_SENSIVEL"
    NAO_ENCONTRADO = "EXEC_NAO_ENCONTRADO"
    TIMEOUT = "EXEC_TIMEOUT"
    MEMORIA = "EXEC_MEMORIA"
    SANDBOX_NEGADO = "EXEC_SANDBOX_NEGADO"
    IMPORT_NEGADO = "EXEC_IMPORT_NEGADO"
    FALHA_INFRA = "EXEC_FALHA_INFRA"


class FalhaDeInfra(RuntimeError):
    """Nao deu para sequer tentar: processo nao criado, porta nao aberta."""

    def __init__(self, mensagem: str, codigo: str = CodigoDeErro.FALHA_INFRA):
        super().__init__(mensagem)
        self.codigo = codigo


@dataclass
class Resultado:
    """O que uma execucao produziu. Nenhum campo resume outro."""

    comando: str = ""
    codigo_saida: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    truncado: bool = False
    timeout: bool = False
    abortado: bool = False
    recusado: bool = False
    precisa_permissao: bool = False
    motivo: str = ""
    codigo_erro: str = ""
    duracao_ms: int = 0
    diretorio: str = ""
    modo: str = "processo"
    arquivos_gerados: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Sucesso exige prova: saiu, e saiu zero."""
        if self.recusado or self.timeout or self.abortado or self.precisa_permissao:
            return False
        return self.codigo_saida == 0

    def para_dict(self) -> Dict[str, Any]:
        """Formato que as ferramentas ja devolvem hoje.

        `codigo`, `saida` e `erro` continuam com os nomes antigos: mudar o
        vocabulario do retorno e mudar o contrato com o orquestrador, com o
        frontend e com dezenas de testes de uma vez.
        """
        saida: Dict[str, Any] = {
            "ok": self.ok,
            "comando": self.comando,
            "codigo": self.codigo_saida,
            "saida": self.stdout,
            "erro": self.stderr,
            "truncado": self.truncado,
            "duracao_ms": self.duracao_ms,
            "diretorio": self.diretorio,
            "modo": self.modo,
        }
        for campo, valor in (
            ("timeout", self.timeout),
            ("abortado", self.abortado),
            ("recusado", self.recusado),
            ("precisa_permissao", self.precisa_permissao),
        ):
            if valor:
                saida[campo] = True
        if self.motivo:
            saida["motivo"] = self.motivo
        if self.codigo_erro:
            saida["codigo_erro"] = self.codigo_erro
        if self.arquivos_gerados:
            saida["arquivos_gerados"] = list(self.arquivos_gerados)
        return saida


def recusa(comando: str, motivo: str, codigo: str = CodigoDeErro.RECUSADO_POLITICA) -> Resultado:
    return Resultado(comando=comando, recusado=True, motivo=motivo, codigo_erro=codigo)


def pendente(comando: str, motivo: str) -> Resultado:
    """Pergunta ao dono. Nao e falha do modelo, e nao deve contar como tal."""
    return Resultado(
        comando=comando, precisa_permissao=True, motivo=motivo,
        codigo_erro=CodigoDeErro.PRECISA_PERMISSAO,
    )
