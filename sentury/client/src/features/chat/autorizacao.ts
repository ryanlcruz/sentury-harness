/** A mensagem que o cartão de permissão manda para retomar o turno.
 *
 * O texto vai ao modelo como está (o Telegram manda o mesmo), mas na conversa
 * ele vira uma linha discreta: é o registro de uma aprovação, não fala da pessoa. */

const PADRAO = /^Autorizado\. Pode rodar `([^`]+)`\.$/;

export const textoDeAutorizacao = (comando: string): string => `Autorizado. Pode rodar \`${comando}\`.`;

export function comandoAutorizado(texto: string): string | null {
  const achado = texto.trim().match(PADRAO);
  return achado ? achado[1] : null;
}

/** "criar_agente vigia" (ou a equipe, "criar_agente alfa, nina") vira os nomes
 * que a pessoa reconhece; o resto mostra o comando. */
export function residenteAprovado(comando: string): string[] | null {
  const achado = comando.match(/^criar_agente\s+([a-z][a-z0-9-]*(?:,\s*[a-z][a-z0-9-]*)*)$/);
  return achado ? achado[1].split(/,\s*/).map(nome => nome[0].toUpperCase() + nome.slice(1)) : null;
}
