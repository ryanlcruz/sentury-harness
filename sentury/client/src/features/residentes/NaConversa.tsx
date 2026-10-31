import React from 'react';
import { Coruja } from './Coruja';
import { coresDoAgente, useHQ } from './useEsperando';

/** A menção `@nome` como pílula, dentro da mensagem da pessoa. */
export const PilulaDoResidente: React.FC<{ nome: string; escura?: boolean }> = ({ nome, escura }) => {
  const agente = useHQ().agentes.find(item => item.nome === nome);
  return (
    <span title={`@${nome}`} className={`mx-0.5 inline-flex items-center gap-1 rounded-full py-px pl-0.5 pr-2 align-middle text-[13px] font-semibold ${escura
      ? 'border border-white/20 bg-white/10 text-[#fffdf7]' : 'border border-[#e3ddcd] bg-[#f3efe4] text-zinc-800'}`}>
      <span className="rounded-full bg-[#f7f3e8] leading-none">
        <Coruja cores={coresDoAgente(agente)} acessorios={agente?.aparencia.acessorios} tamanho={22} rotulo={nome} />
      </span>
      {nome[0].toUpperCase() + nome.slice(1)}
    </span>
  );
};

/** Quem fala quando a mensagem é de um residente: a coruja e o nome. */
export const CabecaDoResidente: React.FC<{ nome: string }> = ({ nome }) => {
  const agente = useHQ().agentes.find(item => item.nome === nome);
  const Nome = nome[0].toUpperCase() + nome.slice(1);
  return (
    <div className="mb-2 flex items-center gap-2.5">
      <span className="flex h-10 w-10 items-end justify-center overflow-hidden rounded-full border border-[#e3ddcd] bg-[#f3efe4] leading-none">
        <Coruja cores={coresDoAgente(agente)} acessorios={agente?.aparencia.acessorios} tamanho={38} rotulo={Nome} />
      </span>
      <span className="text-sm font-semibold text-zinc-900">{Nome}</span>
      {agente ? <span className="text-xs text-zinc-500">{agente.papel}</span> : null}
    </div>
  );
};

/** O texto que o servidor grava começa com "**Nome** respondeu:"; com a cabeça
 * desenhada, esse começo sobra. */
export function semPrefixoDoResidente(conteudo: string, nome: string): string {
  const Nome = nome[0].toUpperCase() + nome.slice(1);
  const prefixo = `**${Nome}** respondeu:`;
  return conteudo.startsWith(prefixo) ? conteudo.slice(prefixo.length).trimStart() : conteudo;
}
