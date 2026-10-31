import { renderToStaticMarkup } from 'react-dom/server';
import { Coruja } from './Coruja';
import { coresDoAgente } from './useEsperando';
import type { Agente } from './api';

/** O selo de um token no campo de texto: mantém o token (`@atlas`) como valor,
 * não é editável por dentro e o Backspace o apaga inteiro. */
function selo(token: string, classe: string): HTMLSpanElement {
  const badge = document.createElement('span');
  badge.contentEditable = 'false';
  badge.dataset.token = token;
  badge.title = token;
  badge.className = classe;
  return badge;
}

/** `@nome` de um residente: a coruja dele e o nome, igual em todo campo. */
export function seloDoResidente(agente: Agente, token = `@${agente.nome}`): HTMLElement {
  const badge = selo(token, 'mx-0.5 inline-flex select-none items-center gap-1 rounded-full border border-[#e3ddcd] bg-[#f3efe4] py-px pl-px pr-2 align-middle text-[13px] font-medium leading-5 text-zinc-800');
  badge.innerHTML = renderToStaticMarkup(
    <Coruja cores={coresDoAgente(agente)} acessorios={agente.aparencia.acessorios} tamanho={22} rotulo={agente.nome} />);
  badge.append(document.createTextNode(agente.nome[0].toUpperCase() + agente.nome.slice(1)));
  return badge;
}

/** `/nome` de uma skill. */
export function seloDaSkill(nome: string): HTMLElement {
  const badge = selo(`/${nome}`, 'mx-0.5 inline-flex select-none items-center rounded-md bg-zinc-900 px-1.5 py-px align-middle text-[12px] font-bold leading-5 text-gold');
  badge.textContent = nome;
  return badge;
}

/** O desenho dos tokens de um campo que só conhece residentes (e, se vierem, skills). */
export function desenhoDeResidentes(agentes: Agente[], skills: string[] = []): (token: string) => HTMLElement | null {
  return (token: string) => {
    const nome = token.slice(1).toLowerCase();
    if (token.startsWith('@')) {
      const agente = agentes.find(a => a.nome === nome);
      return agente ? seloDoResidente(agente, token) : null;
    }
    return skills.includes(nome) ? seloDaSkill(nome) : null;
  };
}
