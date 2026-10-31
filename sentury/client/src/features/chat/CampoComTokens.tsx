import React, { forwardRef, useCallback, useImperativeHandle, useLayoutEffect, useRef } from 'react';

/** Os tokens que viram badge: `@nome` e `/nome`, no começo ou depois de espaço. */
const TOKEN = /((?:^|(?<=\s))[@/][a-z0-9][a-z0-9-]*)/gi;

export interface CampoComTokensHandle {
  /** Troca o gatilho digitado antes do cursor (`@at`, `/ar`) pelo badge do token. */
  inserirToken: (token: string) => void;
  /** Apaga o gatilho antes do cursor, sem inserir nada. */
  apagarGatilho: () => void;
  focar: () => void;
}

interface Props {
  valor: string;
  onMudar: (valor: string) => void;
  /** O texto antes do cursor, já com os badges escritos como token. */
  onCursor: (antes: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
  onColarArquivos: (arquivos: File[]) => void;
  /** O badge de um token conhecido, ou null para deixá-lo como texto. */
  desenhar: (token: string) => HTMLElement | null;
  placeholder: string;
}

function serializar(no: Node): string {
  if (no.nodeType === Node.TEXT_NODE) return (no.textContent || '').replace(/ /g, ' ');
  if (!(no instanceof HTMLElement)) return '';
  if (no.dataset.token) return no.dataset.token;
  if (no.tagName === 'BR') return '\n';
  const dentro = Array.from(no.childNodes).map(serializar).join('');
  return no.tagName === 'DIV' && no.previousSibling ? `\n${dentro}` : dentro;
}

/** Campo de texto em que menções, funções e skills são badges no meio da frase.
 * O valor continua sendo texto simples (`@atlas`, `/arxiv`); o badge é só como
 * ele aparece, e o Backspace o apaga inteiro. */
export const CampoComTokens = forwardRef<CampoComTokensHandle, Props>(function CampoComTokens(
  { valor, onMudar, onCursor, onKeyDown, onColarArquivos, desenhar, placeholder }, ref,
) {
  const campo = useRef<HTMLDivElement>(null);
  const emitido = useRef<string | null>(null);
  const desenhoAnterior = useRef(desenhar);

  const texto = () => (campo.current ? Array.from(campo.current.childNodes).map(serializar).join('') : '');

  const avisarCursor = useCallback(() => {
    const raiz = campo.current;
    const sel = window.getSelection();
    if (!raiz || !sel || !sel.rangeCount || !raiz.contains(sel.anchorNode)) return;
    const antes = document.createRange();
    antes.selectNodeContents(raiz);
    antes.setEnd(sel.anchorNode as Node, sel.anchorOffset);
    const fragmento = antes.cloneContents();
    onCursor(Array.from(fragmento.childNodes).map(serializar).join(''));
  }, [onCursor]);

  // Um token conhecido digitado por inteiro vira selo ao chegar o espaço, como se
  // tivesse sido escolhido na lista: `@bruno ` fica destacado sem precisar clicar.
  const virarTokenDigitado = useCallback(() => {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !campo.current) return;
    const range = sel.getRangeAt(0);
    const alvo = range.startContainer;
    if (alvo.nodeType !== Node.TEXT_NODE || !campo.current.contains(alvo)) return;
    const antes = (alvo.textContent || '').slice(0, range.startOffset).replace(/ /g, ' ');
    const achado = antes.match(/(?:^|\s)([@/][a-z0-9][a-z0-9-]*)\s$/i);
    if (!achado) return;
    const badge = desenhar(achado[1]);
    if (!badge) return;
    const inicio = range.startOffset - achado[1].length - 1;
    const troca = document.createRange();
    troca.setStart(alvo, inicio);
    troca.setEnd(alvo, range.startOffset);
    troca.deleteContents();
    const espaco = document.createTextNode(' ');
    troca.insertNode(espaco);
    troca.insertNode(badge);
    troca.setStartAfter(espaco);
    troca.collapse(true);
    sel.removeAllRanges();
    sel.addRange(troca);
  }, [desenhar]);

  const emitir = useCallback(() => {
    virarTokenDigitado();
    const atual = texto();
    // O navegador deixa um <br> sozinho quando tudo é apagado: o placeholder precisa do vazio.
    if (!atual && campo.current) campo.current.innerHTML = '';
    emitido.current = atual;
    onMudar(atual);
    avisarCursor();
  }, [onMudar, avisarCursor, virarTokenDigitado]);

  // Valor que veio de fora (limpar no envio, ditado, item da fila): redesenha.
  useLayoutEffect(() => {
    const raiz = campo.current;
    // A lista de residentes e skills pode chegar depois: o que já era token vira badge.
    if (!raiz || (valor === emitido.current && desenhar === desenhoAnterior.current)) return;
    desenhoAnterior.current = desenhar;
    raiz.innerHTML = '';
    for (const parte of valor.split(TOKEN)) {
      if (!parte) continue;
      raiz.appendChild(desenhar(parte) || document.createTextNode(parte));
    }
    emitido.current = valor;
    if (document.activeElement === raiz) {
      const sel = window.getSelection();
      sel?.selectAllChildren(raiz);
      sel?.collapseToEnd();
    }
  }, [valor, desenhar]);

  // O cursor dentro do campo; sem ele (a pessoa rolou a conversa ou clicou fora
  // e voltou pela lista), o fim do último texto, onde o gatilho foi digitado.
  // Desistir em silêncio deixava o clique na sugestão sem efeito nenhum.
  const pontoDeEdicao = (sel: Selection): Range | null => {
    const raiz = campo.current;
    if (!raiz) return null;
    if (sel.rangeCount) {
      const range = sel.getRangeAt(0);
      if (range.startContainer.nodeType === Node.TEXT_NODE && raiz.contains(range.startContainer)) return range;
    }
    const caminho = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    let ultimo: Node | null = null;
    while (caminho.nextNode()) ultimo = caminho.currentNode;
    if (!ultimo) return null;
    const range = document.createRange();
    range.setStart(ultimo, (ultimo.textContent || '').length);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
    return range;
  };

  const trocarGatilho = (no: Node | null) => {
    const sel = window.getSelection();
    if (!sel) return false;
    const range = pontoDeEdicao(sel);
    if (!range) return false;
    const alvo = range.startContainer;
    const antes = (alvo.textContent || '').slice(0, range.startOffset);
    const gatilho = antes.match(/[@/][a-z0-9-]*$/i);
    if (!gatilho) return false;
    range.setStart(alvo, range.startOffset - gatilho[0].length);
    range.deleteContents();
    if (no) {
      const espaco = document.createTextNode(' ');
      range.insertNode(espaco);
      range.insertNode(no);
      range.setStartAfter(espaco);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    }
    return true;
  };

  useImperativeHandle(ref, () => ({
    inserirToken: (token: string) => {
      campo.current?.focus();
      const badge = desenhar(token);
      if (trocarGatilho(badge || document.createTextNode(`${token} `))) emitir();
    },
    apagarGatilho: () => { if (trocarGatilho(null)) emitir(); },
    focar: () => {
      const raiz = campo.current;
      if (!raiz) return;
      raiz.focus();
      const sel = window.getSelection();
      sel?.selectAllChildren(raiz);
      sel?.collapseToEnd();
    },
  }), [desenhar, emitir]);

  return (
    <div
      ref={campo}
      contentEditable
      suppressContentEditableWarning
      role="textbox"
      aria-multiline="true"
      aria-label={placeholder}
      data-placeholder={placeholder}
      onInput={emitir}
      onKeyUp={avisarCursor}
      onClick={avisarCursor}
      onKeyDown={event => {
        if (event.key === 'Enter' && event.shiftKey) {
          event.preventDefault();
          document.execCommand('insertText', false, '\n');
          return;
        }
        onKeyDown(event);
      }}
      onPaste={event => {
        const arquivos = Array.from(event.clipboardData?.files || []);
        event.preventDefault();
        if (arquivos.length) { onColarArquivos(arquivos); return; }
        document.execCommand('insertText', false, event.clipboardData.getData('text/plain'));
      }}
      className="min-h-10 max-h-[132px] w-full overflow-y-auto whitespace-pre-wrap break-words bg-transparent px-2 py-1.5 text-[15px] leading-7 text-zinc-800 outline-none empty:before:pointer-events-none empty:before:text-slate-400 empty:before:content-[attr(data-placeholder)]"
    />
  );
});
