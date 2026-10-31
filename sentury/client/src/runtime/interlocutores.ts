/** Com quem a conversa está falando: os residentes do chip "Falando com".
 *
 * Mencionar um residente no começo da mensagem abre o chip dele; enquanto houver
 * chip, a mensagem sem `@` vai para todos os residentes marcados. Fechar o chip
 * devolve a conversa ao Sentury. Fica por conversa, como os acessos. */

const PREFIXO = 'sentury-interlocutores:';

export function lerInterlocutores(sessionId: string | null | undefined): string[] {
  if (!sessionId) return [];
  try {
    const bruto = JSON.parse(window.localStorage.getItem(PREFIXO + sessionId) || '[]') as unknown;
    return Array.isArray(bruto) ? bruto.filter((nome): nome is string => typeof nome === 'string') : [];
  } catch {
    return [];
  }
}

export function salvarInterlocutores(sessionId: string, nomes: string[]): void {
  try {
    if (nomes.length) window.localStorage.setItem(PREFIXO + sessionId, JSON.stringify(nomes));
    else window.localStorage.removeItem(PREFIXO + sessionId);
  } catch {
    // Sem storage o chip vale só enquanto a aba estiver aberta.
  }
}

/** As menções do começo da mensagem (`@alfa @nina faça X`) e o pedido que sobra.
 * Menção no meio da frase não conta: é uma fala sobre o residente, para o Sentury. */
export function mencoesIniciais(texto: string, conhecido: (nome: string) => boolean): { nomes: string[]; pedido: string } {
  const nomes: string[] = [];
  let resto = texto.trim();
  for (;;) {
    const achado = resto.match(/^@([a-z][a-z0-9-]{1,30})(?=\s|$)\s*/i);
    if (!achado || !conhecido(achado[1])) break;
    const nome = achado[1].toLowerCase();
    if (!nomes.includes(nome)) nomes.push(nome);
    resto = resto.slice(achado[0].length);
  }
  return { nomes, pedido: resto.trim() };
}

/** A Mesa em que a conversa está falando: com o chip "Na Mesa", a mensagem vai
 * para o assunto, e a discussão corre lá. Exclui os residentes do chip. */
export interface MesaDaConversa { id: string; titulo: string }

const PREFIXO_MESA = 'sentury-mesa-da-conversa:';

export function lerMesaDaConversa(sessionId: string | null | undefined): MesaDaConversa | null {
  if (!sessionId) return null;
  try {
    const bruto = JSON.parse(window.localStorage.getItem(PREFIXO_MESA + sessionId) || 'null') as Partial<MesaDaConversa> | null;
    return bruto && typeof bruto.id === 'string' && typeof bruto.titulo === 'string' ? { id: bruto.id, titulo: bruto.titulo } : null;
  } catch {
    return null;
  }
}

export function salvarMesaDaConversa(sessionId: string, mesa: MesaDaConversa | null): void {
  try {
    if (mesa) window.localStorage.setItem(PREFIXO_MESA + sessionId, JSON.stringify(mesa));
    else window.localStorage.removeItem(PREFIXO_MESA + sessionId);
  } catch {
    // Sem storage o chip vale só enquanto a aba estiver aberta.
  }
}
