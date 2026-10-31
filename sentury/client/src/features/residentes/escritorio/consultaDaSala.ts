import type { Agente, Assunto, Evento, Tarefa } from '../api';

export interface EstadoDaSala { agentes: Agente[]; esperando: Tarefa[]; assuntos: Assunto[] }

/** Retomadas pedem um retrato atual; buscas antigas não sobrescrevem esse retrato. */
export class ConsultaDaSala {
  private viva = true;
  private buscando = false;
  private revisao = 0;
  private lida = -1;

  constructor(private readonly fonte: {
    eventos(): Promise<Evento[]>;
    estado(): Promise<EstadoDaSala>;
  }, private readonly destino: {
    eventos(eventos: Evento[], animar: boolean): void;
    estado(estado: EstadoDaSala): void;
    reconciliar(): void;
    erro(mensagem: string): void;
  }) {}

  async buscar() {
    if (!this.viva || this.buscando) return;
    this.buscando = true;
    const revisao = this.revisao;
    const restaurar = this.lida !== revisao;
    try {
      const [eventos, estado] = await Promise.all([
        this.fonte.eventos(), restaurar ? this.fonte.estado() : Promise.resolve(null),
      ]);
      if (!this.viva || revisao !== this.revisao) return;
      this.destino.eventos(eventos, !restaurar);
      if (estado) this.destino.estado(estado);
      this.lida = revisao;
      this.destino.erro('');
    } catch (e) {
      if (this.viva && revisao === this.revisao)
        this.destino.erro(e instanceof Error ? e.message : 'a HQ não respondeu');
    } finally {
      this.buscando = false;
      if (this.viva && revisao !== this.revisao) void this.buscar();
    }
  }

  retomar() {
    if (!this.viva) return;
    this.revisao += 1;
    this.destino.reconciliar();
    void this.buscar();
  }

  parar() { this.viva = false; }
}
