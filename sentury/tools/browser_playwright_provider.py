"""Adapter Playwright: percepção textual primeiro, screenshot só por pedido.

O provider é preguiçoso porque ``BrowserProvider.create_session`` é síncrono,
mas o despachante roda dentro de asyncio. Chromium só nasce na primeira ação.
Cada navegação de documento passa pela mesma guarda de ``tools.web``: a rota
também vê redirecionamentos, portanto validar apenas a URL inicial não basta.
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from . import web
from .browser_contracts import Action, BrowserCapability, Observation
from .browser_provider import BrowserProvider


_PAPEIS_INTERATIVOS = {
    "button", "checkbox", "combobox", "link", "listbox", "menuitem",
    "option", "radio", "searchbox", "slider", "spinbutton", "switch",
    "tab", "textbox", "treeitem",
}
_PAPEIS_UTEIS = _PAPEIS_INTERATIVOS | {
    "alert", "cell", "columnheader", "heading", "img", "listitem",
    "paragraph", "row", "rowheader", "status", "StaticText",
}


def _pasta_dos_navegadores() -> Path | None:
    """Onde o `playwright install` guarda os navegadores, sem subir o driver."""
    import os
    import sys

    escolhida = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if escolhida == "0":
        try:
            import playwright

            return Path(playwright.__file__).parent / "driver" / "package" / ".local-browsers"
        except ImportError:
            return None
    if escolhida:
        return Path(escolhida).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "ms-playwright" if base else None
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "ms-playwright"


def chromium_baixado() -> bool | None:
    """Se o Chromium que ESTA versao do Playwright usa foi baixado.

    `None` quando nao da para saber: ai quem pergunta segue como antes. O
    pacote instalado sem `playwright install chromium` fazia `is_available()`
    dizer que sim, o registro escolher o Playwright, e a falha so aparecer na
    primeira acao. Le a lista do proprio pacote (`browsers.json`) em vez de
    subir o driver: isto roda a cada despacho.
    """
    import json

    try:
        import playwright

        lista = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        navegadores = json.loads(lista.read_text(encoding="utf-8"))["browsers"]
        revisoes = {b["name"]: b["revision"] for b in navegadores}
    except Exception:
        return None
    pasta = _pasta_dos_navegadores()
    if pasta is None:
        return None
    candidatos = [
        pasta / f"{nome.replace('-', '_')}-{revisoes[nome]}"
        for nome in ("chromium-headless-shell", "chromium") if nome in revisoes
    ]
    if not candidatos:
        return None
    return any((c / "INSTALLATION_COMPLETE").exists() for c in candidatos)


def _valor_ax(valor: Any) -> Any:
    return valor.get("value") if isinstance(valor, dict) and "value" in valor else valor


# Escolhe a opção de uma lista no controle; o mesmo da extensão do Chrome.
_ESCOLHER = r"""function (texto) {
  const lista = this.tagName === 'OPTION' ? this.closest('select') : (this.tagName === 'SELECT' ? this : null);
  if (!lista) return null;
  const alvo = this.tagName === 'OPTION' ? this : Array.from(lista.options).find(o =>
    o.text.trim().toLowerCase() === String(texto || '').trim().toLowerCase() || o.value === texto);
  if (!alvo) return 'sem opção «' + texto + '» na lista; as que existem: ' + Array.from(lista.options).map(o => o.text.trim()).join(', ');
  lista.value = alvo.value;
  lista.dispatchEvent(new Event('input', { bubbles: true }));
  lista.dispatchEvent(new Event('change', { bubbles: true }));
  return '';
}"""


class PlaywrightBrowserSession(BrowserCapability):
    def __init__(
        self,
        session_id: str,
        *,
        headless: bool = True,
        fixture: Path | None = None,
        settle_ms: int = 180,
        sobreposicao: bool | None = None,
    ) -> None:
        self.session_id = session_id
        self._headless = headless
        # Borda, seta e balao so quando ha alguem vendo a janela.
        self._sobreposicao = (not headless) if sobreposicao is None else sobreposicao
        self._fixture = fixture
        self._settle_ms = settle_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._cdp = None
        self._epoch = 0
        self._proxima_ref = 1
        self._refs_por_backend: dict[int, str] = {}
        self._backend_por_ref: dict[str, int] = {}
        self._anterior: dict[str, dict[str, Any]] | None = None
        self._console: list[dict[str, str]] = []
        self._navegacao_recusada: str | None = None
        self._lock = asyncio.Lock()

    def esta_viva(self) -> bool:
        """A sessão preguiçosa é válida até o processo ou a aba desaparecer."""
        if self._page is None:
            return self._browser is None and self._context is None and self._playwright is None
        navegador_vivo = self._browser is not None and self._browser.is_connected()
        return bool(navegador_vivo and not self._page.is_closed())

    async def _iniciar(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                'Playwright não instalado; use pip install -e ".[extras]" (com o Chrome instalado, não precisa baixar navegador)',
            ) from exc

        self._playwright = await async_playwright().start()
        from .navegador_local import abrir_async

        self._browser = await abrir_async(self._playwright, headless=self._headless)
        self._context = await self._browser.new_context()
        if self._sobreposicao:
            from .browser_sobreposicao import SCRIPT

            await self._context.add_init_script(script=SCRIPT)
        self._page = await self._context.new_page()
        self._page.on("console", lambda mensagem: self._console.append({
            "tipo": mensagem.type,
            "texto": mensagem.text[:1000],
        }))
        await self._page.route("**/*", self._interceptar)
        self._cdp = await self._context.new_cdp_session(self._page)
        if self._fixture is not None:
            await self._page.set_content(self._fixture.read_text(encoding="utf-8"), wait_until="domcontentloaded")

    async def _interceptar(self, route, request) -> None:
        if request.is_navigation_request():
            try:
                web.validar_url_do_navegador(request.url)
            except web.UrlRecusada as exc:
                self._navegacao_recusada = str(exc)
                await route.abort("blockedbyclient")
                return
        await route.continue_()

    async def _esperar(self) -> None:
        if self._page is None:
            return
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=2500)
        except Exception:
            pass
        await self._page.wait_for_timeout(self._settle_ms)

    async def _marcar_ref(self, backend_id: int, ref: str) -> None:
        if self._cdp is None:
            return
        try:
            resolvido = await self._cdp.send("DOM.resolveNode", {"backendNodeId": backend_id})
            objeto = resolvido.get("object", {}).get("objectId")
            if not objeto:
                return
            await self._cdp.send("Runtime.callFunctionOn", {
                "objectId": objeto,
                "functionDeclaration": "function(ref){this.setAttribute('data-sentury-ref', ref)}",
                "arguments": [{"value": ref}],
                "returnByValue": True,
            })
        except Exception:
            # Nó textual ou removido entre a leitura e a marcação: ele continua
            # legível, apenas não vira alvo interativo.
            return

    async def _arvore(self) -> list[dict[str, Any]]:
        if self._cdp is None:
            return []
        resposta = await self._cdp.send("Accessibility.getFullAXTree")
        itens: list[dict[str, Any]] = []
        for no in resposta.get("nodes", []):
            if no.get("ignored"):
                continue
            papel = str(_valor_ax(no.get("role")) or "")
            nome = str(_valor_ax(no.get("name")) or "").strip()
            if papel not in _PAPEIS_UTEIS or (not nome and papel not in {"row", "cell"}):
                continue
            item: dict[str, Any] = {"role": papel, "name": nome}
            backend_id = no.get("backendDOMNodeId")
            if papel in _PAPEIS_INTERATIVOS and backend_id:
                backend_id = int(backend_id)
                ref = self._refs_por_backend.get(backend_id)
                if ref is None:
                    ref = f"e{self._proxima_ref}"
                    self._proxima_ref += 1
                    self._refs_por_backend[backend_id] = ref
                    self._backend_por_ref[ref] = backend_id
                item["ref"] = ref
                await self._marcar_ref(backend_id, ref)
            if no.get("parentId"):
                item["parent"] = str(no["parentId"])
            item["node"] = str(no.get("nodeId") or "")
            itens.append(item)
        return itens

    @staticmethod
    def _chave(item: dict[str, Any]) -> str:
        return str(item.get("ref") or item.get("node") or f"{item.get('role')}:{item.get('name')}")

    async def _observar(self, *, completo: bool = False) -> Observation:
        if self._page is None:
            raise RuntimeError("sessão Playwright não iniciada")
        arvore = await self._arvore()
        atual = {self._chave(item): item for item in arvore}
        if self._anterior is None or completo:
            dados: dict[str, Any] = {"modo": "completo", "arvore": arvore}
        else:
            anterior = self._anterior
            dados = {
                "modo": "diff",
                "entrou": [atual[chave] for chave in atual.keys() - anterior.keys()],
                "saiu": [anterior[chave] for chave in anterior.keys() - atual.keys()],
                "mudou": [
                    {"antes": anterior[chave], "depois": atual[chave]}
                    for chave in atual.keys() & anterior.keys()
                    if atual[chave] != anterior[chave]
                ],
            }
        self._anterior = atual
        bloqueio = await self._motivo_bloqueio()
        return Observation(
            fonte="playwright_accessibility",
            dados=dados,
            epoch=self._epoch,
            confianca=1.0,
            interativa=any("ref" in item for item in arvore),
            metadados={
                "url": self._page.url,
                "titulo": await self._page.title(),
                "navegacao_recusada": self._navegacao_recusada,
                "bloqueio": bloqueio,
                "screenshot": False,
            },
        )

    async def _motivo_bloqueio(self) -> str | None:
        if self._page is None:
            return None
        texto = f"{await self._page.title()} {(await self._page.locator('body').inner_text())[:4000]}".lower()
        if "captcha" in texto:
            return "captcha_failed"
        if "access denied" in texto or "acesso negado" in texto:
            return "access_denied"
        if "checking your browser" in texto or "verificando seu navegador" in texto:
            return "challenge_loop"
        return None

    def _alvo(self, ref: str):
        if not ref or ref not in self._backend_por_ref or self._page is None:
            raise ValueError(f"ref desconhecida: {ref}")
        return self._page.locator(f'[data-sentury-ref="{ref}"]')

    async def _escolher_na_lista(self, alvo, texto: str) -> bool:
        """Opção de <select> (ou a lista com `texto`) escolhida no controle:
        opção de lista fechada não tem caixa, e clicar nela quebra."""
        erro = await alvo.evaluate(f"(e, texto) => ({_ESCOLHER}).call(e, texto)", texto)
        if erro is None:
            return False
        if erro:
            raise ValueError(erro)
        return True

    def _nome_do_alvo(self, ref: str) -> str:
        return str(((self._anterior or {}).get(ref) or {}).get("name") or "")

    async def _anunciar(self, action: Action, alvo=None) -> None:
        """A seta vai ate o alvo e o balao diz a acao, antes de ela acontecer."""
        if not self._sobreposicao or self._page is None:
            return
        from . import browser_sobreposicao as sob

        texto = sob.rotulo(action.tipo, action.argumentos,
                           self._nome_do_alvo(str(action.argumentos.get("ref") or "")))
        if alvo is not None:
            await sob.apontar_para(self._page, alvo, texto, clique=action.tipo == "clicar",
                                   contornar=action.tipo == "digitar")
        elif action.tipo == "navegar":
            await sob.apontar_no_topo(self._page, texto, esperar=False)
        else:
            x, y = await sob._meio_da_tela(self._page)
            await sob.apontar(self._page, x, y, texto)

    async def trazer_para_frente(self) -> bool:
        """O "Mostrar janela" do cartao no chat."""
        if self._page is None:
            return False
        await self._page.bring_to_front()
        return True

    async def execute(self, action: Action) -> Observation:
        async with self._lock:
            await self._iniciar()
            assert self._page is not None
            args = action.argumentos
            representacao = str(args.get("representacao") or "accessibility")

            if action.tipo == "snapshot":
                if representacao == "dom":
                    from .browser_sobreposicao import sem_sobreposicao

                    return Observation(
                        "playwright_dom", sem_sobreposicao(await self._page.content())[:100_000], self._epoch,
                        1.0, False, {"url": self._page.url, "screenshot": False},
                    )
                if representacao == "jsonld":
                    dados = await self._page.locator('script[type="application/ld+json"]').all_text_contents()
                    return Observation(
                        "playwright_jsonld", dados, self._epoch, 1.0, False,
                        {"url": self._page.url, "screenshot": False},
                    )
                return await self._observar(completo=bool(args.get("completo")))

            if action.tipo == "imagens":
                # O print e da pagina: a borda e a seta saem antes e voltam depois.
                if self._sobreposicao:
                    from .browser_sobreposicao import esconder, mostrar

                    await esconder(self._page)
                try:
                    imagem = await self._page.screenshot(full_page=bool(args.get("pagina_inteira")))
                finally:
                    if self._sobreposicao:
                        await mostrar(self._page)
                return Observation(
                    "playwright_screenshot", base64.b64encode(imagem).decode("ascii"),
                    self._epoch, 1.0, False, {"url": self._page.url, "screenshot": True},
                )
            if action.tipo == "console":
                return Observation("playwright_console", list(self._console), self._epoch, 1.0, False)
            if action.tipo == "navegar":
                url = web.validar_url_do_navegador(str(args.get("url") or ""))
                if self._page.url != url:
                    self._navegacao_recusada = None
                    await self._page.goto(url, wait_until="domcontentloaded")
                # Depois de carregar: a pagina nova nasce sem a seta acesa.
                await self._anunciar(action)
            elif action.tipo == "clicar" and await self._escolher_na_lista(
                    self._alvo(str(args.get("ref") or "")), ""):
                await self._anunciar(action, self._alvo(str(args.get("ref") or "")))
            elif action.tipo == "digitar" and args.get("ref") and await self._escolher_na_lista(
                    self._alvo(str(args.get("ref"))), str(args.get("texto") or "")):
                await self._anunciar(action, self._alvo(str(args.get("ref"))))
            elif action.tipo == "clicar":
                alvo = self._alvo(str(args.get("ref") or ""))
                # Link conhecido é validado antes do gesto. A rota continua
                # obrigatória para redirects e navegações disparadas por JS,
                # mas abortar no meio de um clique faria o Chromium trocar a
                # página útil por chrome-error://chromewebdata/.
                href = await alvo.get_attribute("href")
                self._navegacao_recusada = None
                await self._anunciar(action, alvo)
                if href:
                    absoluto = await alvo.evaluate("elemento => elemento.href")
                    try:
                        web.validar_url_do_navegador(str(absoluto or href))
                    except web.UrlRecusada as exc:
                        self._navegacao_recusada = str(exc)
                    else:
                        await alvo.click()
                else:
                    await alvo.click()
            elif action.tipo == "digitar":
                texto = str(args.get("texto") or "")
                if args.get("ref"):
                    campo = self._alvo(str(args.get("ref")))
                    await self._anunciar(action, campo)
                    await campo.fill(texto)
                else:
                    # Sem ref: o campo que já tem o foco (o que acabou de ser clicado).
                    campo = await self._page.evaluate_handle("document.activeElement")
                    editavel = await campo.evaluate(
                        "e => !!e && (e.isContentEditable || /^(INPUT|TEXTAREA)$/.test(e.tagName))")
                    if not editavel:
                        raise ValueError("nenhum campo de texto com o foco: clique no campo antes, "
                                         "ou mande o `ref` dele")
                    await self._anunciar(action, campo.as_element())
                    await self._page.keyboard.type(texto)
                if args.get("enviar"):
                    await self._page.keyboard.press("Enter")
            elif action.tipo == "rolar":
                await self._anunciar(action)
                await self._page.mouse.wheel(
                    int(args.get("delta_x") or 0), int(args.get("delta_y") or args.get("y") or 600),
                )
            else:
                raise ValueError(f"ação Playwright não implementada: {action.tipo}")

            self._epoch += 1
            await self._esperar()
            return await self._observar()

    async def aclose(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = self._context = self._browser = self._playwright = self._cdp = None

    def close_nowait(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.aclose())
        else:
            loop.create_task(self.aclose())


class PlaywrightBrowserProvider(BrowserProvider):
    def __init__(
        self,
        *,
        headless: bool | None = None,
        fixture: str | Path | None = None,
        name: str = "playwright",
    ) -> None:
        if headless is None:
            from .browser_sobreposicao import navegador_visivel

            # A pessoa ve a janela quando ha tela; num servidor, headless.
            headless = not navegador_visivel()
        self._headless = headless
        self._fixture = Path(fixture).resolve() if fixture is not None else None
        self._name = name
        self._sessoes: dict[str, PlaywrightBrowserSession] = {}

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        try:
            import playwright  # noqa: F401
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError:
            return False
        from .navegador_local import precisa_do_chromium

        # Com o Chrome ou o Edge instalado, o Chromium baixado é dispensável.
        if precisa_do_chromium() and chromium_baixado() is False:
            return False
        return self._fixture is None or self._fixture.is_file()

    def create_session(self, task_id: str) -> BrowserCapability:
        session_id = f"{self.name}:{task_id}"
        sessao = PlaywrightBrowserSession(
            session_id,
            headless=self._headless,
            fixture=self._fixture,
        )
        self._sessoes[session_id] = sessao
        return sessao

    def close_session(self, session_id: str) -> bool:
        sessao = self._sessoes.pop(session_id, None)
        if sessao is None:
            return False
        sessao.close_nowait()
        return True

    def emergency_cleanup(self, session_id: str) -> None:
        self.close_session(session_id)


__all__ = ["PlaywrightBrowserProvider", "PlaywrightBrowserSession"]
