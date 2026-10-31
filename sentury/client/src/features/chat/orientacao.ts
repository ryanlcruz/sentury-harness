import { ImagemAnexada } from '../../contracts/domain/session';

/**
 * Permite orientar um turno em andamento ou deixar uma mensagem na fila.
 *
 * - Orientar (Enter com o turno rodando): a mensagem vai para o turno em
 *   curso e entra no proximo ponto seguro. Na conversa ela aparece na hora,
 *   com um chip que diz onde esta: enviando -> aguardando -> entregue -> vista.
 * - Fila (Alt+Enter): espera o turno acabar bem e sai sozinha, uma por vez.
 *   Se o turno foi parado ou falhou, fica esperando: a pessoa decide.
 * - Parar e enviar: para o turno e manda a mensagem como turno novo.
 *
 * A orientacao que chega tarde (a resposta final ja estava sendo escrita)
 * sai da conversa e vai para a fila: ela nao some nem finge ter sido vista.
 */

export type FaseOrientacao = 'enviando' | 'recebida' | 'aplicada' | 'vista';

export interface OrientacaoDaMensagem {
  idCliente: string;
  fase: FaseOrientacao;
}

export interface ItemDaFila {
  id: string;
  texto: string;
  imagens?: ImagemAnexada[];
  arquivos?: ImagemAnexada[];
  funcoes?: string[];
}

const ORDEM: FaseOrientacao[] = ['enviando', 'recebida', 'aplicada', 'vista'];

export const ROTULO_DA_FASE: Record<FaseOrientacao, string> = {
  enviando: 'enviando',
  recebida: 'aguardando',
  aplicada: 'entregue',
  vista: 'vista',
};

export const DICA_DA_FASE: Record<FaseOrientacao, string> = {
  enviando: 'Indo para o turno em curso.',
  recebida: 'Chegou. Entra no próximo ponto seguro: antes do próximo passo.',
  aplicada: 'Entrou no turno. O próximo passo já é planejado com ela.',
  vista: 'O modelo leu esta mensagem.',
};

/** Os eventos podem chegar fora de ordem (o `vista` antes da resposta do
 * POST): a fase so anda para a frente. */
export function avancar(atual: FaseOrientacao, nova: FaseOrientacao): FaseOrientacao {
  return ORDEM.indexOf(nova) > ORDEM.indexOf(atual) ? nova : atual;
}

/** Ainda nao entrou no turno: se ele acabar, a mensagem vai para a fila. */
export function pendente(fase: FaseOrientacao): boolean {
  return fase === 'enviando' || fase === 'recebida';
}
