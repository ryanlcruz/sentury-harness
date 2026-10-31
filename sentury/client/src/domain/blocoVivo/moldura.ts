/**
 * O bloco vivo: HTML ou SVG que o modelo escreve na resposta, desenhado num
 * iframe isolado. Sem `allow-same-origin`, a origem é opaca: o bloco não lê
 * cookie nem toca a página. A política do documento corta rede e recurso de
 * fora; o script roda, então slider, calculadora e abas funcionam. O kit leva
 * o visual e os ícones do Sentury para dentro.
 */
import kitCss from './kit.css?raw';
import { ICONES } from './icones';

const POLITICA = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:";

let sprite = '';

function atributos(attrs: Record<string, string>): string {
  return Object.entries(attrs)
    .filter(([nome]) => nome !== 'key')
    .map(([nome, valor]) => `${nome}="${String(valor).replace(/"/g, '&quot;')}"`)
    .join(' ');
}

/** Os ícones como `<symbol id="ic-nome">`, usados com `<svg class="ic"><use href="#ic-nome"/></svg>`. */
export function spriteDeIcones(): string {
  if (sprite) return sprite;
  const simbolos = ICONES.map(icone => (
    `<symbol id="ic-${icone.name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" `
    + 'stroke-linecap="round" stroke-linejoin="round">'
    + icone.node.map(([tag, attrs]) => `<${tag} ${atributos(attrs)}/>`).join('')
    + '</symbol>'
  ));
  sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">${simbolos.join('')}</svg>`;
  return sprite;
}

// Mede a altura para a página ajustar o quadro, e dá ao bloco um jeito de
// propor uma mensagem; a pessoa confirma antes de ela ir.
const PONTE = `<script>(function(){
  function medir(){parent.postMessage({sentury:'bloco-vivo',altura:Math.ceil(document.documentElement.getBoundingClientRect().height)},'*');}
  if(window.ResizeObserver){new ResizeObserver(medir).observe(document.documentElement);}
  addEventListener('load',medir);
  window.sentury={enviar:function(texto){parent.postMessage({sentury:'bloco-vivo',enviar:String(texto==null?'':texto).slice(0,2000)},'*');}};
})();</script>`;

export function documentoDoBloco(conteudo: string): string {
  return '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
    + `<meta http-equiv="Content-Security-Policy" content="${POLITICA}">`
    + `<style>${kitCss}</style>${PONTE}</head><body>${spriteDeIcones()}${conteudo}</body></html>`;
}

/** O quadro que roda o documento. Nasce aqui, fora da limpeza do HTML da
 * resposta: o documento leva `</style>`, e a limpeza apagaria o `srcdoc`. */
export function quadroDoBloco(documento: string, titulo: string): HTMLIFrameElement {
  const quadro = document.createElement('iframe');
  quadro.className = 'bloco-vivo__quadro';
  quadro.title = titulo;
  quadro.setAttribute('sandbox', 'allow-scripts');
  quadro.setAttribute('loading', 'lazy');
  quadro.srcdoc = documento;
  return quadro;
}
