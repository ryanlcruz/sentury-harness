import { useEffect, useSyncExternalStore } from 'react';
import { residentes, type Assunto, type Evento } from './api';

let retrato: { assuntos: Assunto[]; eventos: Evento[]; erro: string; naVez: Record<string, string[]> } = { assuntos: [], eventos: [], erro: '', naVez: {} };
// Quem está na vez de cada assunto: a tarefa da vez vai de "enfileirada" a "feita".
const naVez = new Map<string, Set<string>>();
const ABRE_A_VEZ = new Set(['enfileirada', 'comecou', 'liberada']);
const FECHA_A_VEZ = new Set(['feita', 'falhou', 'cancelada', 'esperando']);

function anotarVezes(eventos: Evento[]): boolean {
  let mudou = false;
  for (const e of [...eventos].sort((a, b) => a.em - b.em)) {
    if (!e.origem?.startsWith('mesa:') || !e.agente) continue;
    const assunto = e.origem.slice('mesa:'.length);
    const nomes = naVez.get(assunto) ?? new Set<string>();
    if (ABRE_A_VEZ.has(e.tipo) && !nomes.has(e.agente)) { nomes.add(e.agente); mudou = true; }
    if (FECHA_A_VEZ.has(e.tipo) && nomes.delete(e.agente)) mudou = true;
    naVez.set(assunto, nomes);
  }
  return mudou;
}
const ouvintes = new Set<() => void>();
let timer: number | undefined;
let ocupada = false;
let desde = 0;
let carregada = false;

function publicar() { ouvintes.forEach(ouvir => ouvir()); }

/** Busca já, sem esperar a próxima volta: logo depois de a pessoa falar. */
export function acompanharAgora(): void { void acompanhar(); }

export async function atualizarMesa(): Promise<void> {
  const assuntos = await residentes.assuntos();
  retrato = { ...retrato, assuntos: assuntos.sort((a, b) => Number(a.estado === 'fechado') - Number(b.estado === 'fechado') || b.atualizado_em - a.atualizado_em), erro: '' };
  carregada = true;
  publicar();
}

async function acompanhar() {
  if (ocupada) return;
  ocupada = true;
  try {
    const eventos = await residentes.eventos(desde, 200);
    const daMesa = eventos.filter(evento => evento.tipo.startsWith('mesa_'));
    if (anotarVezes(eventos)) {
      retrato = { ...retrato, naVez: Object.fromEntries([...naVez].map(([id, nomes]) => [id, [...nomes]])) };
    }
    // Uma fala da Mesa que entra na fila ou começa a ser escrita muda a vez mostrada embaixo da conversa.
    const vezMudou = eventos.some(evento => evento.origem?.startsWith('mesa:'));
    if (!carregada || daMesa.length || vezMudou || eventos.length === 200) await atualizarMesa();
    if (daMesa.length) {
      const unicos = new Map([...retrato.eventos, ...daMesa].map(e => [`${e.assunto}:${e.em}:${e.tipo}:${e.agente}`, e]));
      retrato = { ...retrato, eventos: [...unicos.values()].sort((a, b) => a.em - b.em).slice(-500), erro: '' };
    } else if (retrato.erro) retrato = { ...retrato, erro: '' };
    desde = Math.max(desde, ...eventos.map(evento => evento.em));
    publicar();
  } catch (e) {
    retrato = { ...retrato, erro: e instanceof Error ? e.message : 'Não consegui atualizar a Mesa.' };
    publicar();
  } finally { ocupada = false; }
}

function assinar(ouvir: () => void) {
  ouvintes.add(ouvir);
  return () => { ouvintes.delete(ouvir); };
}

let assinantes = 0;
export function useMesa() {
  useEffect(() => {
    assinantes += 1;
    if (assinantes === 1) {
      void acompanhar();
      timer = window.setInterval(() => void acompanhar(), 4000);
    }
    return () => {
      assinantes -= 1;
      if (!assinantes && timer !== undefined) window.clearInterval(timer);
    };
  }, []);
  return useSyncExternalStore(assinar, () => retrato);
}
