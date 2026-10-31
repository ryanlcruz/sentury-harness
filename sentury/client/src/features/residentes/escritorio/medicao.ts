import type { MedicaoDaSala } from './escritorio';

export interface AmostraDaSala {
  fps: number;
  cpu: number;
  cpuMax: number;
  intervalo95: number;
  intervaloMax: number;
  atrasados: number;
  duracao: number;
  chamadas: number;
  triangulos: number;
}

/** Usa apenas tempo ativo; um atraso durante a execução nunca é descartado. */
export class MedidorDaSala {
  private intervalos: number[] = [];
  private atrasos = 0;
  private duracao = 0;
  private cpu = 0;
  private cpuMax = 0;

  reiniciar() {
    this.intervalos = [];
    this.atrasos = 0;
    this.duracao = 0;
    this.cpu = 0;
    this.cpuMax = 0;
  }

  receber(m: MedicaoDaSala): AmostraDaSala | null {
    this.intervalos.push(m.intervalo);
    // Atrasado é passar do ritmo pedido com folga de um quadro de tela; parada,
    // a sala pede menos quadros de propósito.
    if (m.intervalo > (m.esperado ?? 1000 / 30) + 17) this.atrasos += 1;
    this.duracao += m.intervalo;
    this.cpu += m.ms;
    this.cpuMax = Math.max(this.cpuMax, m.ms);
    if (this.duracao < 1000 - 0.001) return null;
    const ordenados = [...this.intervalos].sort((a, b) => a - b);
    const amostra = {
      fps: this.intervalos.length * 1000 / this.duracao,
      cpu: this.cpu / this.intervalos.length,
      cpuMax: this.cpuMax,
      intervalo95: ordenados[Math.ceil(ordenados.length * 0.95) - 1],
      intervaloMax: ordenados[ordenados.length - 1],
      atrasados: this.atrasos,
      duracao: this.duracao,
      chamadas: m.chamadas,
      triangulos: m.triangulos,
    };
    this.reiniciar();
    return amostra;
  }
}
