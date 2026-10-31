/** O Escritório desenhado: a sala, os móveis e as plantas, em SVG isométrico.
 * Tudo aqui é cenário; o que muda com a HQ (quadro do dia, rack, farol,
 * envelopes) tem `id` com o prefixo `esc-` para o motor achar. */
import { H, S, caixa, escurecer, esc, iso, mChao, mEsq, mFundo, poli, sombraChao } from './iso';

export const MESA = { x: 6.3, y: 5.25, r: 1.3 };
export const RACK = { x: 8.44, y: 0, w: 0.72, d: 0.62, h: 1.85 };
export const MESINHA = { x: 2.75, y: 7.7, w: 0.9, d: 1.15, h: 0.36 };
export interface AssentoDaMesa { nome: string; x: number; y: number; angulo: number }
/** Pontos fixos evitam deslocar quem já está sentado quando chega um colega. */
export const ASSENTOS: AssentoDaMesa[] = [
  ['lugarO', 4], ['lugarN', 7], ['lugarL', 0], ['lugarS', 2],
  ['lugar1', 1], ['lugar2', 3], ['lugar3', 5], ['lugar4', 6], ['lugar5', 8],
].map(([nome, indice]) => {
  const radial = Number(indice) * Math.PI * 2 / 9;
  return { nome: String(nome), x: MESA.x + Math.cos(radial) * 2.1,
    y: MESA.y + Math.sin(radial) * 2.1, angulo: radial + Math.PI / 2 };
});
export const PARTES_DA_CADEIRA = [
  [-0.25, -0.25, 0.3, 0.5, 0.5, 0.12],
  [-0.06, -0.06, 0, 0.12, 0.12, 0.3],
  [-0.25, -0.3, 0.42, 0.5, 0.07, 0.5],
] as const;

export const TAMPOS = {
  parede: [0.08, 2.05, 0.7, 0.98, 2.45, 0.08],
  pesquisa: [1.5, 0.1, 0.7, 3.1, 1.08, 0.08],
  copa: [10.86, 4.56, 0.85, 1.03, 2.08, 0.07],
} as const;

// A janela segue a hora de quem abre a tela: dia, fim de tarde ou noite.
const CEU = (() => {
  const h = new Date().getHours();
  if (h >= 19 || h < 6) return { cores: ['#0b1430', '#1c2a55', '#3a3f6e'], astro: '#f4f1d9', luz: 0.035, noite: true };
  if (h >= 8 && h < 16) return { cores: ['#5ea4f2', '#9fd0ff', '#e2f2ff'], astro: '#fff3b0', luz: 0.13, noite: false };
  return { cores: ['#3a4f86', '#b9789a', '#f2a66e'], astro: '#ffe2a6', luz: 0.09, noite: false };
})();

export function defsDaCena() {
  return `
    <filter id="esc-borra" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation=".18"/></filter>
    <filter id="esc-brilhoSuave" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4"/></filter>
    <linearGradient id="esc-gChao" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#9a6a42"/><stop offset=".6" stop-color="#83563a"/><stop offset="1" stop-color="#6e4630"/>
    </linearGradient>
    <linearGradient id="esc-gParedeEsq" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4a372c"/><stop offset="1" stop-color="#3a2a22"/>
    </linearGradient>
    <linearGradient id="esc-gParedeFundo" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#55402f"/><stop offset="1" stop-color="#443226"/>
    </linearGradient>
    <linearGradient id="esc-gCeu" x1="0" y1="0" x2="0" y2="1">
      ${CEU.cores.map((c, i) => `<stop offset="${[0, 0.55, 1][i]}" stop-color="${c}"/>`).join('')}
    </linearGradient>
    <radialGradient id="esc-gLuzQuente" cx="50%" cy="50%" r="50%">
      <stop offset="0" stop-color="#ffcf7a" stop-opacity=".55"/><stop offset="1" stop-color="#ffcf7a" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="esc-gLuzFria" cx="50%" cy="50%" r="50%">
      <stop offset="0" stop-color="#6aa8ff" stop-opacity=".35"/><stop offset="1" stop-color="#6aa8ff" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="esc-gLuzVioleta" cx="50%" cy="50%" r="50%">
      <stop offset="0" stop-color="#a68bff" stop-opacity=".32"/><stop offset="1" stop-color="#a68bff" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="esc-gTela" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#16243f"/><stop offset="1" stop-color="#0d1628"/>
    </linearGradient>
    <linearGradient id="esc-gMadeira" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#b98457"/><stop offset="1" stop-color="#9c6b45"/>
    </linearGradient>
    <radialGradient id="esc-gTampo" cx="40%" cy="35%" r="70%">
      <stop offset="0" stop-color="#c79565"/><stop offset="1" stop-color="#94623f"/>
    </radialGradient>
    <linearGradient id="esc-gFolha" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#6fbf6a"/><stop offset="1" stop-color="#2f6e3a"/>
    </linearGradient>
    <linearGradient id="esc-gFolhaClara" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#9ad67f"/><stop offset="1" stop-color="#3f8a45"/>
    </linearGradient>
    <linearGradient id="esc-gFolhaEscura" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4c9450"/><stop offset="1" stop-color="#1e4a29"/>
    </linearGradient>
    <linearGradient id="esc-gEspada" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#3f7d45"/><stop offset=".5" stop-color="#5a9c55"/><stop offset="1" stop-color="#2c5e34"/>
    </linearGradient>
    <linearGradient id="esc-gEspadaEscura" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#2a5a32"/><stop offset="1" stop-color="#1b3f24"/>
    </linearGradient>
    ${Object.entries(VASOS).map(([nome, [claro, meio, escuro]]) => `<linearGradient id="esc-gVaso-${nome}" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="${claro}"/><stop offset=".45" stop-color="${meio}"/><stop offset="1" stop-color="${escuro}"/></linearGradient>`).join('')}
    <linearGradient id="esc-gCelulaA" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4fb6ff"/><stop offset="1" stop-color="#2a5fd6"/></linearGradient>
    <linearGradient id="esc-gCelulaB" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#b89bff"/><stop offset="1" stop-color="#6a4bd1"/></linearGradient>
    <linearGradient id="esc-gCelulaC" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5ff0d6"/><stop offset="1" stop-color="#1f9f9a"/></linearGradient>`;
}

export function cenarioEstatico() {
  let s = '';
  // Laje do piso, vista de frente
  s += `<polygon points="${poli([[12, 0, 0], [12, 10, 0], [12, 10, -0.45], [12, 0, -0.45]])}" fill="#3b271b"/>`;
  s += `<polygon points="${poli([[0, 10, 0], [12, 10, 0], [12, 10, -0.45], [0, 10, -0.45]])}" fill="#4a3122"/>`;
  // Piso com tábuas
  s += `<polygon points="${poli([[0, 0, 0], [12, 0, 0], [12, 10, 0], [0, 10, 0]])}" fill="url(#esc-gChao)"/>`;
  let tabuas = '';
  for (let y = 0.55; y < 10; y += 0.55) {
    tabuas += `<line x1="0" y1="${y.toFixed(2)}" x2="12" y2="${y.toFixed(2)}" stroke="#000" stroke-opacity=".13" stroke-width=".018"/>`;
    const desloc = (y * 7.3) % 2.4;
    for (let x = desloc; x < 12; x += 2.4) {
      tabuas += `<line x1="${x.toFixed(2)}" y1="${(y - 0.55).toFixed(2)}" x2="${x.toFixed(2)}" y2="${y.toFixed(2)}" stroke="#000" stroke-opacity=".1" stroke-width=".015"/>`;
    }
  }
  s += `<g transform="${mChao(0, 0, 0)}">${tabuas}</g>`;
  // Paredes
  s += `<polygon points="${poli([[0, 0, 0], [0, 10, 0], [0, 10, H], [0, 0, H]])}" fill="url(#esc-gParedeEsq)"/>`;
  s += `<polygon points="${poli([[0, 0, 0], [12, 0, 0], [12, 0, H], [0, 0, H]])}" fill="url(#esc-gParedeFundo)"/>`;
  // ripas verticais nas paredes
  let ripasE = '', ripasF = '';
  for (let u = 0.6; u < 10; u += 0.6) ripasE += `<line x1="${u.toFixed(2)}" y1="0" x2="${u.toFixed(2)}" y2="${H}" stroke="#000" stroke-opacity=".12" stroke-width=".02"/>`;
  for (let u = 0.6; u < 12; u += 0.6) ripasF += `<line x1="${u.toFixed(2)}" y1="0" x2="${u.toFixed(2)}" y2="${H}" stroke="#000" stroke-opacity=".1" stroke-width=".02"/>`;
  s += `<g transform="${mEsq(0, 10, H)}">${ripasE}<rect x="0" y="${H - 0.5}" width="10" height=".08" fill="#000" opacity=".2"/></g>`;
  s += `<g transform="${mFundo(0, 0, H)}">${ripasF}<rect x="0" y="${H - 0.5}" width="12" height=".08" fill="#000" opacity=".2"/></g>`;
  // Topo das paredes (espessura)
  s += `<polygon points="${poli([[-0.25, -0.25, H], [12, -0.25, H], [12, 0, H], [0, 0, H], [0, 10, H], [-0.25, 10, H]])}" fill="#6a4f3b"/>`;
  s += `<polygon points="${poli([[12, -0.25, 0], [12, 0, 0], [12, 0, H], [12, -0.25, H]])}" fill="#3a2a20"/>`;
  s += `<polygon points="${poli([[-0.25, 10, 0], [0, 10, 0], [0, 10, H], [-0.25, 10, H]])}" fill="#4a3528"/>`;

  // Janela na parede da esquerda
  s += `<g transform="${mEsq(0, 8.4, 3.35)}">
    <rect x="-.08" y="-.08" width="2.86" height="2.26" rx=".06" fill="#2c1f17"/>
    <clipPath id="esc-vidro"><rect width="2.7" height="2.1"/></clipPath>
    <g clip-path="url(#esc-vidro)">
    <rect x="0" y="0" width="2.7" height="2.1" fill="url(#esc-gCeu)"/>
    <circle cx="2.05" cy="${CEU.noite ? 0.45 : 1.35}" r=".22" fill="${CEU.astro}" opacity=".9"/>
    ${CEU.noite ? [[0.3, 0.25], [0.75, 0.55], [1.05, 0.2], [0.5, 0.8], [1.7, 0.7], [2.45, 0.3], [1.55, 0.35]].map(([x, y]) =>
      `<circle cx="${x}" cy="${y}" r=".025" fill="#fff" opacity=".8"/>`).join('') : ''}
    <ellipse cx=".5" cy="2.05" rx=".8" ry=".45" fill="#2f5b3a"/>
    <ellipse cx="1.6" cy="2.1" rx=".9" ry=".38" fill="#3b6e44"/>
    <ellipse cx="2.5" cy="2.0" rx=".6" ry=".42" fill="#2a5233"/>
    </g>
    <rect x="1.31" y="0" width=".08" height="2.1" fill="#2c1f17"/>
    <rect x="0" y="1.0" width="2.7" height=".07" fill="#2c1f17"/>
    <rect x="-.12" y="2.12" width="2.94" height=".12" fill="#5a4030"/>
  </g>`;
  // Luz da janela no chão
  s += `<polygon points="${poli([[0, 5.75, 0], [0, 8.4, 0], [2.8, 9.7, 0], [2.8, 7.05, 0]])}" fill="${CEU.noite ? '#9fb6ff' : '#ffcf8a'}" opacity="${CEU.luz}"/>`;

  // Relógio de parede, com a hora de verdade
  s += `<g transform="${mEsq(0, 5.52, 3.48)}">
    <circle cx=".38" cy=".38" r=".36" fill="#f4efe4" stroke="#2b2017" stroke-width=".05"/>
    ${Array.from({ length: 12 }, (_, i) => {
      const a = i * Math.PI / 6, r1 = i % 3 ? 0.29 : 0.25;
      return `<line x1="${(0.38 + Math.sin(a) * r1).toFixed(3)}" y1="${(0.38 - Math.cos(a) * r1).toFixed(3)}" x2="${(0.38 + Math.sin(a) * 0.32).toFixed(3)}" y2="${(0.38 - Math.cos(a) * 0.32).toFixed(3)}" stroke="#3b4256" stroke-width="${i % 3 ? 0.012 : 0.025}"/>`;
    }).join('')}
    <line id="esc-ponteiro-h" x1=".38" y1=".38" x2=".38" y2=".2" stroke="#2a3a56" stroke-width=".045" stroke-linecap="round"/>
    <line id="esc-ponteiro-m" x1=".38" y1=".38" x2=".38" y2=".1" stroke="#2a3a56" stroke-width=".028" stroke-linecap="round"/>
    <circle cx=".38" cy=".38" r=".03" fill="#c0563f"/></g>`;
  // Placa da caixa de pedidos
  s += `<g transform="${mEsq(0, 5.36, 1.62)}"><rect x="0" y="0" width=".78" height=".24" rx=".05" fill="#1a1f2b"/><text x=".39" y=".165" text-anchor="middle" font-size=".13" font-weight="600" fill="#ffe08a" font-family="Geist, sans-serif" letter-spacing=".03">PEDIDOS</text></g>`;

  // Poças de luz
  s += `<g transform="${mChao(1.6, 3.3, 0)}" style="mix-blend-mode:screen"><circle r="1.9" fill="url(#esc-gLuzFria)"/></g>`;
  s += `<g transform="${mChao(3, 1.6, 0)}" style="mix-blend-mode:screen"><circle r="2" fill="url(#esc-gLuzFria)"/></g>`;
  s += `<g transform="${mChao(6.8, 1.3, 0)}" style="mix-blend-mode:screen"><circle r="2.3" fill="url(#esc-gLuzVioleta)"/></g>`;
  s += `<g transform="${mChao(10.4, 1.4, 0)}" style="mix-blend-mode:screen"><circle r="2" fill="url(#esc-gLuzFria)"/></g>`;
  s += `<g transform="${mChao(MESA.x, MESA.y, 0)}" style="mix-blend-mode:screen"><circle r="3.2" fill="url(#esc-gLuzQuente)"/></g>`;
  s += `<g transform="${mChao(3.7, 8.9, 0)}" style="mix-blend-mode:screen"><circle r="2.2" fill="url(#esc-gLuzQuente)"/></g>`;

  // Tapete da mesa
  s += `<g transform="${mChao(MESA.x, MESA.y, 0)}">
    <circle r="2.75" fill="#6b4637" opacity=".95"/>
    <circle r="2.55" fill="none" stroke="#c9a37a" stroke-width=".05" stroke-dasharray=".12 .1" opacity=".7"/>
    <circle r="2.1" fill="none" stroke="#8a5c48" stroke-width=".22" opacity=".8"/>
    <circle r="1.2" fill="#7a5040" opacity=".6"/>
  </g>`;
  // Tapete do canto da pesquisa
  s += `<polygon points="${poli([[1.6, 1.4, 0], [4.6, 1.4, 0], [4.6, 3.0, 0], [1.6, 3.0, 0]])}" fill="#7b3b3b" opacity=".75"/>`;
  s += `<polygon points="${poli([[1.75, 1.55, 0], [4.45, 1.55, 0], [4.45, 2.85, 0], [1.75, 2.85, 0]])}" fill="none" stroke="#d9a074" stroke-width="1" opacity=".55"/>`;

  // ---- Quadro do dia: o que a HQ fez hoje, atualizado pelo motor ----
  s += `<g transform="${mEsq(0, 4.55, 3.55)}">
    <rect x="0" y="0" width="2.6" height="1.6" rx=".05" fill="#2b2017"/>
    <rect x=".06" y=".06" width="2.48" height="1.48" rx=".03" fill="#f4efe4"/>
    <text x=".18" y=".34" font-size=".2" font-weight="700" fill="#2a3a56" font-family="Geist, sans-serif" letter-spacing=".02">Hoje na HQ</text>
    ${([['feitas', 'Feitas', '#2fa36b'], ['fila', 'Na fila', '#5a8ad0'], ['esperando', 'Esperando você', '#c99700']] as const).map(([id, rotulo, cor], i) => `
      <circle cx=".29" cy="${0.61 + i * 0.32}" r=".07" fill="${cor}"/>
      <text x=".48" y="${0.66 + i * 0.32}" font-size=".15" fill="#3b4256" font-family="Geist, sans-serif">${rotulo}</text>
      <text id="esc-quadro-${id}" x="1.78" y="${0.66 + i * 0.32}" text-anchor="end" font-size=".17" font-weight="700" fill="#2a3a56" font-family="Geist Mono, monospace">0</text>`).join('')}
    <rect x="1.92" y=".44" width=".42" height=".34" fill="#ffe08a" transform="rotate(4 2.1 .6)"/>
    <rect x="1.98" y=".9" width=".38" height=".32" fill="#f7a9c8" transform="rotate(-5 2.1 1.05)"/>
  </g>`;
  // mesa de trabalho da parede da esquerda
  s += sombraChao(0.6, 3.25, 0.7, 1.35, 0.32);
  s += caixa(0.12, 2.15, 0, 0.82, 0.55, 0.7, '#6b4a33');
  s += caixa(0.12, 3.85, 0, 0.82, 0.55, 0.7, '#6b4a33');
  s += caixa(...TAMPOS.parede, '#a8764d', { topo: '#c08a5b' });
  // monitor virado para a sala
  s += caixa(0.32, 2.62, 0.78, 0.1, 1.3, 0.06, '#2a2f3a');
  s += caixa(0.36, 3.2, 0.84, 0.06, 0.12, 0.2, '#2a2f3a');
  s += caixa(0.3, 2.62, 1.04, 0.08, 1.3, 0.78, '#1d222c');
  s += `<g transform="${mEsq(0.385, 3.88, 1.78)}">
    <rect x=".04" y=".04" width="1.18" height=".66" fill="url(#esc-gTela)"/>
    <g stroke="#7fc0ff" stroke-width=".018" fill="none" opacity=".95">
      <rect x=".14" y=".12" width=".26" height=".14" rx=".02"/><rect x=".52" y=".12" width=".26" height=".14" rx=".02"/>
      <rect x=".9" y=".12" width=".22" height=".14" rx=".02"/><rect x=".33" y=".42" width=".26" height=".14" rx=".02"/>
      <rect x=".72" y=".42" width=".26" height=".14" rx=".02"/>
      <path d="M.4 .19 h.12 M.78 .19 h.12 M.46 .26 v.16 M.85 .26 v.16"/>
    </g>
  </g>`;
  // notebook e caneca
  s += caixa(0.35, 4.05, 0.78, 0.5, 0.38, 0.03, '#3a3f4b', { topo: '#555b6a' });
  s += `<g transform="${mChao(0.6, 2.4, 0.78)}"><circle r=".09" fill="#fffdf6"/><circle r=".06" fill="#6b3e1f"/></g>`;
  s += `<g transform="${mEsq(0, 4.2, 3.95)}"><rect x="0" y="0" width=".9" height=".26" rx=".05" fill="#1a1f2b"/><text x=".45" y=".18" text-anchor="middle" font-size=".15" font-weight="600" fill="#bcd9ff" font-family="Geist, sans-serif" letter-spacing=".03">PLANO</text></g>`;

  // ---- Pesquisa: estante e mesa comprida na parede do fundo ----
  s += sombraChao(0.75, 0.4, 0.7, 0.4, 0.3);
  s += caixa(0.15, 0, 0, 1.15, 0.55, 2.7, '#5a3f2c', { topo: '#7a5740' });
  s += `<g transform="${mFundo(0.15, 0.55, 2.7)}">
    ${[0.15, 0.85, 1.55, 2.25].map((y, i) => `<rect x=".05" y="${y + 0.55}" width="1.05" height=".06" fill="#3a2a1e"/>` +
      Array.from({ length: 6 }, (_, k) => {
        const cores = ['#c0563f', '#3f6fb5', '#e0b34a', '#4f8a5a', '#8b5fb8', '#d0d3dc'];
        const alt = 0.36 + ((k * 7 + i * 3) % 5) * 0.03;
        return `<rect x="${(0.1 + k * 0.155).toFixed(3)}" y="${(y + 0.55 - alt).toFixed(3)}" width=".12" height="${alt.toFixed(3)}" fill="${cores[(k + i) % 6]}" opacity=".9"/>`;
      }).join('')).join('')}
  </g>`;
  s += sombraChao(3.05, 0.75, 1.7, 0.6, 0.3);
  s += caixa(1.55, 0.15, 0, 0.6, 0.95, 0.7, '#6b4a33');
  s += caixa(3.95, 0.15, 0, 0.6, 0.95, 0.7, '#6b4a33');
  s += caixa(...TAMPOS.pesquisa, '#a8764d', { topo: '#c08a5b' });
  // dois monitores virados para a frente
  const monitor = (x0: number, conteudo: string) => {
    let m = caixa(x0 + 0.45, 0.35, 0.78, 0.18, 0.12, 0.22, '#2a2f3a');
    m += caixa(x0, 0.34, 1.0, 1.1, 0.07, 0.72, '#1d222c');
    m += `<g transform="${mFundo(x0, 0.415, 1.72)}"><clipPath id="esc-clip-${x0}"><rect x=".04" y=".04" width="1.02" height=".62"/></clipPath>
      <rect x=".04" y=".04" width="1.02" height=".62" fill="url(#esc-gTela)"/>
      <g clip-path="url(#esc-clip-${x0})">${conteudo}</g></g>`;
    return m;
  };
  const linhasDeCodigo = Array.from({ length: 16 }, (_, i) => {
    const w = 0.22 + ((i * 37) % 9) * 0.07, recuo = ((i * 13) % 4) * 0.06;
    const cor = ['#7fc0ff', '#c58cff', '#8fe0bb', '#ffd27f'][i % 4];
    return `<rect x="${(0.1 + recuo).toFixed(2)}" y="${(0.1 + i * 0.1).toFixed(2)}" width="${w.toFixed(2)}" height=".035" rx=".015" fill="${cor}" opacity=".8"/>`;
  }).join('');
  s += monitor(1.75, `<g class="esc-linhas-codigo" id="esc-codigo-nox">${linhasDeCodigo}</g>`);
  const mapa = Array.from({ length: 34 }, (_, i) => {
    const x = 0.12 + ((i * 53) % 29) * 0.03, y = 0.14 + ((i * 31) % 13) * 0.025;
    return `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r=".012" fill="#6aa8ff" opacity=".85"/>`;
  }).join('') + [0.18, 0.3, 0.22, 0.38, 0.27, 0.44].map((h, i) =>
    `<rect x="${(0.62 + i * 0.07).toFixed(2)}" y="${(0.6 - h).toFixed(2)}" width=".045" height="${h}" fill="#5ab0ff" opacity=".85"/>`).join('');
  s += monitor(3.0, mapa);
  s += `<g transform="${mFundo(2.2, 0, 3.75)}"><rect x="0" y="0" width="1.5" height=".3" rx=".05" fill="#1a1f2b"/><text x=".75" y=".205" text-anchor="middle" font-size=".16" font-weight="600" fill="#d4c9ff" font-family="Geist, sans-serif" letter-spacing=".03">PESQUISA</text></g>`;
  s += `<g transform="${mChao(4.25, 0.5, 0.78)}"><rect x="-.2" y="-.15" width=".4" height=".3" fill="#f4efe4" transform="rotate(12)"/><circle cx=".3" cy=".1" r=".08" fill="#fffdf6"/></g>`;

  // ---- Memória: armário com blocos que respiram ----
  s += sombraChao(6.75, 0.5, 1.8, 0.5, 0.32);
  s += caixa(5.2, 0, 0, 3.1, 0.85, 3.05, '#2b2638', { topo: '#3d3650', fx: '#1f1b29' });
  const celulas: string[] = [];
  for (let lin = 0; lin < 3; lin++) {
    for (let col = 0; col < 3; col++) {
      const g = ['gCelulaA', 'gCelulaB', 'gCelulaC'][(lin + col * 2) % 3];
      const x = 0.22 + col * 0.95, y = 0.22 + lin * 0.95, i = lin * 3 + col;
      const glifo = [
        `<path d="M${x + 0.22} ${y + 0.2} h.32 v.42 h-.32 Z M${x + 0.29} ${y + 0.3} h.18 M${x + 0.29} ${y + 0.38} h.18 M${x + 0.29} ${y + 0.46} h.12"/>`,
        `<path d="M${x + 0.18} ${y + 0.58} l.16 -.18 l.12 .1 l.14 -.16 l.08 .24 Z"/><circle cx="${x + 0.56}" cy="${y + 0.24}" r=".05"/>`,
        `<path d="M${x + 0.17} ${y + 0.24} h.46 v.34 h-.46 Z M${x + 0.17} ${y + 0.24} l.23 .18 l.23 -.18"/>`,
      ][i % 3];
      celulas.push(`<g class="esc-celula" id="esc-celula-${i}" style="animation-delay:${(i * 0.45).toFixed(2)}s">
        <rect x="${x}" y="${y}" width=".8" height=".8" rx=".1" fill="url(#esc-${g})"/>
        <rect x="${x}" y="${y}" width=".8" height=".24" rx=".1" fill="#fff" opacity=".18"/>
        <g fill="none" stroke="#fff" stroke-width=".035" opacity=".8">${glifo}</g></g>`);
    }
  }
  s += `<g transform="${mFundo(5.2, 0.85, 3.05)}">
    <rect x=".1" y=".1" width="2.9" height="2.85" rx=".08" fill="#120f1c"/>
    <rect x=".1" y=".1" width="2.9" height="2.85" rx=".08" fill="none" stroke="#a68bff" stroke-width=".03" opacity=".6"/>
    ${celulas.join('')}
  </g>`;
  s += `<g transform="${mFundo(5.95, 0, 3.75)}"><rect x="0" y="0" width="1.6" height=".3" rx=".05" fill="#1a1f2b"/><text x=".8" y=".205" text-anchor="middle" font-size=".16" font-weight="600" fill="#d4c9ff" font-family="Geist, sans-serif" letter-spacing=".03">MEMÓRIA</text></g>`;

  // ---- Ferramentas: o portal para web, arquivos e terminal ----
  s += sombraChao(10.4, 0.4, 1.3, 0.35, 0.3);
  s += caixa(9.3, 0, 0, 2.25, 0.32, 3.15, '#273246', { topo: '#36435c', fx: '#1b2333' });
  s += `<g transform="${mFundo(9.3, 0.32, 3.15)}">
    <rect x=".1" y=".1" width="2.05" height="2.95" rx=".1" fill="#0d1626"/>
    <rect x=".1" y=".1" width="2.05" height="2.95" rx=".1" fill="none" stroke="#5ab0ff" stroke-width=".035" opacity=".7"/>
    <g id="esc-portal-rede" class="esc-rede">
      <circle cx="1.32" cy="1.35" r=".62" fill="none" stroke="#5ab0ff" stroke-width=".025" opacity=".8"/>
      <ellipse cx="1.32" cy="1.35" rx=".62" ry=".24" fill="none" stroke="#5ab0ff" stroke-width=".02" opacity=".6"/>
      <ellipse cx="1.32" cy="1.35" rx=".24" ry=".62" fill="none" stroke="#5ab0ff" stroke-width=".02" opacity=".6"/>
      ${[[1.0, 1.0], [1.7, 1.15], [1.55, 1.75], [0.95, 1.6], [1.32, 0.78], [1.88, 1.5]].map(([x, y]) =>
        `<circle cx="${x}" cy="${y}" r=".045" fill="#9fd3ff"/>`).join('')}
      <path d="M1 1 L1.7 1.15 L1.55 1.75 L.95 1.6 Z M1.32 .78 L1.7 1.15 M1.88 1.5 L1.55 1.75" stroke="#9fd3ff" stroke-width=".015" fill="none" opacity=".7"/>
    </g>
    ${([['web', 0.6], ['arquivos', 1.15], ['terminal', 1.7]] as const).map(([nome, y]) => `
      <rect x=".24" y="${y}" width=".42" height=".42" rx=".08" fill="#16243f" stroke="#5ab0ff" stroke-width=".02"/>
      <g fill="none" stroke="#bfe1ff" stroke-width=".03">${{
        web: `<circle cx=".45" cy="${y + 0.21}" r=".12"/><path d="M.33 ${y + 0.21} h.24 M.45 ${y + 0.09} q.07 .12 0 .24 q-.07 -.12 0 -.24"/>`,
        arquivos: `<path d="M.35 ${y + 0.12} h.14 l.06 .06 v.16 h-.2 Z"/>`,
        terminal: `<path d="M.34 ${y + 0.14} l.07 .07 l-.07 .07 M.45 ${y + 0.3} h.12"/>`,
      }[nome]}</g>`).join('')}
    <rect x=".24" y="2.45" width="1.78" height=".4" rx=".06" fill="#16243f"/>
    <text x="1.13" y="2.71" text-anchor="middle" font-size=".15" fill="#9fd3ff" font-family="Geist Mono, monospace" id="esc-portal-texto">pronto</text>
  </g>`;
  {
    // Farol: acende quando alguém espera a sua autorização
    const [fx, fy] = iso(9.55, 0.16, 3.15);
    s += `<circle id="esc-farol-brilho" cx="${fx}" cy="${fy - 8}" r="15" fill="#f5c400" filter="url(#esc-brilhoSuave)"/>
      <rect x="${fx - 6}" y="${fy - 3}" width="12" height="4" rx="1.5" fill="#2a2f3a"/>
      <path id="esc-farol" d="M${fx - 5} ${fy - 3} v-6 a5 5 0 0 1 10 0 v6 Z"/>
      <path d="M${fx - 2.5} ${fy - 9} a2.5 2.5 0 0 1 3 -2" stroke="#fff" stroke-width="1" fill="none" opacity=".5"/>`;
  }
  s += `<g transform="${mFundo(9.7, 0, 3.75)}"><rect x="0" y="0" width="1.45" height=".3" rx=".05" fill="#1a1f2b"/><text x=".725" y=".205" text-anchor="middle" font-size=".16" font-weight="600" fill="#bfe1ff" font-family="Geist, sans-serif" letter-spacing=".03">FERRAMENTAS</text></g>`;

  // ---- Canto do sofá ----
  s += sombraChao(0.75, 7.9, 0.75, 1.6, 0.3);
  s += caixa(0.12, 6.45, 0, 1.15, 2.9, 0.38, '#3f5a3b', { topo: '#557a4f' });
  s += caixa(0.12, 6.45, 0.38, 0.32, 2.9, 0.62, '#3a5236', { topo: '#4f7049' });
  s += caixa(0.12, 6.3, 0, 1.15, 0.22, 0.62, '#36502f', { topo: '#4b6b45' });
  s += caixa(0.12, 9.3, 0, 1.15, 0.22, 0.62, '#36502f', { topo: '#4b6b45' });
  s += caixa(0.48, 6.6, 0.38, 0.7, 1.3, 0.1, '#5f8857', { topo: '#6f9a66' });
  s += caixa(0.48, 7.98, 0.38, 0.7, 1.28, 0.1, '#5f8857', { topo: '#6f9a66' });
  s += caixa(0.46, 8.45, 0.48, 0.18, 0.55, 0.42, '#d9a441', { topo: '#e9b85a' });
  return s;
}

// ---------- objetos do chão, ordenados por profundidade ----------
// ---------- plantas: cada vaso tem uma espécie ----------
const VASOS: Record<CorDeVaso, [string, string, string]> = {
  creme: ['#f6efe2', '#e2d7c3', '#bfb29b'],
  terra: ['#e4936a', '#c46a43', '#94492b'],
  grafite: ['#555c6c', '#3a3f4c', '#22262e'],
};
type CorDeVaso = 'creme' | 'terra' | 'grafite';
type Especie = 'costela' | 'espada' | 'figueira' | 'arbusto';

function vasoDe(sx: number, sy: number, k: number, cor: CorDeVaso) {
  const [claro, , escuro] = VASOS[cor], rt = 12 * k, rb = 9 * k, h = 20 * k;
  let s = `<path d="M${sx - rt} ${sy - h} L${sx + rt} ${sy - h} L${sx + rb} ${sy} Q${sx} ${sy + 3.5 * k} ${sx - rb} ${sy} Z" fill="url(#esc-gVaso-${cor})"/>`;
  if (cor === 'grafite') s += `<path d="M${sx - rt * 0.93} ${sy - h * 0.62} Q${sx} ${sy - h * 0.62 + 3.6 * k} ${sx + rt * 0.93} ${sy - h * 0.62}" stroke="#c9a54a" stroke-width="${1.4 * k}" fill="none"/>`;
  if (cor === 'terra') s += `<path d="M${sx - rt} ${sy - h + 3.4 * k} Q${sx} ${sy - h + 7.6 * k} ${sx + rt} ${sy - h + 3.4 * k}" stroke="${escuro}" stroke-width="${1.2 * k}" fill="none" opacity=".7"/>`;
  s += `<ellipse cx="${sx}" cy="${sy - h}" rx="${rt}" ry="${4 * k}" fill="${claro}"/>
    <ellipse cx="${sx}" cy="${sy - h + 0.5 * k}" rx="${rt - 2.2 * k}" ry="${2.7 * k}" fill="#3d2a1e"/>
    <path d="M${sx - rt * 0.62} ${sy - h * 0.82} L${sx - rb * 0.62} ${sy - 2 * k}" stroke="#fff" stroke-width="${1.6 * k}" opacity=".18" stroke-linecap="round"/>`;
  return s;
}
const r2 = (n: number) => n.toFixed(1);
// Costela-de-adão: folhas em coração, com nervuras, em hastes curvas.
function costela(ox: number, oy: number, k: number) {
  const folhas = [[-24, 30, 2], [30, 30, 2], [-64, 30, 0], [66, 28, 1], [-38, 42, 1], [40, 40, 0], [-12, 48, 0], [14, 46, 1]];
  return folhas.map(([a, haste, tom], i) => {
    const r = a * Math.PI / 180, L = haste * k;
    const ex = ox + Math.sin(r) * L, ey = oy - Math.cos(r) * L * 0.92;
    const cx = ox + Math.sin(r) * L * 0.25, cy = oy - L * 0.8;
    const g = ['gFolha', 'gFolhaClara', 'gFolhaEscura'][tom];
    return `<path d="M${r2(ox)} ${r2(oy)} Q${r2(cx)} ${r2(cy)} ${r2(ex)} ${r2(ey)}" stroke="#3f7a3c" stroke-width="${r2(1.6 * k)}" fill="none"/>
      <g transform="translate(${r2(ex)} ${r2(ey)}) rotate(${r2(a * 1.1)}) scale(${(k * (0.82 + (i % 3) * 0.1)).toFixed(2)})">
        <path d="M0 2 C9 2 15 -6 14 -14 C13 -22 6 -27 0 -28 C-6 -27 -13 -22 -14 -14 C-15 -6 -9 2 0 2 Z" fill="url(#esc-${g})"/>
        <path d="M0 1 L0 -26" stroke="#2c5a2c" stroke-width=".9" opacity=".55"/>
        <path d="M1 -7 L11 -11 M1 -13 L13 -18 M1 -19 L9 -24 M-1 -7 L-11 -11 M-1 -13 L-13 -18 M-1 -19 L-9 -24" stroke="#1f4a26" stroke-width="1.3" opacity=".5" stroke-linecap="round"/>
        <path d="M-3 -24 C-8 -21 -11 -16 -11 -11" stroke="#fff" stroke-width=".9" opacity=".25" fill="none"/>
      </g>`;
  }).join('');
}
// Espada-de-são-jorge: lâminas altas com borda amarelada e faixas claras.
function espada(ox: number, oy: number, k: number) {
  const laminas = [[-4, 44, 2, -5], [9, 52, 2, 4], [-22, 54, 0, -8], [-10, 68, 1, -3], [2, 78, 0, 0], [14, 64, 1, 4], [25, 50, 0, 8]];
  return laminas.map(([a, comp, tom, dx]) => {
    const L = comp * k, b = 4.3 * k;
    const faixas = [1, 2, 3, 4].map(j => `<path d="M${r2(-b * 0.75)} ${r2(-L * j / 5.6)} q${r2(b * 0.75)} ${r2(-2.6 * k)} ${r2(b * 1.5)} 0" stroke="#a9d39a" stroke-width="${r2(0.8 * k)}" fill="none" opacity=".35"/>`).join('');
    return `<g transform="translate(${r2(ox + dx * k)} ${r2(oy)}) rotate(${a})">
      <path d="M${r2(-b)} 0 C${r2(-b)} ${r2(-L * 0.55)} ${r2(-b * 0.4)} ${r2(-L * 0.86)} 0 ${r2(-L)} C${r2(b * 0.4)} ${r2(-L * 0.86)} ${r2(b)} ${r2(-L * 0.55)} ${r2(b)} 0 Z"
        fill="url(#esc-${tom === 2 ? 'gEspadaEscura' : 'gEspada'})" stroke="#d8d97c" stroke-width="${r2(0.9 * k)}" stroke-opacity="${tom === 1 ? 0.9 : 0.65}"/>
      ${faixas}
      <path d="M0 -2 L0 ${r2(-L * 0.9)}" stroke="#fff" stroke-width="${r2(0.6 * k)}" opacity=".15"/></g>`;
  }).join('');
}
// Figueira-lira: tronco fino e uma copa de folhas largas presas a ele, arredondadas na ponta.
function figueira(ox: number, oy: number, k: number) {
  const topo = 72;
  const xTronco = (t: number) => ox + (1 - t) * t * 2 * 3 * k - t * t * k;
  let s = `<path d="M${r2(ox)} ${r2(oy)} Q${r2(ox + 3 * k)} ${r2(oy - topo / 2 * k)} ${r2(ox - k)} ${r2(oy - topo * k)}" stroke="#6b4a33" stroke-width="${r2(2.8 * k)}" fill="none" stroke-linecap="round"/>`;
  const folhas = [[24, -82, 2, 0.8], [26, 80, 2, 0.8], [30, -64, 2, 0.88], [34, 62, 2, 0.88], [40, -48, 0, 0.95], [44, 50, 1, 0.95],
    [50, -88, 1, 0.82], [52, 86, 0, 0.82], [56, -32, 1, 1], [60, 34, 0, 1], [64, -14, 0, 1.02], [67, 16, 1, 1.02], [70, -2, 1, 0.98]];
  s += folhas.map(([altura, rot, tom, tam]) => {
    const t = altura / topo, g = ['gFolha', 'gFolhaClara', 'gFolhaEscura'][tom];
    return `<g transform="translate(${r2(xTronco(t))} ${r2(oy - altura * k)}) rotate(${rot}) scale(${(k * tam).toFixed(2)})">
      <path d="M0 0 C7 -3 12 -14 10 -22 C8 -29 3 -31 0 -31 C-3 -31 -8 -29 -10 -22 C-12 -14 -7 -3 0 0 Z" fill="url(#esc-${g})"/>
      <path d="M0 -1 L0 -29 M0 -9 L6 -13 M0 -16 L8 -20 M0 -9 L-6 -13 M0 -16 L-8 -20" stroke="#cfe8b0" stroke-width=".8" opacity=".4" fill="none"/>
      <path d="M-4 -27 C-8 -24 -9 -20 -9 -17" stroke="#fff" stroke-width=".9" opacity=".22" fill="none"/></g>`;
  }).join('');
  return s;
}
// Arbusto pequeno, para cima das mesas.
function arbusto(ox: number, oy: number, k: number) {
  const bolas = [[-9, -5, 8, 2], [9, -5, 8, 2], [0, -8, 9, 0], [-12, -14, 7, 1], [12, -14, 7, 0], [-5, -20, 8, 1], [6, -20, 8, 0], [0, -27, 7, 1]];
  return bolas.map(([dx, dy, r, tom]) => {
    const g = ['gFolha', 'gFolhaClara', 'gFolhaEscura'][tom], cx = ox + dx * k, cy = oy + dy * k;
    return `<circle cx="${r2(cx)}" cy="${r2(cy)}" r="${r2(r * k)}" fill="url(#esc-${g})"/>
      <circle cx="${r2(cx - r * k * 0.35)}" cy="${r2(cy - r * k * 0.4)}" r="${r2(r * k * 0.28)}" fill="#fff" opacity=".14"/>`;
  }).join('');
}
// z > 0 põe o vaso em cima de um móvel: o fundo dele fica no tampo, não no chão.
export function vaso(x: number, y: number, tamanho = 1, especie: Especie = 'arbusto', cor: CorDeVaso = 'creme', z = 0) {
  const [sx, sy] = iso(x, y, z), k = tamanho;
  const folhagem = { costela, espada, figueira, arbusto }[especie](sx, sy - 19 * k, k);
  return `<g>${sombraChao(x, y, 0.34 * k, 0.34 * k, 0.35, z)}${vasoDe(sx, sy, k, cor)}${folhagem}</g>`;
}

export function mesaRedonda() {
  const { x, y, r } = MESA;
  const [sx, sy] = iso(x, y, 0);
  let s = sombraChao(x, y, r * 0.9, r * 0.9, 0.35);
  s += `<rect x="${sx - 7}" y="${sy - 0.72 * S}" width="14" height="${0.72 * S}" fill="#5a3b28"/>`;
  s += `<g transform="${mChao(x, y, 0)}"><ellipse rx=".55" ry=".55" fill="#4a3122"/></g>`;
  s += `<g transform="${mChao(x, y, 0.68)}"><circle r="${r}" fill="#7a5034"/></g>`;
  s += `<g transform="${mChao(x, y, 0.76)}">
    <circle r="${r}" fill="url(#esc-gTampo)"/>
    <circle r="${r - 0.08}" fill="none" stroke="#000" stroke-opacity=".12" stroke-width=".03"/>
    <rect x="-.75" y="-.35" width=".42" height=".55" fill="#f4efe4" transform="rotate(-14 -.55 -.1)"/>
    <rect x=".35" y=".25" width=".42" height=".55" fill="#f4efe4" transform="rotate(20 .55 .5)"/>
    <rect x="-.2" y=".55" width=".36" height=".46" fill="#fff6dc" transform="rotate(6 0 .78)"/>
  </g>`;
  s += caixa(x - 0.75, y + 0.15, 0.76, 0.5, 0.36, 0.03, '#3a3f4b', { topo: '#4c5262' });
  s += `<g transform="${mFundo(x - 0.75, y + 0.15, 1.08)}"><rect x=".02" y="0" width=".46" height=".3" fill="#2a3d5c"/><rect x=".06" y=".05" width=".3" height=".03" fill="#7fc0ff"/></g>`;
  s += caixa(x - 0.75, y + 0.15, 0.79, 0.5, 0.04, 0.3, '#2c313b');
  s += vaso(x + 0.15, y - 0.25, 0.5, 'arbusto', 'terra', 0.76);
  const [cx, cy] = iso(x + 0.6, y - 0.55, 0.76);
  s += `<ellipse cx="${cx}" cy="${cy}" rx="5" ry="2.5" fill="#fffdf6"/><rect x="${cx - 4}" y="${cy - 7}" width="8" height="7" fill="#fffdf6"/><ellipse cx="${cx}" cy="${cy - 7}" rx="4" ry="2" fill="#6b3e1f"/>`;
  return s;
}

export function banquinho(x: number, y: number, encosto: 'o' | 'n' | 'l' | 's' | number) {
  const angulo = typeof encosto === 'number' ? encosto : { o: -Math.PI / 2, n: 0, l: Math.PI / 2, s: Math.PI }[encosto];
  const c = Math.cos(angulo), sen = Math.sin(angulo);
  let s = sombraChao(x, y, 0.32, 0.32, 0.3);
  PARTES_DA_CADEIRA.forEach(([u, v, z, w, d, h], parte) => {
    const base = [[u, v], [u + w, v], [u + w, v + d], [u, v + d]]
      .map(([a, b]): [number, number, number] => [x + a * c - b * sen, y + a * sen + b * c, z]);
    const topo = base.map(([a, b]): [number, number, number] => [a, b, z + h]);
    for (let i = 0; i < 4; i++) {
      const j = (i + 1) % 4, dx = base[j][0] - base[i][0], dy = base[j][1] - base[i][1];
      if (dy - dx <= 1e-8) continue;
      s += `<polygon points="${poli([base[i], base[j], topo[j], topo[i]])}" fill="${parte === 1 ? '#4a3122' : -dx >= dy ? '#7d5233' : '#614028'}" stroke="rgba(0,0,0,.18)" stroke-width=".6"/>`;
    }
    s += `<polygon points="${poli(topo)}" fill="${parte === 1 ? '#4a3122' : '#a06d45'}" stroke="rgba(0,0,0,.18)" stroke-width=".6"/>`;
  });
  return s;
}

export function luminaria(x: number, y: number) {
  const [sx, sy] = iso(x, y, 0);
  return `<g>${sombraChao(x, y, 0.3, 0.3, 0.3)}
    <ellipse cx="${sx}" cy="${sy}" rx="10" ry="4" fill="#2a2a2e"/>
    <rect x="${sx - 1.5}" y="${sy - 82}" width="3" height="82" fill="#2f2f35"/>
    <circle cx="${sx}" cy="${sy - 86}" r="26" fill="#ffcf7a" opacity=".25" filter="url(#esc-brilhoSuave)"/>
    <path d="M${sx - 13} ${sy - 80} L${sx + 13} ${sy - 80} L${sx + 8} ${sy - 98} L${sx - 8} ${sy - 98} Z" fill="#f3e3c3"/>
    <path d="M${sx} ${sy - 80} L${sx + 13} ${sy - 80} L${sx + 8} ${sy - 98} L${sx} ${sy - 98} Z" fill="#dcc8a2"/></g>`;
}

// Copa: balcão encostado na borda da sala, com cafeteira e canecas.
export function copa() {
  let s = sombraChao(11.37, 5.6, 0.6, 1.15, 0.3);
  s += caixa(10.9, 4.6, 0, 0.95, 2.0, 0.85, '#5a3f2c', { topo: '#8a6446' });
  s += `<g transform="${mFundo(10.9, 6.6, 0.85)}"><rect x=".08" y=".1" width=".79" height=".65" rx=".03" fill="none" stroke="#3a281c" stroke-width=".025"/><rect x=".42" y=".38" width=".1" height=".03" rx=".015" fill="#c9a37a"/></g>`;
  s += `<g transform="${mEsq(11.85, 6.6, 0.85)}">${[0, 0.66, 1.32].map(u => `<rect x="${u + 0.06}" y=".1" width=".56" height=".65" rx=".03" fill="none" stroke="#3a281c" stroke-width=".025"/><rect x="${u + 0.3}" y=".38" width=".08" height=".03" rx=".015" fill="#c9a37a"/>`).join('')}</g>`;
  s += caixa(...TAMPOS.copa, '#cfc6b8', { topo: '#ece5d8' });
  // cafeteira
  s += caixa(11.2, 4.72, 0.92, 0.5, 0.42, 0.6, '#2a2f3a', { topo: '#3a4050' });
  s += caixa(11.24, 4.76, 1.52, 0.42, 0.34, 0.08, '#1d222c', { topo: '#4a5163' });
  s += `<g transform="${mFundo(11.2, 5.14, 1.5)}"><rect x=".08" y=".06" width=".18" height=".1" rx=".02" fill="#5fd6c9" opacity=".8"/><circle cx=".38" cy=".11" r=".04" fill="#ff7a7a"/></g>`;
  const [xc, yc] = iso(11.42, 5.2, 0.92);
  s += `<rect x="${xc - 3.5}" y="${yc - 6}" width="7" height="6" fill="#fffdf6"/><ellipse cx="${xc}" cy="${yc - 6}" rx="3.5" ry="1.6" fill="#6b3e1f"/>`;
  const [vx, vy] = iso(11.42, 5.0, 1.62);
  s += `<g class="esc-vapor" id="esc-vapor">${[-4, 0, 4].map(d => `<path d="M${vx + d} ${vy} q3 -5 0 -10 q-3 -5 0 -10" stroke="#fff" stroke-width="1.6" fill="none" opacity=".7" stroke-linecap="round"/>`).join('')}</g>`;
  // canecas e garrafa
  ([[11.3, 5.75, '#5ab0ff'], [11.55, 5.95, '#f07ac8'], [11.1, 5.42, '#ff9a3c']] as const).forEach(([x, y, c]) => {
    const [cx, cy] = iso(x, y, 0.92);
    s += `<rect x="${cx - 4}" y="${cy - 8}" width="8" height="8" rx="1" fill="${c}"/><ellipse cx="${cx}" cy="${cy - 8}" rx="4" ry="1.8" fill="${escurecer(c, 0.45)}"/><path d="M${cx + 4} ${cy - 6} q3 1 0 4" stroke="${c}" stroke-width="1.5" fill="none"/>`;
  });
  const [gx, gy] = iso(11.55, 5.45, 0.92);
  s += `<rect x="${gx - 4}" y="${gy - 20}" width="8" height="20" rx="3" fill="#9fd3ff" opacity=".55"/><rect x="${gx - 2}" y="${gy - 24}" width="4" height="5" rx="1" fill="#5ab0ff"/>`;
  return s;
}

// Rack do Router: um pisca-pisca por residente acende quando ele usa o cérebro; a tela mostra o gasto do dia.
export interface LuzDoRack { nome: string; cor: string }

/** O rack do Router: a tela mostra o gasto e os turnos do dia; cada residente
 * tem uma luz, que pisca quando ele está usando o cérebro (até 8). */
export function rackDoRouter(luzes: LuzDoRack[]) {
  const { x, y, d, h } = RACK;
  const w = 0.88;
  let s = sombraChao(x + RACK.w / 2, y + d / 2, 0.75, 0.5, 0.32);
  s += caixa(x, y, 0, RACK.w, d, h, '#232a38', { topo: '#323b4e', fx: '#1a202c' });
  s += `<g transform="${mFundo(x, y + d, h)} scale(${RACK.w / w} 1)">
    <rect x=".08" y=".07" width="${w - 0.16}" height=".2" rx=".04" fill="#1a1f2b"/>
    <text x="${w / 2}" y=".215" text-anchor="middle" font-size=".11" font-weight="600" fill="#bfe1ff" font-family="Geist, sans-serif" letter-spacing=".03">ROUTER</text>
    <rect x=".08" y=".33" width="${w - 0.16}" height=".5" rx=".05" fill="#0d1626" stroke="#5ab0ff" stroke-width=".015" stroke-opacity=".5"/>
    <text x="${w / 2}" y=".57" text-anchor="middle" font-size=".17" font-weight="600" fill="#9fd3ff" font-family="Geist Mono, monospace" id="esc-uso-custo">US$ 0,00</text>
    <text x="${w / 2}" y=".74" text-anchor="middle" font-size=".1" fill="#8a93a8" font-family="Geist Mono, monospace" id="esc-uso-turnos">hoje</text>
    ${luzes.slice(0, 8).map((luz, i) => {
      const cx = i < 4 ? 0.1 : 0.48, cy = 0.96 + (i % 4) * 0.17;
      return `<g class="esc-led-linha" id="esc-led-${esc(luz.nome)}">
        <text x="${cx.toFixed(2)}" y="${(cy + 0.07).toFixed(2)}" font-size=".1" font-weight="700" fill="${luz.cor}" font-family="Geist, sans-serif">${esc(luz.nome[0].toUpperCase())}</text>
        ${[0, 1, 2].map(k => `<rect class="esc-led" x="${(cx + 0.1 + k * 0.08).toFixed(3)}" y="${cy.toFixed(2)}" width=".06" height=".06" rx=".015" fill="${luz.cor}" style="animation-delay:${(k * 0.11 + i * 0.05).toFixed(2)}s"/>`).join('')}</g>`;
    }).join('')}
    ${[1.66, 1.71].map(v => `<rect x=".12" y="${v}" width="${w - 0.24}" height=".025" rx=".01" fill="#0d1218"/>`).join('')}
  </g>`;
  return s;
}

// Caixa de pedidos: o que chega da pessoa (pelo painel ou pelo Telegram) cai aqui como envelope.
export function caixaDePedidos() {
  const x = 0.25, y = 4.68, w = 0.62, d = 0.55;
  let s = sombraChao(x + w / 2, y + d / 2, 0.42, 0.42, 0.3);
  s += caixa(x, y, 0, w, d, 0.6, '#6b4a33', { topo: '#8a6446' });
  s += caixa(x + 0.05, y + 0.05, 0.6, w - 0.1, d - 0.1, 0.1, '#2a3d5c', { topo: '#16233a' });
  const [bx, by] = iso(x + w / 2, y + d / 2, 0.75);
  s += `<circle id="esc-brilho-pedidos" cx="${bx}" cy="${by}" r="18" fill="#f5c400" opacity="0" filter="url(#esc-brilhoSuave)"/>`;
  s += [0, 1, 2].map(i => `<g id="esc-envelope-${i}" opacity="0" transform="${mChao(x + w / 2, y + d / 2, 0.71 + i * 0.03)}">
    <g transform="rotate(${i * 11 - 8})"><rect x="-.19" y="-.13" width=".38" height=".26" rx=".02" fill="#fffdf6" stroke="#c9bea9" stroke-width=".012"/>
    <path d="M-.19 -.13 L0 .02 L.19 -.13" stroke="#c9bea9" stroke-width=".015" fill="none"/></g></g>`).join('');
  return s;
}

// Lixeira ao lado da mesa do Nox: as fontes descartadas caem aqui.
export function lixeira() {
  const [sx, sy] = iso(4.88, 0.78, 0);
  return `<g>${sombraChao(4.88, 0.78, 0.22, 0.22, 0.3)}
    <path d="M${sx - 8} ${sy - 17} L${sx + 8} ${sy - 17} L${sx + 6.5} ${sy} L${sx - 6.5} ${sy} Z" fill="#3a4152"/>
    <path d="M${sx} ${sy - 17} L${sx + 8} ${sy - 17} L${sx + 6.5} ${sy} L${sx} ${sy} Z" fill="#2c3240"/>
    <ellipse cx="${sx}" cy="${sy - 17}" rx="8" ry="3.4" fill="#1c2230" stroke="#4f586c" stroke-width="1"/>
    <g id="esc-papeis">${[[-3, -18], [2, -19], [0, -21]].map(([dx, dy], i) => `<circle cx="${sx + dx}" cy="${sy + dy}" r="3" fill="#f4efe4" stroke="#c9bea9" stroke-width=".6" opacity="${i ? 0 : 1}"/>`).join('')}</g></g>`;
}

export function mesinhaDeCentro() {
  const { x, y, w, d, h } = MESINHA;
  let s = sombraChao(x + w / 2, y + d / 2, 0.6, 0.75, 0.3);
  s += caixa(x, y, 0, w, d, h, '#6b4a33', { topo: '#a8764d' });
  const [cx, cy] = iso(x + 0.4, y + 0.35, h);
  s += `<rect x="${cx - 4}" y="${cy - 8}" width="8" height="8" fill="#fffdf6"/><ellipse cx="${cx}" cy="${cy - 8}" rx="4" ry="2" fill="#6b3e1f"/>`;
  s += caixa(x + 0.15, y + 0.65, h, 0.5, 0.35, 0.08, '#3f6fb5', { topo: '#5a8ad0' });
  return s;
}
