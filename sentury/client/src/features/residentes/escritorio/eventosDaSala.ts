import type { Assunto, Evento } from '../api';
import type { Escritorio } from './escritorio';

type Sala = Pick<Escritorio, 'pedidoChegou' | 'falar' | 'sentarNaMesa' | 'levantarDaMesa' | 'ativa' | 'reconciliarMesa'>;
type Fala = { fala: string; para?: string };

/** Leitura repetida do feed não repete a caminhada, a fala ou a contagem. */
export class EventosDaSala {
  desde = 0;
  private readonly vistos = new Set<string>();
  private readonly mesas = new Map<string, Set<string>>();

  receber(eventos: Evento[], animar: boolean, sala: Sala | null, ler: (e: Evento) => Fala): Evento[] {
    animar = animar && !!sala?.ativa();
    const novos: Evento[] = [];
    for (const e of [...eventos].sort((a, b) => a.em - b.em)) {
      this.desde = Math.max(this.desde, e.em);
      const chave = JSON.stringify([e.em, e.tipo, e.tarefa, e.agente, e.assunto, e.para, e.texto]);
      if (this.vistos.has(chave)) continue;
      this.vistos.add(chave); novos.push(e);
      if (this.vistos.size > 4096) this.vistos.delete(this.vistos.values().next().value!);
      const lido = ler(e);
      if (e.tipo.startsWith('mesa_')) {
        const nomes = this.mesas.get(e.assunto) ?? new Set<string>();
        if (e.tipo === 'mesa_fechada') {
          this.mesas.delete(e.assunto);
          const emOutra = new Set([...this.mesas.values()].flatMap(m => [...m]));
          if (animar) sala?.levantarDaMesa([...nomes].filter(n => !emOutra.has(n)));
        } else {
          this.mesas.set(e.assunto, nomes);
          const chegam = [...e.participantes, e.agente].filter(n => n && n !== 'pessoa' && !nomes.has(n));
          if (e.tipo !== 'mesa_passou') {
            chegam.forEach(n => nomes.add(n));
            if (animar && chegam.length) sala?.sentarNaMesa([...new Set(chegam)]);
          }
        }
        if (animar && lido.fala) sala?.falar(e.agente, lido.fala, lido.para);
      } else if (animar && !e.origem.startsWith('mesa:')) {
        if (e.tipo === 'enfileirada') {
          if (e.origem.startsWith('agente:')) {
            const nome = e.agente.charAt(0).toUpperCase() + e.agente.slice(1);
            sala?.falar(e.origem.slice('agente:'.length), `${nome}, pode ver isso?`, nome);
          }
          sala?.pedidoChegou(e.agente);
        } else if (lido.fala) sala?.falar(e.agente, lido.fala, lido.para);
      }
    }
    if (!animar) this.reconciliar(sala);
    return novos;
  }

  reconciliar(sala: Sala | null) {
    sala?.reconciliarMesa([...new Set([...this.mesas.values()].flatMap(m => [...m]))]);
  }

  restaurarMesas(assuntos: Pick<Assunto, 'id' | 'estado' | 'participantes'>[], sala: Sala | null) {
    this.mesas.clear();
    for (const a of assuntos) if (a.estado === 'aberto')
      this.mesas.set(a.id, new Set(a.participantes.filter(n => n && n !== 'pessoa')));
    this.reconciliar(sala);
  }
}
