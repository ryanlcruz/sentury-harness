/* O cartão do computer use, montado a partir dos eventos `computador` do
   stream (`sentury/tools/computador.py`, `_emitir_gesto`). Cada gesto chega
   duas vezes: `rodando` e depois `ok`, `erro` ou `parado`. */

export interface GestoComputador {
  acao: string;
  /** O gesto em palavras, o mesmo do balão ao lado do mouse ("clicar"). */
  titulo: string;
  /** O que o narrador disse do passo; sem fala, o gesto com a coordenada. */
  detalhe: string;
  status: 'rodando' | 'ok' | 'erro' | 'parado' | string;
  tecla?: string;
}

export interface CartaoComputador {
  gestos: GestoComputador[];
  status: 'rodando' | 'pronta' | 'parada' | 'encerrada' | string;
  parado: boolean;
  prints: number;
  /** Conferências pela lista de elementos, sem print. */
  leituras?: number;
  janela: string;
  objetivo: string;
  turno: number;
  limite: number;
  retomada?: boolean;
  /** A vez da pessoa (login, senha, CAPTCHA): até ela devolver, nada vê nem mexe. */
  vez?: VezDoComputador | null;
}

export interface VezDoComputador {
  com: 'pessoa' | 'agente' | string;
  motivo: string;
}

export interface EventoComputador {
  fase?: string;
  acao?: string;
  titulo?: string;
  descricao?: string;
  fala?: string;
  status?: string;
  tecla?: string;
  prints?: number;
  leituras?: number;
  janela?: string;
  objetivo?: string;
  turno?: number;
  limite?: number;
  retomada?: boolean;
  com?: string;
  motivo?: string;
}

// O cartão mostra os últimos: um jogo passa de cem gestos num turno.
export const GESTOS_VISIVEIS = 7;
// As teclinhas do "Agora": as quatro últimas, a de agora em destaque.
export const TECLAS_VISIVEIS = 4;

export function novoCartaoComputador(): CartaoComputador {
  return { gestos: [], status: 'rodando', parado: false, prints: 0, janela: '', objetivo: '', turno: 0, limite: 0, retomada: false };
}

export function aplicarEventoComputador(anterior: CartaoComputador | null, evento: EventoComputador): CartaoComputador {
  const cartao: CartaoComputador = { ...(anterior || novoCartaoComputador()) };
  cartao.gestos = [...cartao.gestos];
  if (evento.fase === 'sessao') {
    cartao.status = String(evento.status || 'pronta');
    cartao.parado = cartao.status === 'parada';
    if (evento.retomada) cartao.retomada = true;
    return cartao;
  }
  if (evento.fase === 'vez') {
    cartao.vez = { com: String(evento.com || ''), motivo: String(evento.motivo || '') };
    return cartao;
  }
  if (evento.fase !== 'gesto') return cartao;
  if (typeof evento.prints === 'number') cartao.prints = Math.max(cartao.prints, evento.prints);
  if (typeof evento.leituras === 'number') cartao.leituras = Math.max(cartao.leituras || 0, evento.leituras);
  if (evento.janela) cartao.janela = String(evento.janela);
  if (evento.objetivo) cartao.objetivo = String(evento.objetivo);
  if (typeof evento.turno === 'number') cartao.turno = evento.turno;
  if (typeof evento.limite === 'number') cartao.limite = evento.limite;
  const gesto: GestoComputador = {
    acao: String(evento.acao || ''),
    titulo: String(evento.titulo || evento.acao || ''),
    detalhe: String(evento.fala || evento.descricao || ''),
    status: String(evento.status || 'rodando'),
    tecla: evento.tecla ? String(evento.tecla) : undefined,
  };
  const ultimo = cartao.gestos[cartao.gestos.length - 1];
  // O fim de um gesto substitui o `rodando` dele, em vez de virar outra linha.
  if (ultimo && ultimo.status === 'rodando' && ultimo.titulo === gesto.titulo && gesto.status !== 'rodando') {
    cartao.gestos[cartao.gestos.length - 1] = gesto;
  } else {
    cartao.gestos.push(gesto);
  }
  cartao.status = 'rodando';
  if (gesto.status === 'parado') { cartao.parado = true; cartao.status = 'parada'; }
  return cartao;
}

export function paraGuardarComputador(c: CartaoComputador | null): CartaoComputador | undefined {
  if (!c) return undefined;
  return { ...c, gestos: c.gestos.map(g => ({ ...g })), status: c.status === 'rodando' ? 'pronta' : c.status };
}

/** As teclas recentes para as teclinhas do "Agora"; a última é a de agora
    se o gesto atual for uma tecla. */
export function teclasRecentes(cartao: CartaoComputador): Array<{ nome: string; agora: boolean }> {
  const ultimoIndice = cartao.gestos.length - 1;
  return cartao.gestos
    .map((g, i) => ({ g, i }))
    .filter(({ g }) => Boolean(g.tecla))
    .slice(-TECLAS_VISIVEIS)
    .map(({ g, i }) => ({ nome: g.tecla as string, agora: i === ultimoIndice }));
}
