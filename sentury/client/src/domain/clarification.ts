import type { ClarificationPayload } from '../contracts/domain/session';

export interface AnswerState {
  selected: string[];
  custom: string;
}

export function montarRespostas(clarification: ClarificationPayload, answers: Record<number, AnswerState>) {
  return {
    respostas: clarification.questions.map((question, index) => ({
      pergunta: question.question,
      selecionadas: answers[index]?.selected || [],
      outro: answers[index]?.custom.trim() || '',
    })),
  };
}

export interface RespostaLegivel {
  pergunta: string;
  escolhas: string[];
  outro: string;
}

/** O pacote que `montarRespostas` manda vira pergunta, escolhas e texto livre.
 * O texto da mensagem é o JSON que o servidor valida; mostrado cru, a pessoa
 * via chaves e aspas no lugar do que ela escolheu. Outro texto devolve null. */
export function lerRespostas(texto: string): RespostaLegivel[] | null {
  const limpo = (texto || '').trim();
  if (!limpo.startsWith('{') || !limpo.includes('"respostas"')) return null;
  try {
    const dado = JSON.parse(limpo);
    if (!dado || !Array.isArray(dado.respostas) || !dado.respostas.length) return null;
    return dado.respostas.map((item: { pergunta?: unknown; selecionadas?: unknown; outro?: unknown }) => {
      const escolhas = Array.isArray(item.selecionadas) ? item.selecionadas.map(String) : [];
      const outro = typeof item.outro === 'string' ? item.outro.trim() : '';
      return { pergunta: typeof item.pergunta === 'string' ? item.pergunta : '', escolhas, outro };
    });
  } catch {
    return null;
  }
}
