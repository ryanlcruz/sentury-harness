"""O destino declarado impede que uma ferramenta da caixa execute na HQ."""
import os


def caixa_obrigatoria():
    return os.environ.get("SENTURY_CAIXA_OBRIGATORIA", "").strip().lower() in ("1", "true", "sim")


def recusa(meta):
    from .escopo import agente_do_turno

    if agente_do_turno() is None or not caixa_obrigatoria():
        return None
    destino = meta.get("destino_residente")
    if destino == "hq":
        return None
    if destino == "caixa" and meta.get("operacao_caixa"):
        return None
    return {
        "ok": False,
        "modo": "caixa",
        "erro": "Esta ferramenta não tem execução isolada disponível para o residente. "
                "Executá-la na HQ daria acesso ao ambiente do servidor, por isso a chamada foi recusada. "
                "Considere uma ferramenta da caixa ou peça à pessoa a capacidade que falta.",
    }
