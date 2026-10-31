/** A geometria do Escritório: a sala em coordenadas (x, y, z) e a projeção
 * isométrica para o SVG. Uma unidade da sala vale `S` pixels. */

export const S = 40;
export const H = 4.2;
const C30 = 0.8660254;
const S30 = 0.5;

export type Ponto = [number, number, number?];

export const iso = (x: number, y: number, z = 0): [number, number] => [(x - y) * C30 * S, (x + y) * S30 * S - z * S];
export const p = (x: number, y: number, z = 0) => iso(x, y, z).map(n => n.toFixed(1)).join(',');
export const poli = (lista: Ponto[]) => lista.map(([x, y, z]) => p(x, y, z ?? 0)).join(' ');

/** Matriz que desenha no chão (plano z): u ao longo de +x, v ao longo de +y. */
export const mChao = (x: number, y: number, z: number) => {
  const [e, f] = iso(x, y, z);
  return `matrix(${C30 * S} ${S30 * S} ${-C30 * S} ${S30 * S} ${e} ${f})`;
};
/** Parede do fundo (plano y = c): u ao longo de +x, v para baixo a partir de ztopo. */
export const mFundo = (x: number, y: number, ztopo: number) => {
  const [e, f] = iso(x, y, ztopo);
  return `matrix(${C30 * S} ${S30 * S} 0 ${S} ${e} ${f})`;
};
/** Parede da esquerda (plano x = c): u ao longo de -y, para a direita na tela. */
export const mEsq = (x: number, y: number, ztopo: number) => {
  const [e, f] = iso(x, y, ztopo);
  return `matrix(${C30 * S} ${-S30 * S} 0 ${S} ${e} ${f})`;
};

const hex = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const paraHex = (rgb: number[]) => '#' + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
export const clarear = (h: string, t: number) => paraHex(hex(h).map(v => v + (255 - v) * t));
export const escurecer = (h: string, t: number) => paraHex(hex(h).map(v => v * (1 - t)));

export interface OpcoesCaixa { topo?: string; fy?: string; fx?: string; borda?: string }

/** Um bloco com as três faces que a câmera vê. */
export function caixa(x: number, y: number, z: number, w: number, d: number, h: number, cor: string, op: OpcoesCaixa = {}) {
  const topo = op.topo || clarear(cor, 0.12), fy = op.fy || cor, fx = op.fx || escurecer(cor, 0.22);
  const borda = op.borda || 'rgba(0,0,0,.18)';
  return `
    <polygon points="${poli([[x, y + d, z], [x + w, y + d, z], [x + w, y + d, z + h], [x, y + d, z + h]])}" fill="${fy}" stroke="${borda}" stroke-width=".6"/>
    <polygon points="${poli([[x + w, y, z], [x + w, y + d, z], [x + w, y + d, z + h], [x + w, y, z + h]])}" fill="${fx}" stroke="${borda}" stroke-width=".6"/>
    <polygon points="${poli([[x, y, z + h], [x + w, y, z + h], [x + w, y + d, z + h], [x, y + d, z + h]])}" fill="${topo}" stroke="${borda}" stroke-width=".6"/>`;
}

export const sombraChao = (x: number, y: number, rx: number, ry: number, op = 0.28, z = 0) =>
  `<g transform="${mChao(x, y, z)}"><ellipse cx="0" cy="0" rx="${rx}" ry="${ry}" fill="#000" opacity="${op}" filter="url(#esc-borra)"/></g>`;

/** Texto vindo de fora (nome, pedido) vira texto, nunca marcação. */
export const esc = (t: string) => t.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string));
