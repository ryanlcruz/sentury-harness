"""Memória da pessoa: o contexto que entra no turno e o armazenamento.

O armazenamento é `memoria_em_arquivos.MemoriaEmArquivos`. `UserMemoryStore`,
sobre o backend de sessão, fica só para trazer o que já estava guardado lá.
Quem decide o que guardar é o modelo, pela ferramenta `memoria`.
"""
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional


_MEM_TTL = 60 * 60 * 24 * 180  # 180 dias
_MAX_MEMORIAS = 60
_MAX_FATO_CHARS = 240

def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode("ascii")


# Remove termos genéricos antes de deduplicar memórias por assunto.
_MEM_STOPWORDS = {
    "meu", "minha", "nosso", "nossa", "foco", "focar", "foca", "salvar", "salve",
    "preferencia", "preferencias", "interesse", "recorrente",
    "que", "para", "com", "sem", "tende", "pedir",
    "dados", "quero", "acompanhar", "priorize", "prioridade", "objetivo", "meta",
    "de", "da", "do", "em", "no", "na", "os", "as", "um", "uma", "e", "a", "o",
}


def _sig_tokens(texto: str) -> set:
    """Tokens significativos (o ASSUNTO) de uma memória, sem acento nem filler."""
    toks = re.findall(r"[a-z0-9]+", _sem_acento(texto))
    return {t for t in toks if len(t) > 2 and t not in _MEM_STOPWORDS}


# Tópicos rastreáveis (regiões, unidades de negócio e filiais) para aprender o
# FOCO do usuário pelo comportamento: não só pelo ensino explícito.
def _topicos_do_setor():
    """Consulta os tópicos do setor ativo a cada chamada.

    Sem setor, apenas preferências ensinadas explicitamente entram na memória.
    """
    try:
        from ..domains.do_setor import dimensoes

        tabela = dimensoes()
    except Exception:
        return []
    saida = []
    for nome, valores in tabela.items():
        rotulo = str(nome).replace("_", " ")
        for valor in (valores or []):
            saida.append((_sem_acento(str(valor)), str(valor), rotulo))
    return saida


def detect_recurring_interest(
    history: List[Dict[str, Any]], results: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Aprende do comportamento deliberado, não da frequência de fala: só conta
    quando a pessoa restringe as análises ao mesmo recorte em dois ou mais
    aprofundamentos. Menção em texto não conta, porque falar muito de um recorte
    com problema é o motivo de investigar, não uma preferência durável. O que a
    pessoa ensina, o modelo guarda pela ferramenta `memoria`.

    `history` é mantido na assinatura por compatibilidade com os chamadores, mas
    deliberadamente NÃO é lido: menção em conversa não é sinal de preferência."""
    # Só filtros explícitos das análises (ex.: regiao="Sul"): uma
    # AÇÃO de restringir o recorte, não o assunto ter sido citado por alguém.
    # As chaves de recorte vem do setor ativo; o generalista nao tem nenhuma.
    try:
        from ..domains.do_setor import dimensoes

        chaves = tuple(dimensoes().keys())
    except Exception:
        chaves = ()
    filtros = []
    for receita in (results or {}).values():
        for chave in chaves:
            valor = (receita.get("arguments") or {}).get(chave)
            if valor:
                filtros.append(_sem_acento(str(valor)))
    if len(filtros) < 2:
        return None
    for chave, nome, tipo in _topicos_do_setor():
        padrao = rf"\b{re.escape(chave)}\b"
        if sum(1 for txt in filtros if re.search(padrao, txt)) >= 2:
            return f"Interesse recorrente: {tipo} {nome}"
    return None


_COMO_USAR = Path(__file__).resolve().parent.parent / "context" / "base" / "MEMORIA_DA_PESSOA.md"
_ITENS_NO_TURNO = 30
_ANTIGAS_PARECIDAS = 8


def build_memory_context(memorias: List[Dict[str, Any]], pedido: str = "") -> Optional[str]:
    """A lista curta do que o Sentury sabe da pessoa, com tipo e idade: as mais recentes
    e, das que ficaram para trás, as parecidas com o pedido, que senão nunca voltariam."""
    if not memorias:
        return None
    from .memoria_em_arquivos import idade

    escolhidas = memorias[-_ITENS_NO_TURNO:]
    antigas = memorias[:-_ITENS_NO_TURNO]
    if antigas and str(pedido or "").strip():
        from .semelhanca import parecidas

        achadas = parecidas(pedido, {str(i): m.get("descricao") or m["texto"] for i, m in enumerate(antigas)},
                            _ANTIGAS_PARECIDAS)
        escolhidas = [antigas[int(c)] for c in sorted(achadas, key=int)] + escolhidas
    linhas = []
    for m in escolhidas:
        quando = idade(m.get("ts"))
        marca = ", ".join(x for x in (m.get("tipo"), quando) if x)
        nome = f" `{m['nome']}`" if m.get("nome") else ""
        linhas.append(f"- {m.get('descricao') or m['texto']}{f' ({marca})' if marca else ''}{nome}")
    return _COMO_USAR.read_text(encoding="utf-8").strip() + "\n\n" + "\n".join(linhas)


class UserMemoryStore:
    """Persiste a memória do usuário sobre o backend de sessão (get/set/delete
    com TTL). Cada usuário tem uma lista de fatos sob a chave `umem:{user_id}`."""

    def __init__(self, backend: Any):
        self._backend = backend

    def _key(self, user_id: str) -> str:
        return f"umem:{user_id}"

    async def all(self, user_id: str) -> List[Dict[str, Any]]:
        data = await self._backend.get(self._key(user_id))
        if isinstance(data, dict):
            return data.get("memories", [])
        return []

    async def remember(self, user_id: str, texto: str, sessao: Optional[str] = None) -> bool:
        """`sessao` é a conversa de onde veio; sem ela, foi ensinada pela tela."""
        texto = (texto or "").strip()
        if not texto:
            return False
        memorias = await self.all(user_id)
        # Dedupe EXATA...
        if any(m["texto"].lower() == texto.lower() for m in memorias):
            return False
        # ...e por ASSUNTO: se já existe uma memória sobre o mesmo tópico (ex.:
        # "foco Norte" e "interesse recorrente Norte" -> ambas {norte}), não
        # acumula quase-duplicata. Determinístico, sem LLM.
        novos = _sig_tokens(texto)
        if novos:
            for m in memorias:
                existentes = _sig_tokens(m.get("texto", ""))
                if not existentes:
                    continue
                inter = novos & existentes
                if inter and (novos <= existentes or existentes <= novos
                              or len(inter) / len(novos | existentes) >= 0.5):
                    return False
        # O id nao pode repetir depois de apagar uma: a tela apaga por id.
        proximo = max((int(m.get("id") or 0) for m in memorias), default=0) + 1
        nova = {"id": proximo, "texto": texto[:_MAX_FATO_CHARS], "ts": time.time()}
        if sessao:
            nova["sessao"] = sessao
        memorias.append(nova)
        memorias = memorias[-_MAX_MEMORIAS:]
        await self._backend.set(self._key(user_id), {"memories": memorias}, _MEM_TTL)
        return True

    async def forget(self, user_id: str, termo: Optional[str] = None) -> int:
        memorias = await self.all(user_id)
        if not memorias:
            return 0
        if termo:
            termo_l = termo.lower()
            restantes = [m for m in memorias if termo_l not in m["texto"].lower()]
        else:
            restantes = []
        removidos = len(memorias) - len(restantes)
        if removidos:
            await self._backend.set(self._key(user_id), {"memories": restantes}, _MEM_TTL)
        return removidos


    async def remove_texto(self, user_id: str, texto: str) -> bool:
        """Apaga a memoria com este texto exato. O "Desfazer" do chat só conhece
        o texto aprendido, e `forget` apagaria tudo que contivesse o termo."""
        alvo = (texto or "").strip().lower()
        memorias = await self.all(user_id)
        restantes = [m for m in memorias if m.get("texto", "").strip().lower() != alvo]
        if not alvo or len(restantes) == len(memorias):
            return False
        await self._backend.set(self._key(user_id), {"memories": restantes}, _MEM_TTL)
        return True

    async def remove(self, user_id: str, mem_id: int) -> bool:
        """Apaga uma memoria pelo id (a tela de Memoria)."""
        memorias = await self.all(user_id)
        restantes = [m for m in memorias if int(m.get("id") or 0) != int(mem_id)]
        if len(restantes) == len(memorias):
            return False
        await self._backend.set(self._key(user_id), {"memories": restantes}, _MEM_TTL)
        return True


def get_user_memory_store(session_store: Any, raiz: Optional[Path] = None):
    """A memória em arquivos; o backend de sessão só entrega o que já tinha."""
    from .memoria_em_arquivos import MemoriaEmArquivos

    return MemoriaEmArquivos(raiz, legado=UserMemoryStore(session_store))
