/**
 * Os botões dos blocos de código no chat. "Copiar" leva o código; "Visualizar"
 * troca o código pelo desenho, no mesmo bloco vivo isolado, e volta.
 */
import { documentoDoBloco, quadroDoBloco } from './moldura';

export function alternarVisualizacao(bloco: HTMLElement, codigo: string, botao: HTMLElement): void {
  const pre = bloco.querySelector('pre');
  const quadro = bloco.querySelector<HTMLIFrameElement>('iframe.bloco-vivo__quadro');
  if (quadro) {
    quadro.remove();
    pre?.removeAttribute('hidden');
    botao.textContent = 'Visualizar';
    return;
  }
  pre?.setAttribute('hidden', '');
  bloco.appendChild(quadroDoBloco(documentoDoBloco(codigo), 'Código visualizado'));
  botao.textContent = 'Ver código';
}

/** Trata o clique no corpo da mensagem; devolve o texto a copiar, quando for o caso. */
export function aoClicarNoCodigo(alvo: HTMLElement): string | null {
  const bloco = alvo.closest<HTMLElement>('.md-code');
  if (!bloco) return null;
  const codigo = bloco.querySelector('pre code')?.textContent ?? '';
  const visualizar = alvo.closest<HTMLElement>('[data-visualizar]');
  if (visualizar) {
    alternarVisualizacao(bloco, codigo, visualizar);
    return null;
  }
  const copiar = alvo.closest<HTMLElement>('[data-copy]');
  if (!copiar) return null;
  copiar.textContent = 'Copiado';
  window.setTimeout(() => { copiar.textContent = 'Copiar'; }, 1600);
  return codigo;
}
