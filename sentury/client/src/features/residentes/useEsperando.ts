import { useEffect, useSyncExternalStore } from 'react';
import { residentes, type Agente, type Tarefa } from './api';
import type { CoresCoruja } from './Coruja';

/** Um retrato só da HQ para a interface inteira: sidebar, conversa e composer
 * leem daqui, e uma busca a cada 15 s serve todos. */

interface RetratoDaHQ {
  agentes: Agente[];
  esperando: Tarefa[];
}

let retrato: RetratoDaHQ = { agentes: [], esperando: [] };
const ouvintes = new Set<() => void>();
let assinantes = 0;
let intervalo: number | undefined;

async function atualizar(): Promise<void> {
  try {
    const [lista, pendentes] = await Promise.all([residentes.listar(), residentes.esperando()]);
    retrato = { agentes: lista.agentes, esperando: pendentes };
  } catch {
    // HQ fora do ar: a interface segue sem residentes, sem quebrar.
  }
  ouvintes.forEach(ouvir => ouvir());
}

export function atualizarHQ(): void {
  void atualizar();
}

function assinar(ouvir: () => void) {
  ouvintes.add(ouvir);
  return () => { ouvintes.delete(ouvir); };
}

export function useHQ(): RetratoDaHQ {
  useEffect(() => {
    assinantes += 1;
    if (assinantes === 1) {
      void atualizar();
      intervalo = window.setInterval(() => void atualizar(), 15000);
    }
    return () => {
      assinantes -= 1;
      if (assinantes === 0 && intervalo !== undefined) window.clearInterval(intervalo);
    };
  }, []);
  return useSyncExternalStore(assinar, () => retrato);
}

/** Quantas tarefas de residente esperam a pessoa. Para o selo do prédio. */
export function useEsperandoNaHQ(): number {
  return useHQ().esperando.length;
}

export const CORES_PADRAO: CoresCoruja = { penas: '#76767e', asas: '#55555c', barriga: '#b4b4bb' };

export function coresDoAgente(agente?: Agente): CoresCoruja {
  if (!agente?.cores.penas) return CORES_PADRAO;
  return {
    penas: agente.cores.penas,
    asas: agente.cores.asas || agente.cores.penas,
    barriga: agente.cores.barriga || agente.cores.penas,
    olho: agente.cores.olho,
  };
}
