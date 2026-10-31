/**
 * A página ouvindo os blocos vivos. O bloco só fala por `postMessage`, e a
 * página só confia no quadro de onde a mensagem veio: ajusta a altura dele e
 * repassa a mensagem que ele propõe, que a pessoa confirma antes de ir.
 */
export const EVENTO_PROPOSTA = 'sentury:bloco-vivo-proposta';

export interface PropostaDoBloco {
  texto: string;
  quadro: HTMLIFrameElement;
}

const ALTURA_MINIMA = 48;
const ALTURA_MAXIMA = 1600;

let instalado = false;

export function ouvirBlocosVivos(): void {
  if (instalado || typeof window === 'undefined') return;
  instalado = true;
  window.addEventListener('message', (evento: MessageEvent) => {
    const dado = evento.data as { sentury?: string; altura?: unknown; enviar?: unknown } | null;
    if (!dado || dado.sentury !== 'bloco-vivo') return;
    const quadro = Array.from(document.querySelectorAll<HTMLIFrameElement>('iframe.bloco-vivo__quadro'))
      .find(q => q.contentWindow === evento.source);
    if (!quadro) return;
    if (typeof dado.altura === 'number' && Number.isFinite(dado.altura)) {
      const altura = Math.min(ALTURA_MAXIMA, Math.max(ALTURA_MINIMA, Math.ceil(dado.altura) + 4));
      quadro.style.height = `${altura}px`;
    }
    if (typeof dado.enviar === 'string' && dado.enviar.trim()) {
      window.dispatchEvent(new CustomEvent<PropostaDoBloco>(EVENTO_PROPOSTA, {
        detail: { texto: dado.enviar.trim().slice(0, 2000), quadro },
      }));
    }
  });
}
