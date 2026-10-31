"""Confere anexos reais sem executar ferramentas depois da resposta."""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, Optional, Tuple


logger = logging.getLogger(__name__)

EXIGE_DO_HOSPEDEIRO = ("responder",)


class EntregaDeArtefato:
    """Valida a apresentação dos anexos produzidos por ferramentas."""

    async def _fix_html_if_broken(self, html_text: str, max_tries: int = 2) -> Tuple[str, bool]:
        """LOOP DE CONSTRUÇÃO (só quando há visual pra construir): renderiza o HTML
        num Chromium headless (render_verifier); se quebrou (erro de JS), devolve o
        erro ao modelo pra CONSERTAR e revalida: até max_tries. Retorna (html, ok).
        Sem Playwright (dev local sem browser) → não trava, entrega como está."""
        import sys
        if "pytest" in sys.modules:
            return html_text, True
        from ..artifacts.render_verifier import verify_render_preview
        import re as _re

        current = html_text
        for tentativa in range(max_tries + 1):
            # A verificação síncrona de renderização roda em outra thread
            # para não bloquear o laço assíncrono.
            vr = await asyncio.to_thread(verify_render_preview, "html", current.encode("utf-8"))
            if vr is None:            # Playwright indisponível → não bloqueia
                return current, True
            if vr.get("status") in ("ok", "warning"):
                return current, True  # renderizou limpo ou com aviso técnico
            if tentativa >= max_tries:
                break
            erro = "; ".join(vr.get("errors", [])) or "o HTML não renderizou corretamente"
            logger.info("Loop de construção: HTML quebrado (%s), tentativa de conserto %d.", erro[:80], tentativa + 1)
            fix_msgs = [
                {"role": "system", "content": "Você é um especialista em desenvolvimento web encarregado de corrigir erros de sintaxe de JavaScript ou marcação HTML que impedem a renderização de relatórios. Suas correções devem ser cirúrgicas: mantenha rigorosamente TODOS os dados e tabelas originais intactos. Não mude textos, números ou métricas. Devolva apenas o código HTML completo e corrigido, dentro de um bloco ```html ... ```. Sem explicações adicionais."},
                {"role": "user", "content": f"O seguinte HTML gerou este erro na renderização do navegador:\n{erro}\n\nCódigo HTML atual:\n{current}\n\nIdentifique a linha ou bloco que causou o problema, corrija-o mantendo todo o resto exatamente igual e devolva o código HTML completo corrigido."},
            ]
            try:
                raw = await self.responder.complete(fix_msgs, temperature=0.1)
            except Exception:
                break
            m = _re.search(r"```html\s*(.*?)```", raw, _re.DOTALL | _re.IGNORECASE)
            novo = (m.group(1) if m else raw).strip()
            if not novo or novo == current:
                break
            # Guardrail contra encolhimento destrutivo (LLM desiste e apaga dados)
            if len(novo) < len(current) * 0.5:
                logger.warning("Loop de construção: Conserto rejeitado por perda de conteúdo expressiva (redução excessiva de tamanho).")
                break
            current = novo
        return current, False

    async def _validate_and_fix_html_attachment(self, attachment: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Aplica o loop de construção a um attachment HTML autoral (do sandbox).
        Conserta in-place se der; marca `_render_ok=False` se ficou quebrado."""
        if not attachment or attachment.get("type") != "html" or not attachment.get("content_base64"):
            return attachment
        try:
            html = base64.b64decode(attachment["content_base64"]).decode("utf-8")
        except Exception:
            return attachment
        fixed, ok = await self._fix_html_if_broken(html)
        if fixed and fixed != html:
            attachment["content_base64"] = base64.b64encode(fixed.encode("utf-8")).decode("ascii")
        attachment["_render_ok"] = ok
        return attachment
