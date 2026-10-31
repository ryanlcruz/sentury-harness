import { MESA, MESINHA, RACK, type AssentoDaMesa } from './cenario';

export interface PontoDaSala { x: number; y: number }
type Retangulo = { x: number; y: number; w: number; d: number; entrada?: boolean };
export const FOLGA = 0.68;
const MOVEIS: Retangulo[] = [
  { x: 0.08, y: 2.05, w: 0.98, d: 2.45 },
  { x: 1.5, y: 0.1, w: 3.1, d: 1.08 },
  { x: 0.12, y: 6.3, w: 1.15, d: 3.22, entrada: true },
  MESINHA,
  { x: 10.86, y: 4.56, w: 1.03, d: 2.08 },
  { x: 0.25, y: 4.68, w: 0.62, d: 0.55 },
  { x: 4.66, y: 0.56, w: 0.44, d: 0.44 },
  RACK,
  { x: 5.2, y: 0, w: 3.1, d: 0.85 },
  { x: 9.3, y: 0, w: 2.25, d: 0.32 },
  { x: 10.95, y: 8.95, w: 0.7, d: 0.7 },
  { x: 6.25, y: 9.1, w: 0.7, d: 0.7 },
  { x: 3.4, y: 9.05, w: 0.4, d: 0.4 },
];
const dentro = (p: PontoDaSala, r: Retangulo) =>
  p.x > r.x && p.x < r.x + r.w && p.y > r.y && p.y < r.y + r.d;

function atravessa(a: PontoDaSala, b: PontoDaSala, r: Retangulo) {
  let inicio = 0, fim = 1;
  for (const [valor, delta, min, max] of [
    [a.x, b.x - a.x, r.x, r.x + r.w], [a.y, b.y - a.y, r.y, r.y + r.d],
  ]) {
    if (Math.abs(delta) < 1e-9) { if (valor < min || valor > max) return false; }
    else {
      const t1 = (min - valor) / delta, t2 = (max - valor) / delta;
      inicio = Math.max(inicio, Math.min(t1, t2)); fim = Math.min(fim, Math.max(t1, t2));
      if (inicio > fim) return false;
    }
  }
  return true;
}

function cruzaMesa(a: PontoDaSala, b: PontoDaSala) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((MESA.x - a.x) * dx + (MESA.y - a.y) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(a.x + dx * t - MESA.x, a.y + dy * t - MESA.y) < MESA.r + FOLGA - 1e-8;
}

/** Os cantos livres formam um caminho contínuo, sem atravessar os móveis. */
export function rota(a: PontoDaSala, b: PontoDaSala, assentos: readonly AssentoDaMesa[] = []): PontoDaSala[] {
  const cadeiras = assentos.map(p => ({ x: p.x - 0.36, y: p.y - 0.36, w: 0.72, d: 0.72, entrada: true }));
  const obstaculos = [...MOVEIS, ...cadeiras].map(r => ({ entrada: r.entrada, x: r.x - FOLGA, y: r.y - FOLGA,
    w: r.w + 2 * FOLGA, d: r.d + 2 * FOLGA }))
    // Assento e sofá têm entrada explícita; o destino pode ficar dentro deles.
    .filter(r => !r.entrada || (!dentro(a, r) && !dentro(b, r)));
  const livre = (p: PontoDaSala) => p.x >= 0.4 && p.x <= 11.6 && p.y >= 0.4 && p.y <= 9.6
    && !obstaculos.some(r => dentro(p, r));
  const passa = (de: PontoDaSala, ate: PontoDaSala) => !cruzaMesa(de, ate)
    && !obstaculos.some(r => atravessa(de, ate, r));
  if (passa(a, b)) return [b];
  const pontos = [a, b];
  // A entrada por trás do encosto mantém a passagem mesmo com a mesa cheia.
  for (const p of assentos) {
    const dx = p.x - MESA.x, dy = p.y - MESA.y, distancia = Math.hypot(dx, dy);
    for (const margem of [FOLGA + 0.5, FOLGA + 1.2]) {
      const entrada = { x: p.x + dx / distancia * margem, y: p.y + dy / distancia * margem };
      if (livre(entrada)) pontos.push(entrada);
    }
  }
  for (const r of obstaculos) {
    for (const x of [r.x - 0.02, r.x + r.w + 0.02]) {
      for (const y of [r.y - 0.02, r.y + r.d + 0.02]) { if (livre({ x, y })) pontos.push({ x, y }); }
    }
  }
  const raio = (MESA.r + FOLGA + 0.02) / Math.cos(Math.PI / 20);
  for (let i = 0; i < 20; i++) {
    const p = { x: MESA.x + Math.cos(i * Math.PI / 10) * raio,
      y: MESA.y + Math.sin(i * Math.PI / 10) * raio };
    if (livre(p)) pontos.push(p);
  }
  const custo = pontos.map(() => Infinity), anterior = pontos.map(() => -1), visitados = new Set<number>();
  custo[0] = 0;
  while (visitados.size < pontos.length) {
    let atual = -1;
    for (let i = 0; i < pontos.length; i++) {
      if (!visitados.has(i) && (atual < 0 || custo[i] < custo[atual])) atual = i;
    }
    if (atual < 0 || !Number.isFinite(custo[atual])) return [];
    if (atual === 1) {
      const caminho: PontoDaSala[] = [];
      for (let i = 1; i !== 0; i = anterior[i]) caminho.unshift(pontos[i]);
      return caminho;
    }
    visitados.add(atual);
    for (let i = 0; i < pontos.length; i++) {
      if (visitados.has(i) || !passa(pontos[atual], pontos[i])) continue;
      const d = custo[atual] + Math.hypot(pontos[i].x - pontos[atual].x, pontos[i].y - pontos[atual].y);
      if (d < custo[i]) { custo[i] = d; anterior[i] = atual; }
    }
  }
  return [];
}
