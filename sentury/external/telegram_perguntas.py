"""Coleta o mesmo conjunto de decisões em mensagens menores no Telegram."""
import json
import time
import uuid
from ..harness.perguntas import resposta


class PerguntasTelegram:
    def __init__(self):
        self.pendentes = {}

    def abrir(self, chat_id, session_id, clarification):
        self.cancelar(chat_id)
        chave = uuid.uuid4().hex[:12]
        self.pendentes[chave] = {"chat": chat_id, "sessao": session_id,
                                "perguntas": clarification["questions"], "indice": 0,
                                "respostas": [], "selecionadas": [], "livre": False,
                                "hora": time.monotonic()}
        while len(self.pendentes) > 64:
            self.pendentes.pop(next(iter(self.pendentes)))
        return chave

    def cancelar(self, chat_id):
        for chave, pedido in list(self.pendentes.items()):
            if pedido["chat"] == chat_id:
                self.pendentes.pop(chave, None)

    def obter(self, chave, chat_id):
        pedido = self.pendentes.get(chave)
        if pedido and time.monotonic() - pedido["hora"] > 1800:
            self.pendentes.pop(chave, None)
            pedido = None
        return pedido if pedido and pedido["chat"] == chat_id else None

    def mensagem(self, chave, chat_id):
        p = self.obter(chave, chat_id)
        if p is None:
            return None
        i = p["indice"]
        q = p["perguntas"][i]
        texto = f"{i + 1} de {len(p['perguntas'])}: {q['question']}"
        texto += "\nEscolha uma ou mais." if q["multiSelect"] else "\nEscolha uma opção."
        linhas = []
        for n, opcao in enumerate(q["options"]):
            texto += f"\n{n + 1}. {opcao['label']}"
            if opcao.get("description"):
                texto += f": {opcao['description']}"
            marcado = "Selecionado: " if opcao["label"] in p["selecionadas"] else ""
            linhas.append([{"text": (marcado + opcao["label"])[:64],
                            "callback_data": f"sq:{chave}:{i}:{n}"}])
        linhas.append([{"text": "Outra resposta", "callback_data": f"sq:{chave}:{i}:outro"}])
        if q["multiSelect"]:
            linhas.append([{"text": "Continuar", "callback_data": f"sq:{chave}:{i}:ok"}])
        return {"chat_id": chat_id, "text": texto, "reply_markup": {"inline_keyboard": linhas}}

    def _avancar(self, chave, p, outro=""):
        p["respostas"].append({"selecionadas": p["selecionadas"], "outro": outro})
        p["indice"] += 1
        p["selecionadas"] = []
        p["livre"] = False
        if p["indice"] < len(p["perguntas"]):
            return None
        dado = resposta(p["perguntas"], p["respostas"])
        self.pendentes.pop(chave, None)
        return json.dumps(dado, ensure_ascii=False)

    def tocar(self, data, chat_id):
        partes = str(data).split(":")
        if len(partes) != 4 or partes[0] != "sq":
            return None
        _, chave, etapa, escolha = partes
        p = self.obter(chave, chat_id)
        if p is None or etapa != str(p["indice"]):
            return None
        q = p["perguntas"][p["indice"]]
        if escolha == "outro":
            p["livre"] = True
            return chave, None, "Escreva sua resposta nesta conversa."
        if escolha == "ok":
            if not p["selecionadas"]:
                return chave, None, "Escolha ao menos uma opção ou escreva outra resposta."
            return chave, self._avancar(chave, p), "Resposta registrada."
        if not escolha.isdigit() or int(escolha) >= len(q["options"]):
            return None
        rotulo = q["options"][int(escolha)]["label"]
        if q["multiSelect"]:
            if rotulo in p["selecionadas"]:
                p["selecionadas"].remove(rotulo)
            else:
                p["selecionadas"].append(rotulo)
            return chave, None, "Seleção atualizada."
        p["selecionadas"] = [rotulo]
        return chave, self._avancar(chave, p), "Resposta registrada."

    def texto_livre(self, chat_id, texto):
        for chave, p in list(self.pendentes.items()):
            if self.obter(chave, chat_id) and p["livre"]:
                if not texto.strip() or len(texto) > 500:
                    return chave, None, "Escreva até 500 caracteres."
                return chave, self._avancar(chave, p, texto.strip()), "Resposta registrada."
        return None
