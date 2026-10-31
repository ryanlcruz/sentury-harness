/* O cartão do navegador, montado a partir dos eventos `navegador` do stream.
   É o mesmo cálculo de `sentury/harness/cartao_do_navegador.py`: lá ele
   guarda o resumo na mensagem; aqui ele mostra ao vivo. Mudou um, muda o
   outro. */

export interface PassoNavegador {
  acao: string;
  rotulo: string;
  status: 'pendente' | 'running' | 'ok' | 'error' | string;
  leitura: string;
}

export interface CartaoNavegador {
  site: string;
  passos: PassoNavegador[];
  status: 'rodando' | 'ok' | 'parou' | 'erro' | string;
  motivo: string;
  textos: number;
  prints: number;
  duracao_ms: number;
  retomada?: boolean;
  /** Só no client: quando começou, para o relógio ao vivo. */
  inicio?: number;
  _base?: number;
}

export interface EventoNavegador {
  fase?: string;
  site?: string;
  passos?: Array<{ acao?: string; rotulo?: string }>;
  indice?: number;
  status?: string;
  leitura?: string;
  motivo?: string;
  retomada?: boolean;
}

export function novoCartao(): CartaoNavegador {
  return { site: '', passos: [], status: 'rodando', motivo: '', textos: 0, prints: 0, duracao_ms: 0, retomada: false, _base: 0 };
}

export function aplicarEventoNavegador(
  anterior: CartaoNavegador | null, evento: EventoNavegador, agora = Date.now(),
): CartaoNavegador {
  const c: CartaoNavegador = anterior
    ? { ...anterior, passos: anterior.passos.map(p => ({ ...p })) }
    : novoCartao();
  if (evento.fase === 'inicio') {
    if (c.inicio === undefined) c.inicio = agora;
    c._base = c.passos.length;
    c.site = evento.site || c.site;
    c.status = 'rodando';
    c.motivo = '';
    if (evento.retomada) c.retomada = true;
    for (const p of evento.passos || []) {
      c.passos.push({ acao: p.acao || '', rotulo: p.rotulo || '', status: 'pendente', leitura: '' });
    }
  } else if (evento.fase === 'passo') {
    const passo = c.passos[(c._base || 0) + (evento.indice || 0)];
    if (passo) {
      passo.status = evento.status || 'ok';
      if (evento.leitura && !passo.leitura && passo.status !== 'running') {
        passo.leitura = evento.leitura;
        if (evento.leitura === 'texto') c.textos += 1; else c.prints += 1;
      }
    }
  } else if (evento.fase === 'fim') {
    c.status = evento.status || 'ok';
    c.motivo = evento.motivo || '';
    c.site = evento.site || c.site;
    for (const p of c.passos) if (p.status === 'running') p.status = c.status === 'ok' ? 'ok' : 'error';
  }
  if (c.inicio !== undefined) c.duracao_ms = agora - c.inicio;
  return c;
}

/** O que vai para a mensagem: sem os campos de trabalho do ao vivo. */
export function paraGuardar(c: CartaoNavegador | null): CartaoNavegador | undefined {
  if (!c || !c.passos.length) return undefined;
  const { inicio: _i, _base: _b, ...resto } = c;
  return { ...resto, status: resto.status === 'rodando' ? 'ok' : resto.status };
}

export function duracao(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(s / 60);
  return m ? `${m} min ${s % 60} s` : `${s} s`;
}
