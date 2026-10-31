/**
 * O painel: o modelo descreve o que mostrar (JSON num bloco ```painel) e o
 * Sentury monta com o kit, dentro do mesmo bloco vivo isolado. O modelo
 * escreve dado, não HTML: o visual sai sempre igual, e componente desconhecido
 * vira aviso em vez de quebrar a resposta. A cor é escolha do modelo (nome da
 * paleta ou hex); sem escolha, uso e risco ganham a cor da faixa. A lista de
 * componentes para o modelo mora na skill bloco-vivo; um teste confere que ela
 * e `TIPOS` batem.
 */
import appsJson from './apps.json?raw';

type Dado = Record<string, unknown>;

const esc = (valor: unknown): string => String(valor ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Dado que vai para dentro de um <script>: `</script>` no texto do modelo não fecha o script.
const js = (valor: unknown): string => JSON.stringify(valor).replace(/</g, '\\u003c');

const icone = (nome: string): string => `<svg class="ic"><use href="#ic-${esc(nome)}"/></svg>`;

const lista = (valor: unknown): Dado[] => (Array.isArray(valor) ? valor : [])
  .filter((item): item is Dado => Boolean(item) && typeof item === 'object');

const numero = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

// `%` e `°` colam no número; o resto (`GB`, `mil`) vem depois de um espaço.
const comUnidade = (u: unknown): string => (u ? (/^[%°]/.test(String(u)) ? String(u) : ` ${String(u)}`) : '');

const fmt = (v: number, casas?: number): string => v.toLocaleString('pt-BR', casas == null
  ? { maximumFractionDigits: 2 } : { minimumFractionDigits: casas, maximumFractionDigits: casas });

export const PALETA: Record<string, string> = {
  verde: '#16a34a', vermelho: '#dc2626', amarelo: '#eab308', laranja: '#ea580c', azul: '#2563eb',
  roxo: '#7c3aed', rosa: '#db2777', ciano: '#0891b2', cinza: '#78716c', ouro: '#f5c400', tinta: '#1c1b18',
};
// A ordem das fatias e séries quando o modelo não escolhe a cor.
const CICLO = ['ouro', 'azul', 'verde', 'roxo', 'laranja', 'ciano', 'rosa', 'cinza'];

/** Nome da paleta ou hex; qualquer outra coisa vira o padrão. */
function cor(valor: unknown, padrao = PALETA.ouro): string {
  if (typeof valor !== 'string') return padrao;
  const nome = valor.trim().toLowerCase();
  if (nome in PALETA) return PALETA[nome];
  return /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(nome) ? nome : padrao;
}

/** Uso e risco: verde até 75%, amarelo até 90%, vermelho acima. */
const corDaFaixa = (pct: number): string => (pct >= 90 ? PALETA.vermelho : pct >= 75 ? PALETA.amarelo : PALETA.verde);

const SENTIDO_ICONE: Record<string, string> = {
  bom: 'trending-up', ruim: 'trending-down', atencao: 'triangle-alert', neutro: 'minus', info: 'info',
};
const sentido = (valor: unknown): string => (typeof valor === 'string' && valor in SENTIDO_ICONE ? valor : 'neutro');

const titulo = (c: Dado): string => (c.titulo ? `<div class="rotulo">${esc(c.titulo)}</div>` : '');

const selo = (nome: unknown, tom: string): string => (nome
  ? `<span class="selo" style="color:${tom};background:${tom}1a">${icone(String(nome))}</span>` : '');

interface App { nome: string; icone: string; cor: string; apelidos?: string[] }

// Programa se reconhece pelo nome, sem acento, caixa nem espaço: "VS Code" e "vscode" são o mesmo.
const chaveDoApp = (nome: unknown): string => String(nome ?? '').normalize('NFKD')
  .replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
const APPS = new Map<string, App>();
for (const [chave, app] of Object.entries(JSON.parse(appsJson) as Record<string, App>)) {
  for (const nome of [chave, app.nome, ...(app.apelidos ?? [])]) APPS.set(chaveDoApp(nome), app);
}

const nomeDoApp = (nome: unknown): string => APPS.get(chaveDoApp(nome))?.nome ?? String(nome ?? '');

/** O selo de um programa: o da tabela, ou a inicial numa cor que sai do nome,
 * para o mesmo programa ter sempre a mesma cor. */
function seloDoApp(nome: unknown): string {
  const app = APPS.get(chaveDoApp(nome));
  if (app) return selo(app.icone, app.cor);
  const texto = String(nome ?? '').trim();
  const tons = Object.values(PALETA);
  let soma = 0;
  for (const letra of chaveDoApp(texto)) soma = (soma * 31 + letra.charCodeAt(0)) >>> 0;
  return `<span class="selo selo--letra" style="background:${tons[soma % tons.length]}">`
    + `${esc(texto.charAt(0).toUpperCase() || '?')}</span>`;
}

function numeros(c: Dado): string {
  const cartoes = lista(c.itens).map(item => {
    const s = sentido(item.sentido);
    const tom = item.cor ? cor(item.cor) : '';
    const variacao = item.variacao != null
      ? `<div class="sub ${s === 'neutro' ? '' : s}">${icone(SENTIDO_ICONE[s])} ${esc(item.variacao)}</div>` : '';
    return `<div class="cartao"${tom ? ` style="border-left:4px solid ${tom}"` : ''}>`
      + `<div class="linha" style="justify-content:space-between"><div class="rotulo">${esc(item.rotulo)}</div>`
      + `${selo(item.icone, tom || 'var(--tinta-2)')}</div>`
      + `<div class="numero"${tom ? ` style="color:${tom}"` : ''}>${esc(item.valor)}</div>`
      + `${variacao}${item.sub ? `<div class="sub">${esc(item.sub)}</div>` : ''}</div>`;
  });
  return `<div class="grade">${cartoes.join('')}</div>`;
}

function tabela(c: Dado): string {
  const colunas = Array.isArray(c.colunas) ? c.colunas : [];
  const linhas = Array.isArray(c.linhas) ? c.linhas.filter(Array.isArray) as unknown[][] : [];
  const celula = (v: unknown) => (typeof v === 'number'
    ? `<td style="text-align:right">${esc(fmt(v))}</td>` : `<td>${esc(v)}</td>`);
  return `${c.titulo ? `<h3>${esc(c.titulo)}</h3>` : ''}<table class="tabela"><thead><tr>`
    + colunas.map(col => `<th>${esc(col)}</th>`).join('') + '</tr></thead><tbody>'
    + linhas.map(l => `<tr>${l.map(celula).join('')}</tr>`).join('') + '</tbody></table>';
}

function barras(c: Dado): string {
  const itens = lista(c.itens).filter(item => numero(item.valor) != null);
  const maior = numero(c.maximo) ?? (Math.max(...itens.map(item => Math.abs(item.valor as number)), 0) || 1);
  const unidade = esc(comUnidade(c.unidade));
  return `<div class="cartao coluna">${titulo(c)}`
    + itens.map(item => {
      const valor = item.valor as number;
      const largura = Math.min(100, Math.round((Math.abs(valor) / maior) * 100));
      const texto = `${fmt(valor)}${comUnidade(c.unidade)}`;
      return `<div title="${esc(item.rotulo)}: ${esc(texto)}"><div class="linha" style="justify-content:space-between">`
        + `<span class="linha">${item.app ? seloDoApp(item.app) : item.icone ? icone(String(item.icone)) : ''}${esc(item.rotulo)}</span>`
        + `<span class="sub">${esc(fmt(valor))}${unidade}</span></div>`
        + `<div class="barra"><span style="width:${largura}%;background:${cor(item.cor, cor(c.cor))}"></span></div></div>`;
    }).join('') + '</div>';
}

function anel(pct: number, tom: string, centro: string, legenda: string): string {
  const raio = 46, volta = 2 * Math.PI * raio;
  const cheio = Math.max(0, Math.min(100, pct));
  return `<div class="anel"><svg viewBox="0 0 120 120" width="120" height="120">`
    + `<circle cx="60" cy="60" r="${raio}" fill="none" stroke="var(--painel)" stroke-width="12"/>`
    + `<circle class="anel__arco" cx="60" cy="60" r="${raio}" fill="none" stroke="${tom}" stroke-width="12" `
    + `stroke-linecap="round" stroke-dasharray="${(volta * cheio / 100).toFixed(1)} ${volta.toFixed(1)}" `
    + 'transform="rotate(-90 60 60)"/>'
    + `<text x="60" y="60" text-anchor="middle" dominant-baseline="central" class="anel__centro">${esc(centro)}</text></svg>`
    + `<div class="sub" style="text-align:center">${esc(legenda)}</div></div>`;
}

function medidor(c: Dado): string {
  const varios = lista(c.itens).length > 0;
  const itens = varios ? lista(c.itens) : [c];
  const aneis = itens.map(item => {
    const valor = numero(item.valor) ?? 0;
    const maximo = numero(item.maximo) ?? 100;
    const pct = maximo ? (valor / maximo) * 100 : 0;
    const tom = item.cor ? cor(item.cor) : corDaFaixa(pct);
    const centro = item.centro != null ? String(item.centro) : `${fmt(pct, 0)}%`;
    return `<div class="coluna" style="align-items:center"><div class="rotulo">${esc(item.rotulo)}</div>`
      + anel(pct, tom, centro, String(item.sub ?? ''))
      + '</div>';
  });
  return `<div class="cartao coluna">${varios ? titulo(c) : ''}<div class="grade">${aneis.join('')}</div></div>`;
}

function rosca(c: Dado): string {
  const itens = lista(c.itens).filter(item => (numero(item.valor) ?? 0) > 0);
  const total = itens.reduce((soma, item) => soma + (item.valor as number), 0) || 1;
  const raio = 46, volta = 2 * Math.PI * raio;
  let acumulado = 0;
  const fatias = itens.map((item, i) => {
    const parte = (item.valor as number) / total;
    const tom = cor(item.cor, PALETA[CICLO[i % CICLO.length]]);
    const arco = `<circle cx="60" cy="60" r="${raio}" fill="none" stroke="${tom}" stroke-width="18" `
      + `stroke-dasharray="${(volta * parte).toFixed(2)} ${volta.toFixed(2)}" stroke-dashoffset="${(-volta * acumulado).toFixed(2)}" `
      + `transform="rotate(-90 60 60)"><title>${esc(item.rotulo)}: ${esc(fmt(item.valor as number))}</title></circle>`;
    acumulado += parte;
    return { arco, tom, item, parte };
  });
  const centro = c.centro && typeof c.centro === 'object' ? c.centro as Dado : null;
  const unidade = esc(comUnidade(c.unidade));
  return `<div class="cartao coluna">${titulo(c)}<div class="linha" style="gap:20px;align-items:center">`
    + `<svg viewBox="0 0 120 120" width="150" height="150">${fatias.map(f => f.arco).join('')}`
    + (centro ? `<text x="60" y="56" text-anchor="middle" class="anel__centro anel__centro--rosca">${esc(centro.valor)}</text>`
      + `<text x="60" y="74" text-anchor="middle" class="anel__legenda">${esc(centro.rotulo)}</text>` : '')
    + '</svg><div class="coluna legenda">'
    + fatias.map(f => `<div class="linha"><span class="ponto" style="background:${f.tom}"></span>`
      + `<span style="flex:1">${esc(f.item.rotulo)}</span><span class="sub">${esc(fmt(f.item.valor as number))}${unidade}`
      + ` · ${esc(fmt(f.parte * 100, 0))}%</span></div>`).join('')
    + '</div></div></div>';
}

function linhaDoTempo(c: Dado): string {
  const series = lista(c.series)
    .map(s => ({ nome: s.nome, cor: s.cor, pontos: (Array.isArray(s.pontos) ? s.pontos : []).filter(p => numero(p) != null) as number[] }))
    .filter(s => s.pontos.length > 1);
  const rotulos = Array.isArray(c.rotulos) ? c.rotulos.map(String) : [];
  const todos = series.flatMap(s => s.pontos);
  if (!todos.length) return aviso({ sentido: 'atencao', texto: 'A série precisa de pelo menos dois pontos.' });
  const largura = 600, altura = 180, margem = 8;
  const menor = Math.min(...todos), maior = Math.max(...todos);
  const faixa = maior - menor || 1;
  const quantos = Math.max(...series.map(s => s.pontos.length));
  const x = (i: number) => margem + (i * (largura - 2 * margem)) / (quantos - 1);
  const y = (v: number) => altura - margem - ((v - menor) / faixa) * (altura - 2 * margem);
  const unidade = comUnidade(c.unidade);
  const desenhos = series.map((s, i) => {
    const tom = cor(s.cor, PALETA[CICLO[i % CICLO.length]]);
    const pts = s.pontos.map((v, j) => `${x(j).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const area = c.area === false ? '' : `<polygon points="${x(0).toFixed(1)},${altura - margem} ${pts} `
      + `${x(s.pontos.length - 1).toFixed(1)},${altura - margem}" fill="${tom}" opacity="0.12"/>`;
    const ultimo = s.pontos.length - 1;
    const marcas = s.pontos.map((v, j) => `<circle cx="${x(j).toFixed(1)}" cy="${y(v).toFixed(1)}" r="${j === ultimo ? 4 : 2.5}" `
      + `fill="${tom}"><title>${esc(rotulos[j] ?? '')} ${esc(fmt(v))}${esc(unidade)}</title></circle>`).join('');
    return `${area}<polyline points="${pts}" fill="none" stroke="${tom}" stroke-width="2.5" stroke-linejoin="round"/>${marcas}`;
  });
  const legenda = series.length > 1 ? `<div class="linha legenda">${series.map((s, i) => `<span class="linha">`
    + `<span class="ponto" style="background:${cor(s.cor, PALETA[CICLO[i % CICLO.length]])}"></span>${esc(s.nome)}</span>`).join('')}</div>` : '';
  const fim = series[0];
  return `<div class="cartao coluna">${titulo(c)}`
    + `<div class="linha" style="justify-content:space-between"><span class="numero" style="font-size:22px">`
    + `${esc(fmt(fim.pontos[fim.pontos.length - 1]))}${esc(unidade)}</span><span class="sub">${esc(rotulos[rotulos.length - 1] ?? '')}</span></div>`
    + `<svg viewBox="0 0 ${largura} ${altura}" preserveAspectRatio="none" style="width:100%;height:150px">${desenhos.join('')}</svg>`
    + `<div class="linha sub" style="justify-content:space-between"><span>${esc(rotulos[0] ?? '')}</span>`
    + `<span>${esc(rotulos[rotulos.length - 1] ?? '')}</span></div>${legenda}</div>`;
}

function progresso(c: Dado): string {
  return `<div class="cartao coluna">${titulo(c)}`
    + lista(c.itens).map(item => {
      const usado = numero(item.usado) ?? 0, total = numero(item.total) ?? 0;
      const pct = total ? (usado / total) * 100 : 0;
      const tom = item.cor ? cor(item.cor) : corDaFaixa(pct);
      const unidade = comUnidade(item.unidade);
      return `<div class="coluna" style="gap:4px"><div class="linha" style="justify-content:space-between">`
        + `<span class="linha">${item.app ? seloDoApp(item.app) : selo(item.icone, tom)}<b>${esc(item.rotulo ?? nomeDoApp(item.app))}</b></span>`
        + `<span class="sub">${esc(fmt(usado))} de ${esc(fmt(total))}${esc(unidade)} · <b style="color:${tom}">${esc(fmt(pct, 0))}%</b></span></div>`
        + `<div class="barra grossa"><span style="width:${Math.min(100, pct).toFixed(1)}%;background:${tom}"></span></div>`
        + `${item.sub ? `<div class="sub">${esc(item.sub)}</div>` : ''}</div>`;
    }).join('') + '</div>';
}

function itensComIcone(c: Dado): string {
  return `<div class="cartao coluna" style="gap:0">${titulo(c)}`
    + lista(c.itens).map(item => {
      const tom = cor(item.cor, 'var(--tinta-2)');
      return `<div class="linha item-lista">${item.app ? seloDoApp(item.app) : selo(item.icone || 'circle-dot', tom)}`
        + `<div class="coluna" style="gap:0;flex:1;min-width:0"><b>${esc(item.titulo ?? nomeDoApp(item.app))}</b>`
        + `${item.sub ? `<span class="sub">${esc(item.sub)}</span>` : ''}</div>`
        + `${item.valor != null ? `<span style="font-weight:600;color:${item.cor ? tom : 'inherit'}">${esc(typeof item.valor === 'number' ? fmt(item.valor) : item.valor)}</span>` : ''}</div>`;
    }).join('') + '</div>';
}

// Fórmula só com aritmética sobre `x`: o painel não executa código do modelo.
const FORMULA = /^[0-9x+\-*/().\s]+$/;

function simulador(c: Dado, indice: number): string {
  const controle = (c.controle && typeof c.controle === 'object' ? c.controle : {}) as Dado;
  const num = (v: unknown, padrao: number) => numero(v) ?? padrao;
  const min = num(controle.min, 0), max = num(controle.max, 100), passo = num(controle.passo, 1);
  const inicial = Math.min(max, Math.max(min, num(controle.inicial, min)));
  const resultados = lista(c.resultados).filter(r => typeof r.formula === 'string' && FORMULA.test(r.formula as string));
  const id = `s${indice}`;
  const saidas = resultados.map((r, i) => `<div class="cartao"${r.cor ? ` style="border-left:4px solid ${cor(r.cor)}"` : ''}>`
    + `<div class="rotulo">${esc(r.rotulo)}</div><div class="numero" id="${id}r${i}"></div></div>`).join('');
  const contas = resultados.map((r, i) => ({
    alvo: `${id}r${i}`, formato: String(r.formato || 'numero'), casas: num(r.casas, 1), unidade: String(r.unidade || ''),
  }));
  const enviar = typeof c.enviar === 'string' && c.enviar.trim()
    ? `<button class="botao" id="${id}e">${icone('message-square')} ${esc(c.rotulo_enviar || 'Pedir análise deste cenário')}</button>`
    : '';
  return `<div class="cartao coluna">${titulo(c)}`
    + `<div class="linha" style="justify-content:space-between"><span>${esc(controle.rotulo)}</span>`
    + `<b><span id="${id}v"></span>${esc(controle.unidade || '')}</b></div>`
    + `<input type="range" id="${id}" min="${min}" max="${max}" step="${passo}" value="${inicial}">`
    + `<div class="grade">${saidas}</div>${enviar}</div>`
    + `<script>(function(){var r=document.getElementById(${js(id)});var contas=${js(contas)};`
    + 'var fmt=function(v,c){var n=v.toLocaleString("pt-BR",{minimumFractionDigits:c.casas,maximumFractionDigits:c.casas});'
    + 'var u=c.unidade?" "+c.unidade:"";return c.formato==="moeda"?"R$ "+n+u:c.formato==="porcento"?n+"%":n+u;};'
    // A política do bloco corta `eval`; a fórmula, já conferida como aritmética
    // sobre `x`, vai escrita como função.
    + `var fs=[${resultados.map(r => `function(x){return (${String(r.formula)});}`).join(',')}];`
    + `function mostrar(){var x=Number(r.value);document.getElementById(${js(id + 'v')}).textContent=x;`
    + 'contas.forEach(function(c,i){var v=fs[i](x);document.getElementById(c.alvo).textContent=Number.isFinite(v)?fmt(v,c):"—";});}'
    + 'r.oninput=mostrar;mostrar();'
    + (enviar ? `document.getElementById(${js(id + 'e')}).onclick=function(){sentury.enviar(${js(c.enviar)}.replace("{x}",r.value));};` : '')
    + '})();</script>';
}

function aviso(c: Dado): string {
  const s = sentido(c.sentido === undefined ? 'info' : c.sentido);
  const tom = c.cor ? cor(c.cor) : '';
  return `<div class="cartao linha"${tom ? ` style="border-left:4px solid ${tom}"` : ''}>`
    + `<span class="${s === 'info' || s === 'neutro' ? '' : s}"${tom ? ` style="color:${tom}"` : ''}>${icone(String(c.icone || SENTIDO_ICONE[s]))}</span>`
    + `<span>${esc(c.texto)}</span></div>`;
}

function passos(c: Dado): string {
  return `<div class="cartao coluna">${titulo(c)}`
    + lista(c.itens).map(item => `<div class="linha"><span class="${item.feito ? 'bom' : 'sub'}">`
      + `${icone(item.feito ? 'circle-check' : 'circle-dot')}</span><span>${esc(item.texto)}</span></div>`).join('')
    + '</div>';
}

function texto(c: Dado): string {
  return `${c.titulo ? `<h3>${esc(c.titulo)}</h3>` : ''}<p>${esc(c.texto)}</p>`;
}

const MONTADORES: Record<string, (c: Dado, indice: number) => string> = {
  numeros, tabela, barras, medidor, rosca, linha: linhaDoTempo, progresso, lista: itensComIcone,
  simulador, aviso, passos, texto,
};

export const TIPOS = Object.keys(MONTADORES);

export function htmlDoPainel(fonte: string): string {
  let spec: unknown;
  try {
    spec = JSON.parse(fonte);
  } catch {
    return aviso({ sentido: 'atencao', texto: 'O painel não pôde ser montado: o JSON veio incompleto ou inválido.' });
  }
  const componentes = Array.isArray(spec) ? spec
    : spec && typeof spec === 'object' && Array.isArray((spec as Dado).componentes) ? (spec as Dado).componentes as unknown[]
      : [spec];
  const partes = componentes.map((c, i) => {
    const dado = (c && typeof c === 'object' ? c : {}) as Dado;
    const montar = MONTADORES[String(dado.tipo)];
    return montar ? montar(dado, i) : aviso({ sentido: 'atencao', texto: `Componente desconhecido: ${String(dado.tipo)}` });
  });
  return `<div class="coluna">${partes.join('')}</div>`;
}
