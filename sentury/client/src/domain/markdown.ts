import { marked, type Tokens, type RendererObject } from 'marked';
import DOMPurify from 'dompurify';
import { documentoDoBloco, quadroDoBloco } from './blocoVivo/moldura';
import { htmlDoPainel } from './blocoVivo/painel';
import { ouvirBlocosVivos } from './blocoVivo/ponte';

// O `marked` cru não cobre os blocos específicos usados na conversa.

const CALLOUTS: Record<string, { label: string; cls: string }> = {
  insight: { label: 'Insight', cls: 'insight' },
  note: { label: 'Observação', cls: 'note' },
  observacao: { label: 'Observação', cls: 'note' },
  tip: { label: 'Dica', cls: 'tip' },
  dica: { label: 'Dica', cls: 'tip' },
  important: { label: 'Importante', cls: 'important' },
  importante: { label: 'Importante', cls: 'important' },
  warning: { label: 'Atenção', cls: 'warning' },
  atencao: { label: 'Atenção', cls: 'warning' },
  caution: { label: 'Cuidado', cls: 'danger' },
  cuidado: { label: 'Cuidado', cls: 'danger' },
  recomendacao: { label: 'Recomendação', cls: 'reco' },
};

const chaveCallout = (bruto: string): string =>
  (bruto || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

let tarefasVistas = 0;
// Caixa clicavel so onde alguem trata o clique (drawer do Tasks). No chat a
// lista mostra estado: caixa com cara de clicavel que nao faz nada engana.
let tarefasEditaveis = false;

const ICONE_FEITO = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.5"></circle><polyline points="5,8.2 7.2,10.3 11,6"></polyline></svg>';
// `[-]` e "em andamento": o agente marca quando comeca o item (o GFM so
// conhece `[ ]` e `[x]`, entao o marked entrega como item comum).
const ICONE_ANDAMENTO = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.5"></circle><path d="M8 1.5a6.5 6.5 0 0 1 0 13z" fill="currentColor" stroke="none"></path></svg>';
const EM_ANDAMENTO = /^\s*[-*+]\s+\[-\]\s/;

const ICONE_PENDENTE = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.5"></circle></svg>';

const TAGS_BLOCO = 'div|svg|table|figure|section|article';

// Conta profundidade: regex nao-guloso fecha no primeiro `</div>`, e o cartao
// de KPI tem div dentro de div.
function fimDoBloco(texto: string, inicio: number, tag: string): number {
  const abre = new RegExp('<' + tag + '\\b', 'gi');
  const fecha = new RegExp('</' + tag + '\\s*>', 'gi');
  let profundidade = 0;
  let i = inicio;
  for (;;) {
    if (i >= texto.length) return -1;
    abre.lastIndex = i;
    fecha.lastIndex = i;
    const a = abre.exec(texto);
    const f = fecha.exec(texto);
    if (!f) return -1;
    if (a && a.index < f.index) {
      profundidade += 1;
      i = a.index + a[0].length;
      continue;
    }
    profundidade -= 1;
    i = f.index + f[0].length;
    if (profundidade === 0) return i;
  }
}

function cercarTrecho(texto: string): string {
  const inicioDeBloco = new RegExp('^[ \\t]*<(' + TAGS_BLOCO + ')\\b', 'im');
  let saida = '';
  let resto = texto;
  for (;;) {
    const m = inicioDeBloco.exec(resto);
    if (!m) return saida + resto;
    const abertura = m.index + (m[0].length - m[0].trimStart().length);
    const fim = fimDoBloco(resto, abertura, m[1]);
    if (fim < 0) return saida + resto;
    const bloco = resto.slice(abertura, fim).trim();
    // HTML solto na prosa é o modelo querendo mostrar, não ensinar código.
    saida += resto.slice(0, abertura) + '\n```vivo\n' + bloco + '\n```\n';
    resto = resto.slice(fim);
  }
}

// HTML solto na prosa era escapado e aparecia como texto. Aqui vira cerca.
export function cercarHtmlSolto(md: string): string {
  const texto = String(md || '');
  if (!new RegExp('<(' + TAGS_BLOCO + ')\\b', 'i').test(texto)) return texto;
  // Só fora de cerca: dentro de ``` o HTML já é intencional e já funciona.
  return texto
    .split(/(^```[\s\S]*?^```)/m)
    .map((parte, i) => (i % 2 ? parte : cercarTrecho(parte)))
    .join('');
}

const escapar = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function criarRenderer(): RendererObject {
  return {
    // h1 vira h3: a resposta e um turno, nao uma pagina.
    heading(this: { parser: typeof marked.Parser.prototype }, token: Tokens.Heading) {
      const nivel = Math.min(token.depth + 2, 6);
      return '<h' + nivel + ' class="md-h">' + this.parser.parseInline(token.tokens) + '</h' + nivel + '>';
    },

    blockquote(this: { parser: typeof marked.Parser.prototype }, token: Tokens.Blockquote) {
      const corpo = this.parser.parse(token.tokens);
      const m = corpo.match(/^\s*<p>\s*\[!\s*([a-zA-ZÀ-ÿ]+)\s*\]\s*/);
      const meta = m ? CALLOUTS[chaveCallout(m[1])] : undefined;
      if (!meta || !m) return '<blockquote class="md-quote">' + corpo + '</blockquote>';
      const semMarca = corpo.replace(m[0], '<p>');
      return (
        '<div class="md-callout md-callout--' + meta.cls + '">' +
        '<div class="md-callout__label">' + meta.label + '</div>' +
        '<div class="md-callout__body">' + semMarca + '</div></div>'
      );
    },

    listitem(this: { parser: typeof marked.Parser.prototype }, item: Tokens.ListItem) {
      let conteudo = this.parser.parse(item.tokens, !!item.loose);
      const andamento = !item.task && EM_ANDAMENTO.test(item.raw || '');
      if (andamento) conteudo = conteudo.replace(/\[-\]\s*/, '');
      if (!item.task && !andamento) return '<li>' + conteudo + '</li>';
      if (andamento && !tarefasEditaveis) {
        return (
          '<li class="md-status is-doing"><span class="md-status__icone" aria-label="em andamento">' + ICONE_ANDAMENTO +
          '</span><span>' + conteudo + '</span></li>'
        );
      }
      if (andamento) {
        const indice = tarefasVistas;
        tarefasVistas += 1;
        return (
          '<li class="md-check is-doing"><span class="md-check__box" data-check="' + indice +
          '" role="checkbox" tabindex="0" aria-checked="mixed" title="Em andamento: clique para marcar como feito"></span>' +
          '<span>' + conteudo + '</span></li>'
        );
      }
      if (!tarefasEditaveis) {
        return (
          '<li class="md-status' + (item.checked ? ' is-done' : '') + '">' +
          '<span class="md-status__icone" aria-label="' + (item.checked ? 'feito' : 'pendente') + '">' +
          (item.checked ? ICONE_FEITO : ICONE_PENDENTE) + '</span>' +
          '<span>' + conteudo + '</span></li>'
        );
      }
      // O indice permite ao container alternar a caixinha na origem (o markdown).
      const indice = tarefasVistas;
      tarefasVistas += 1;
      return (
        '<li class="md-check' + (item.checked ? ' is-done' : '') + '">' +
        '<span class="md-check__box" data-check="' + indice + '" role="checkbox" tabindex="0" aria-checked="' + (item.checked ? 'true' : 'false') + '">' +
        (item.checked ? ICONE_FEITO : '') + '</span>' +
        '<span>' + conteudo + '</span></li>'
      );
    },

    list(this: { listitem: (i: Tokens.ListItem) => string }, token: Tokens.List) {
      const temTarefa = token.items.some(i => i.task || EM_ANDAMENTO.test(i.raw || ''));
      const corpo = token.items.map(i => this.listitem(i)).join('');
      if (token.ordered) return '<ol class="md-list">' + corpo + '</ol>';
      return '<ul class="md-list' + (temTarefa ? ' md-checklist' : '') + '">' + corpo + '</ul>';
    },

    code(token: Tokens.Code) {
      const idioma = (token.lang || '').toLowerCase().trim();
      const texto = token.text;

      // Renderizado depois da montagem, para nao carregar a lib sem diagrama.
      // O modelo abre a cerca com o tipo do diagrama (```flowchart TD) em vez
      // de ```mermaid, e o diagrama saia como bloco de codigo. O primeiro
      // termo do proprio conteudo ja diz que e mermaid.
      const TIPOS_MERMAID = /^(flowchart|graph|sequencediagram|classdiagram|statediagram|erdiagram|journey|gantt|pie|mindmap|timeline|quadrantchart)\b/i;
      const ehMermaid = idioma === 'mermaid'
        || TIPOS_MERMAID.test(idioma)
        || (!idioma && TIPOS_MERMAID.test(texto.trimStart()));
      if (ehMermaid) {
        // O codigo fica junto, fechado: quem quiser levar o diagrama para
        // outro lugar copia daqui, sem precisar pedir de novo.
        return (
          '<div class="mermaid-container">'
          + '<pre class="mermaid">' + escapar(texto) + '</pre>'
          + '<details class="mermaid-fonte"><summary>código do diagrama</summary>'
          + '<pre><code>' + escapar(texto) + '</code></pre></details>'
          + '</div>'
        );
      }
      if (idioma === 'vivo' || idioma === 'painel') {
        // `vivo` e `painel` são cercas só do Sentury: o modelo as usa quando
        // quer desenhar. Rodam no bloco vivo, isolado da página (domain/blocoVivo).
        const conteudo = idioma === 'painel' ? htmlDoPainel(texto) : texto;
        const indice = blocosVistos.push(documentoDoBloco(conteudo)) - 1;
        return '<div class="bloco-vivo" data-bloco="' + indice + '"></div>';
      }
      const rotulo = idioma || 'texto';
      // `html` e `svg` são código que a pessoa pode ter pedido para ler; ver
      // desenhado é escolha dela, no mesmo bloco isolado.
      const visualizar = idioma === 'html' || idioma === 'svg'
        ? '<button type="button" class="md-code__copy" data-visualizar>Visualizar</button>' : '';
      return (
        '<div class="md-code"><div class="md-code__bar"><span>' + escapar(rotulo) + '</span>' +
        '<span class="md-code__acoes">' + visualizar +
        '<button type="button" class="md-code__copy" data-copy>Copiar</button></span></div>' +
        '<pre><code>' + escapar(texto) + '</code></pre></div>'
      );
    },
  } as RendererObject;
}

let configurado = false;
let blocosVistos: string[] = [];

function montarBlocos(raiz: DocumentFragment): void {
  raiz.querySelectorAll<HTMLElement>('.bloco-vivo[data-bloco]').forEach(lugar => {
    const documento = blocosVistos[Number(lugar.dataset.bloco)];
    lugar.removeAttribute('data-bloco');
    if (documento != null) lugar.appendChild(quadroDoBloco(documento, 'Bloco da resposta'));
  });
}

function configurar(): void {
  if (configurado) return;
  marked.use({ renderer: criarRenderer(), gfm: true, breaks: true });
  ouvirBlocosVivos();
  configurado = true;
}

function marcarSeveridade(raiz: DocumentFragment): void {
  raiz.querySelectorAll('td').forEach(cell => {
    const valor = cell.textContent?.trim() || '';
    if (/^-\s*\d|cr[ií]tic|falhou|risco alto/i.test(valor)) cell.classList.add('sev-bad');
    else if (/^\+\s*\d|saud[aá]vel|conclu[ií]do|validado/i.test(valor)) cell.classList.add('sev-good');
  });
}

/** Cada tabela ganha o botão de levar para o painel. Entra depois da limpeza,
 * então o atributo não precisa ser liberado para o HTML do modelo. */
function barraDasTabelas(raiz: DocumentFragment): void {
  raiz.querySelectorAll('table').forEach(tabela => {
    const caixa = document.createElement('div');
    caixa.className = 'md-tabela';
    tabela.replaceWith(caixa);
    caixa.appendChild(tabela);
    const barra = document.createElement('div');
    barra.className = 'md-tabela__barra';
    barra.innerHTML = '<button type="button" class="md-tabela__painel" data-tabela-painel>Abrir no painel</button>';
    caixa.appendChild(barra);
  });
}

/** Itens de checklist no markdown: quantos, quantos feitos e quantos em
 * andamento (`[-]`, que conta no total e nao como feito). */
export function contarTarefas(md: string): { total: number; feitas: number; andamento: number } {
  const itens = (md || '').match(/^\s*[-*+] \[[ xX-]\]/gm) || [];
  return {
    total: itens.length,
    feitas: itens.filter(i => /\[[xX]\]/.test(i)).length,
    andamento: itens.filter(i => /\[-\]/.test(i)).length,
  };
}

/** O proximo estado da caixa quando a pessoa clica: pendente e em andamento
 * viram feito; feito volta a pendente. So o agente poe `[-]`. */
export function proximaMarca(atual: string): ' ' | 'x' {
  return /[xX]/.test(atual) ? ' ' : 'x';
}

export function renderMarkdown(md: string, opcoes: { tarefasEditaveis?: boolean } = {}): string {
  configurar();
  tarefasVistas = 0;
  blocosVistos = [];
  tarefasEditaveis = Boolean(opcoes.tarefasEditaveis);
  const bruto = marked.parse(cercarHtmlSolto(md || ''), { async: false }) as string;
  const limpo = DOMPurify.sanitize(bruto, {
    // Os ícones das tarefas. Sem `style` livre e sem iframe: o HTML do modelo
    // mora no bloco vivo, que entra depois da limpeza, e aqui ele poderia
    // cobrir a página.
    ADD_TAGS: ['svg', 'path', 'rect', 'circle', 'line', 'polyline', 'polygon', 'g', 'text'],
    ADD_ATTR: ['viewBox', 'fill', 'stroke', 'stroke-width', 'x', 'y', 'rx', 'ry', 'cx', 'cy', 'd', 'points', 'width', 'height', 'data-copy', 'data-visualizar'],
  });
  const template = document.createElement('template');
  template.innerHTML = limpo;
  marcarSeveridade(template.content);
  montarBlocos(template.content);
  barraDasTabelas(template.content);
  return template.innerHTML;
}
