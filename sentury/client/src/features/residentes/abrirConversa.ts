/** Abrir o chat de um residente, ou um assunto da Mesa, de qualquer ponto da
 * conversa principal: a troca completa mora lá, e a conversa do Sentury mostra
 * só o resumo. */
const EVENTO = 'sentury:abrir-residente';
const EVENTO_MESA = 'sentury:abrir-mesa';

export function abrirConversaDoResidente(nome: string): void {
  window.dispatchEvent(new CustomEvent<string>(EVENTO, { detail: nome }));
}

export function aoAbrirConversaDoResidente(abrir: (nome: string) => void): () => void {
  return ouvir(EVENTO, abrir);
}

export function abrirAssuntoDaMesa(id: string): void {
  window.dispatchEvent(new CustomEvent<string>(EVENTO_MESA, { detail: id }));
}

export function aoAbrirAssuntoDaMesa(abrir: (id: string) => void): () => void {
  return ouvir(EVENTO_MESA, abrir);
}

function ouvir(evento: string, abrir: (valor: string) => void): () => void {
  const aoEvento = (e: Event) => {
    const valor = (e as CustomEvent<string>).detail;
    if (typeof valor === 'string' && valor) abrir(valor);
  };
  window.addEventListener(evento, aoEvento);
  return () => window.removeEventListener(evento, aoEvento);
}
