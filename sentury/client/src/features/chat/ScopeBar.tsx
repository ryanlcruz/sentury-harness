import React from 'react';
import { Search, X } from 'lucide-react';
import { useChatStore } from '../../stores/chat-store';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const LABELS: Record<string, string> = {
  regiao: 'região', filial: 'filial', unidade_negocio: 'unidade', categoria: 'categoria',
  periodo_inicio: 'de', periodo_fim: 'até',
};

export const ScopeBar: React.FC<{ sessionId: string; scope: Record<string, unknown> }> = ({ sessionId, scope }) => {
  const loadSession = useChatStore(state => state.loadSession);

  // Limpar escopo e operacao de estado, nao pergunta: mandar "limpar filtros"
  // pelo chat gastava um turno inteiro de LLM para esvaziar um dicionario.
  const limpar = async () => {
    const config = getRuntimeConfig();
    try {
      await apiClient.delete(
        `/sentury/sessions/${encodeURIComponent(sessionId)}/escopo?user_id=${encodeURIComponent(config.userId)}`,
        { headers: authHeaders() },
      );
      await loadSession(sessionId);
    } catch {
      // Falhou: o escopo continua na tela, que e a verdade do servidor.
    }
  };
  const entries = Object.entries(scope).filter(([, value]) => value !== null && value !== undefined && value !== '');
  if (!entries.length) return null;
  // Escopo é estado da conversa inteira. Dentro da área que rola ele virava um
  // cartão pairando sobre o texto; aqui é uma faixa própria, que empurra o
  // conteúdo em vez de cobrir.
  return <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-1.5 text-[10px]"><span className="mr-1 inline-flex items-center gap-1 rounded-md bg-zinc-900 px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-gold"><Search className="h-3 w-3" />Escopo</span>{entries.map(([key, value]) => <span key={key} className="rounded-full border border-stone-300 bg-white px-2 py-1 text-zinc-800"><strong>{LABELS[key] || key}:</strong> {String(value)}</span>)}<button type="button" onClick={() => void limpar()} className="ml-1 inline-flex items-center gap-1 rounded-full px-2 py-1 font-semibold text-zinc-500 hover:bg-red-50 hover:text-red-700" title="Voltar à visão geral"><X className="h-3 w-3" />limpar</button></div></div>;
};
