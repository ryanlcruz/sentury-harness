import React, { useState } from 'react';
import { Coruja } from './Coruja';
import { coresDoAgente } from './useEsperando';
import { ferramentaPedida, residentes, type Agente, type Tarefa } from './api';

/** O que espera a pessoa: autorizar um comando ou responder uma pergunta. */
export const Esperando: React.FC<{ tarefa: Tarefa; agente?: Agente; onRespondida: () => void }> = ({ tarefa, agente, onRespondida }) => {
  const [retorno, setRetorno] = useState('');
  const ferramenta = ferramentaPedida(tarefa.pendente);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState('');
  const responder = async (resposta: 'uma_vez' | 'negar' | '') => {
    setEnviando(true);
    setErro('');
    try {
      await residentes.responder(tarefa.id, resposta, retorno);
      onRespondida();
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui responder');
      setEnviando(false);
    }
  };
  if (tarefa.motivo === 'pessoa no controle') {
    return <div className="px-5 py-4 text-sm"><span className="font-semibold capitalize">{tarefa.agente}</span> espera você devolver o navegador pela aba Tela.</div>;
  }
  return (
    <div className="flex flex-wrap items-center gap-4 px-5 py-4">
      {agente ? <Coruja cores={coresDoAgente(agente)} acessorios={agente.aparencia.acessorios} estado="esperando" tamanho={48} rotulo={agente.nome} /> : null}
      <div className="min-w-[240px] flex-1">
        <p className="text-sm"><strong className="font-semibold capitalize">{tarefa.agente}</strong> {ferramenta ? 'pediu uma ferramenta nova:' : tarefa.pendente ? 'quer rodar fora da caixa:' : 'perguntou:'}</p>
        {tarefa.pendente
          ? <code className="mt-1 block font-mono text-[13px] text-zinc-950">{ferramenta || tarefa.pendente}</code>
          : <p className="mt-1 text-sm text-zinc-700">{tarefa.resposta || tarefa.motivo}</p>}
        {ferramenta && tarefa.motivo.includes(': ') ? <p className="mt-1 text-sm text-zinc-700">{tarefa.motivo.slice(tarefa.motivo.indexOf(': ') + 2)}</p> : null}
        <p className="mt-1 text-xs text-zinc-500">Tarefa: "{tarefa.pedido}"</p>
        {erro ? <p className="mt-1 text-xs text-red-600">{erro}</p> : null}
      </div>
      {tarefa.pendente ? (
        <div className="flex gap-2">
          <button type="button" disabled={enviando} onClick={() => void responder('uma_vez')}
            className="h-11 rounded-lg bg-gold px-4 text-sm font-semibold text-zinc-950 transition hover:bg-gold-hover disabled:opacity-50">{ferramenta ? 'Liberar' : 'Autorizar desta vez'}</button>
          <button type="button" disabled={enviando} onClick={() => void responder('negar')}
            className="h-11 rounded-lg border border-[#d8cfbd] bg-white px-4 text-sm text-zinc-900 transition hover:border-zinc-400 disabled:opacity-50">Negar</button>
        </div>
      ) : (
        <form className="flex w-full gap-2 sm:w-auto" onSubmit={event => { event.preventDefault(); if (retorno.trim()) void responder(''); }}>
          <label className="sr-only" htmlFor={`retorno-${tarefa.id}`}>Sua resposta</label>
          <input id={`retorno-${tarefa.id}`} value={retorno} onChange={event => setRetorno(event.target.value)} placeholder="Sua resposta"
            className="h-11 min-w-0 flex-1 rounded-lg border border-[#d8cfbd] bg-white px-3 text-sm outline-none focus:border-gold-hover sm:w-64" />
          <button type="submit" disabled={enviando || !retorno.trim()}
            className="h-11 rounded-lg bg-gold px-4 text-sm font-semibold text-zinc-950 disabled:opacity-50">Responder</button>
        </form>
      )}
    </div>
  );
};
