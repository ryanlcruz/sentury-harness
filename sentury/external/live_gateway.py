"""Gemini Live (voz em tempo real): a Sentury atendendo por "ligação".

Proxy: o browser fala com o nosso WebSocket, e ESTE módulo fala com a Gemini Live
API (a GEMINI_API_KEY nunca sai do servidor). Fluxo: mic do browser (PCM16 16kHz)
→ Gemini → áudio de volta (PCM 24kHz) → browser. Interrupção (barge-in) é nativa:
se a pessoa fala por cima, a Gemini manda `interrupted` e mandamos o browser
esvaziar a fila de áudio na hora.

Também expõe algumas ferramentas de LEITURA do setor ativo via function
calling: então no meio da conversa a Sentury "puxa" dado real. Nada pesado.

google-genai é import TARDIO: se a lib não estiver instalada, o app sobe normal e
só o /sentury/live fica indisponível.
"""
import base64
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Half-cascade: melhor uso de ferramentas (a pessoa quer que ela "chame APIs").
# Live tem RPM praticamente ilimitado no free: daí o "modo quase ilimitado".
DEFAULT_LIVE_MODEL = "gemini-3.1-flash-live-preview"
DEFAULT_VOICE = "Sulafat"

LIVE_PERSONA = (
    "Você é o Sentury, atendendo AGORA por "
    "LIGAÇÃO DE VOZ. Ao se apresentar, diga apenas que é o Sentury. "
    "Abra a chamada com algo curto e caloroso, tipo: 'Alô! Aqui é a Sentury — estou na escuta.' "
    "Fale como gente ao telefone: frases curtas, naturais, sem jargão nem listas longas — é voz, não texto. "
    "Você está num modo de conversa quase ilimitado; aproveite pra ser ágil e prestativa. "
    "Quando a pessoa pedir número/indicador, CHAME as ferramentas pra puxar o dado REAL antes de "
    "responder — não invente. As ferramentas que você tem na ligação chegam com a chamada; "
    "se não houver nenhuma que sirva, diga isso em vez de estimar. "
    "Se a pessoa estiver compartilhando a TELA, comente o que aparece e ajude com base nisso. "
    "Se ainda for pouco, diga que isso é só o começo e que dá pra evoluir. "
    "Responda sempre em português do Brasil."
)


def _tool_declarations() -> list:
    """Ferramentas de leitura expostas à Sentury na ligação (function calling).

    Quem publica é o setor ativo (`do_setor.ferramentas_da_voz`): o motor não
    tem consulta própria na voz, e sem setor a ligação não oferece nenhuma.
    Todas são de leitura e devolvem texto curto (é voz).
    """
    from ..domains.do_setor import ferramentas_da_voz

    ferramentas = ferramentas_da_voz()
    if not ferramentas:
        return []
    from google.genai import types
    S = types.Schema
    T = types.Type

    def _declarar(f: dict):
        params = f.get("parametros") or {}
        kwargs = {}
        if params:
            kwargs["parameters"] = S(type=T.OBJECT, properties={
                campo: S(type=T.STRING, description=str(desc)) for campo, desc in params.items()
            })
        return types.FunctionDeclaration(name=f["nome"], description=f.get("descricao", ""), **kwargs)

    return [types.Tool(function_declarations=[_declarar(f) for f in ferramentas])]


async def execute_live_tool(name: str, data_store: Any, args: Optional[dict] = None) -> str:
    """Executa uma ferramenta de leitura do setor e devolve um texto curto (falável)."""
    from ..domains.do_setor import executar_na_voz, ferramentas_da_voz

    # O nome precisa estar no que o setor publica AGORA: a sessão pode ter sido
    # aberta antes de alguém trocar o setor.
    if name not in {f["nome"] for f in ferramentas_da_voz()}:
        return "Essa consulta não faz parte do que este Sentury tem na mesa agora."
    try:
        resposta = await executar_na_voz(name, data_store, args or {})
    except Exception as exc:
        logger.warning("Ferramenta live '%s' falhou: %s", name, exc)
        return "Tive um problema ao puxar esse dado agora."
    return resposta or "Não reconheci essa consulta."


def build_live_config(api_key: str, voz: Optional[str] = None):
    """Monta o cliente + config da sessão Live (áudio, voz, persona, tools)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    config_kwargs = dict(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=LIVE_PERSONA)]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voz or DEFAULT_VOICE)
            )
        ),
        tools=_tool_declarations(),
    )
    # Estes campos variam por versão do SDK: só adiciona se existirem (senão a
    # ligação nem sobe, como o erro 'AudioTranscriptionConfig' no Render).
    if hasattr(types, "AudioTranscriptionConfig"):
        # transcrição/legenda do que foi falado (opcional; a voz funciona sem ela)
        config_kwargs["input_audio_transcription"] = types.AudioTranscriptionConfig()
        config_kwargs["output_audio_transcription"] = types.AudioTranscriptionConfig()
    try:
        config = types.LiveConnectConfig(media_resolution="MEDIA_RESOLUTION_MEDIUM", **config_kwargs)
    except Exception:
        config = types.LiveConnectConfig(**config_kwargs)  # sem media_resolution se a versão não aceitar
    return client, config


async def run_live_bridge(websocket, data_store, api_key: str, model: Optional[str] = None,
                          voz: Optional[str] = None) -> None:
    """Ponte browser <-> Gemini Live. Roda até a ligação terminar.

    Protocolo com o browser (JSON):
      recebe: {"type":"audio","data":<base64 pcm16 16k>} | {"type":"end"}
      envia:  {"type":"ready"} | {"type":"audio","data":<base64 pcm 24k>}
              | {"type":"interrupted"} | {"type":"text","role":..., "text":...}
              | {"type":"tool","name":...} | {"type":"error","detail":...}
    """
    import asyncio

    from google.genai import types

    model = model or DEFAULT_LIVE_MODEL
    client, config = build_live_config(api_key, voz)

    async with client.aio.live.connect(model=model, config=config) as session:
        await websocket.send_json({"type": "ready"})

        async def browser_to_gemini():
            while True:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                if msg.get("type") == "audio":
                    pcm = base64.b64decode(msg["data"])
                    await session.send_realtime_input(
                        audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
                    )
                elif msg.get("type") == "image":
                    # frame de tela/câmera (baixa resolução, poucos por segundo)
                    jpg = base64.b64decode(msg["data"])
                    await session.send_realtime_input(
                        video=types.Blob(data=jpg, mime_type="image/jpeg")
                    )
                elif msg.get("type") == "end":
                    break

        async def gemini_to_browser():
            while True:
                async for response in session.receive():
                    # Áudio da Sentury → browser
                    if response.data:
                        await websocket.send_json({
                            "type": "audio",
                            "data": base64.b64encode(response.data).decode(),
                        })
                    sc = getattr(response, "server_content", None)
                    if sc is not None:
                        if getattr(sc, "interrupted", False):
                            await websocket.send_json({"type": "interrupted"})
                        # Transcrições (opcional, pro painel/legenda)
                        it = getattr(sc, "input_transcription", None)
                        if it and getattr(it, "text", None):
                            await websocket.send_json({"type": "text", "role": "user", "text": it.text})
                        ot = getattr(sc, "output_transcription", None)
                        if ot and getattr(ot, "text", None):
                            await websocket.send_json({"type": "text", "role": "sentury", "text": ot.text})
                    # Function calling: puxa dado real e devolve pra Sentury
                    tc = getattr(response, "tool_call", None)
                    if tc and getattr(tc, "function_calls", None):
                        respostas = []
                        for fc in tc.function_calls:
                            await websocket.send_json({"type": "tool", "name": fc.name})
                            fc_args = dict(fc.args) if getattr(fc, "args", None) else None
                            resultado = await execute_live_tool(fc.name, data_store, fc_args)
                            respostas.append(types.FunctionResponse(
                                id=fc.id, name=fc.name, response={"result": resultado},
                            ))
                        await session.send_tool_response(function_responses=respostas)

        try:
            await asyncio.gather(browser_to_gemini(), gemini_to_browser())
        except Exception as exc:
            logger.info("Ligação Live encerrada: %s", exc)
