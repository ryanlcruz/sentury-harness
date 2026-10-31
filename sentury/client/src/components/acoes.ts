import { ActionIntent } from '../contracts/events/session-events';

/**
 * O verbo que o usuário lê quando uma ferramenta roda.
 *
 * O backend já decide a intenção de cada ferramenta (`sentury/tools/selos.py`)
 * e a manda no `tool_start`. O contrato validava e a tela ignorava: sobrava
 * "Executando ferramenta" para tudo — medir, entregar, alterar e perguntar
 * viravam a mesma frase.
 *
 * O verbo importa porque `alterar` e `consultar` pedem atenção diferente de
 * quem lê. Ver "Alterando" passar na tela é a diferença entre acompanhar e
 * descobrir depois.
 */
export const VERBO_DA_ACAO: Record<ActionIntent, string> = {
  medir: 'Medindo',
  investigar: 'Investigando',
  recomendar: 'Recomendando',
  entregar: 'Entregando',
  consultar: 'Consultando',
  alterar: 'Alterando',
  executar: 'Executando',
  perguntar: 'Perguntando',
  pensar: 'Pensando',
  // `outro` não vira verbo: inventar um rótulo para o que não se sabe é pior
  // que a frase genérica, que pelo menos não afirma nada.
  outro: '',
};

export function verboDaAcao(intent?: string | null): string {
  if (!intent) return '';
  return VERBO_DA_ACAO[intent as ActionIntent] || '';
}
