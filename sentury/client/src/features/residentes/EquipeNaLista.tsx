import React, { useState } from 'react';
import { Building2, Search, Users } from 'lucide-react';
import { Coruja } from './Coruja';
import { coresDoAgente, useHQ } from './useEsperando';
import { estadoDaCoruja, NOME_DO_ESTADO, nomeVisivel } from './api';
import { useMesa } from './useMesa';

/** A aba Equipe do painel de conversas: uma conversa por residente. */
export const EquipeNaLista: React.FC<{
  selecionado?: string | null;
  onSelecionar: (nome: string) => void;
  mesaSelecionada?: boolean;
  onMesa?: () => void;
  onAbrirHQ?: () => void;
}> = ({ selecionado, onSelecionar, mesaSelecionada, onMesa, onAbrirHQ }) => {
  const hq = useHQ();
  const mesa = useMesa();
  const abertos = mesa.assuntos.filter(a => a.estado === 'aberto').length;
  const ultimo = [...mesa.assuntos].sort((a, b) => b.atualizado_em - a.atualizado_em)[0];
  const [busca, setBusca] = useState('');
  const filtro = busca.trim().toLowerCase();
  const lista = hq.agentes.filter(a => `${a.nome} ${a.papel}`.toLowerCase().includes(filtro));
  return (
    <>
      <label className="mx-3 mt-3 flex items-center gap-2 rounded-lg border border-stone-200 bg-white/75 px-2.5 py-2 focus-within:border-gold">
        <Search className="h-3.5 w-3.5 text-zinc-400" />
        <input value={busca} onChange={event => setBusca(event.target.value)} placeholder="Buscar residente"
          className="w-full bg-transparent text-xs outline-none placeholder:text-zinc-400" />
      </label>
      <div className="flex-1 space-y-1 overflow-y-auto p-3">
        {onMesa ? (
          <button type="button" onClick={onMesa} aria-pressed={Boolean(mesaSelecionada)}
            className={`mb-2 flex w-full items-center gap-2.5 rounded-lg border border-stone-200 bg-white/60 px-2 py-2 text-left hover:bg-white ${mesaSelecionada ? 'bg-white ring-1 ring-stone-200' : ''}`}>
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gold-soft text-gold-ink"><Users className="h-4 w-4" /></span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-zinc-900">Mesa</span>
              <span className="block truncate text-[11px] text-zinc-500">{ultimo?.titulo || 'O que os residentes conversam entre si'}</span>
            </span>
            {abertos ? <span className="shrink-0 rounded-full bg-gold px-1.5 text-[10px] font-bold text-zinc-950" aria-label={`${abertos} assuntos abertos`}>{abertos} aberto{abertos > 1 ? 's' : ''}</span> : null}
          </button>
        ) : null}
        {lista.map(agente => {
          const estado = estadoDaCoruja(agente, hq.esperando);
          const esperando = estado === 'esperando';
          return (
            <button key={agente.nome} type="button" onClick={() => onSelecionar(agente.nome)}
              aria-pressed={selecionado === agente.nome}
              className={`flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left hover:bg-white ${selecionado === agente.nome ? 'bg-white ring-1 ring-stone-200' : ''}`}>
              <Coruja tamanho={32} cores={coresDoAgente(agente)} acessorios={agente.aparencia.acessorios} estado={estado} rotulo={agente.nome} />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-1.5">
                  <span className="shrink-0 text-sm font-semibold text-zinc-900">{nomeVisivel(agente.nome)}</span>
                  <span className="truncate text-[11px] text-zinc-500">{agente.papel}</span>
                </span>
                <span className={`block truncate text-[11px] ${esperando ? 'font-medium text-gold-ink' : 'text-zinc-400'}`}>
                  {esperando ? 'Esperando você' : (agente as { previa?: string }).previa || NOME_DO_ESTADO[estado]}
                </span>
              </span>
              <span aria-label={NOME_DO_ESTADO[estado]} title={NOME_DO_ESTADO[estado]}
                className={`h-2 w-2 shrink-0 rounded-full ${estado === 'trabalhando' ? 'bg-emerald-500' : esperando ? 'bg-amber-500' : 'bg-stone-300'}`} />
            </button>
          );
        })}
        {!lista.length ? (
          <p className="px-2 py-3 text-xs leading-5 text-zinc-500">
            {hq.agentes.length ? 'Nenhum residente com esse nome.' : 'Ainda não há residentes. Descreva o trabalho na conversa com o Sentury: ele propõe o residente e você aprova.'}
          </p>
        ) : null}
      </div>
      {onAbrirHQ ? (
        <button type="button" onClick={onAbrirHQ}
          className="mx-3 mb-2 flex items-center gap-2 rounded-lg px-2 py-2 text-left text-[12px] text-zinc-600 hover:bg-white hover:text-zinc-900">
          <Building2 className="h-3.5 w-3.5" />O Escritório fica na HQ
        </button>
      ) : null}
    </>
  );
};
