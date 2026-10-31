import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, Clock, Infinity as InfinityIcon, ShieldAlert, X } from 'lucide-react';
import { PermissaoPayload } from '../../contracts/events/session-events';
import { apiClient } from '../../transport/http-client';
import { useChatStore } from '../../stores/chat-store';
import { FabricaDoResidente } from '../residentes/FabricaDoResidente';
import { EquipeDeResidentes } from '../residentes/EquipeDeResidentes';
import { textoDeAutorizacao } from './autorizacao';

interface PermissionSheetProps {
  messageId: string;
  sessionId: string;
  permissao: PermissaoPayload;
}

type Resposta = 'uma_vez' | 'sessao' | 'sempre' | 'negar' | 'negar_sempre';

// A ordem importa: "nesta conversa" é o sim normal, e fica primeiro. "Sempre"
// grava no disco e por isso vem depois — quem quer parar de ser perguntado
// escolhe conscientemente, não por ser o botão mais fácil de acertar.
const OPCOES: { resposta: Resposta; rotulo: string; explica: string; Icon: typeof Check }[] = [
  { resposta: 'sessao', rotulo: 'Nesta conversa', explica: 'Vale até esta conversa acabar', Icon: Clock },
  { resposta: 'uma_vez', rotulo: 'Só desta vez', explica: 'Pergunto de novo na próxima', Icon: Check },
  { resposta: 'sempre', rotulo: 'Sempre', explica: 'Fica gravado; não pergunto mais', Icon: InfinityIcon },
  { resposta: 'negar', rotulo: 'Não', explica: 'Não roda agora; pergunto de novo depois', Icon: X },
];

export const PermissionSheet: React.FC<PermissionSheetProps> = ({ sessionId, messageId, permissao }) => {
  const [enviando, setEnviando] = useState<Resposta | null>(null);

  const [erro, setErro] = useState('');
  const sendMessage = useChatStore(state => state.sendMessage);
  const dispensar = useChatStore(state => state.dispensarInterativo);


  const responder = async (resposta: Resposta) => {
    setEnviando(resposta);
    setErro('');
    try {
      await apiClient.post('/sentury/permissoes', {
        comando: permissao.comando,
        resposta,
        session_id: sessionId,
      });
      dispensar(sessionId, messageId, 'permissao');
      // Negar não vira nova tentativa: o agente já sabe o motivo e seguir
      // pedindo seria transformar a recusa em insistência.
      if (resposta !== 'negar' && resposta !== 'negar_sempre') void sendMessage(sessionId, textoDeAutorizacao(permissao.comando));
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui registrar a resposta');
      setEnviando(null);
    }
  };

  // Equipe: cada marcado é aprovado com o próprio comando, o mesmo que a
  // ferramenta confere ao criar; a retomada cria todos os aprovados.
  const criarEquipe = async (nomes: string[]) => {
    setEnviando('uma_vez');
    setErro('');
    try {
      for (const nome of nomes) {
        await apiClient.post('/sentury/permissoes', { comando: `criar_agente ${nome}`, resposta: 'uma_vez', session_id: sessionId });
      }
      dispensar(sessionId, messageId, 'permissao');
      void sendMessage(sessionId, textoDeAutorizacao(`criar_agente ${nomes.join(', ')}`));
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui registrar a resposta');
      setEnviando(null);
    }
  };

  const chatCanvas = document.getElementById('sentury-main');
  if (permissao.ferramenta === 'criar_agente' && (permissao.equipe?.length || 0) > 1) {
    return (
      <div className="sentury-needs-user my-4 max-w-[720px] overflow-hidden rounded-2xl border border-[#d8cfbd] bg-[#fffdf8] shadow-[0_1px_2px_rgba(35,31,24,.06)]">
        <EquipeDeResidentes
          equipe={permissao.equipe || []}
          enviando={enviando !== null}
          erro={erro}
          onCriar={nomes => void criarEquipe(nomes)}
          onNaoCriar={() => void responder('negar')}
          onFechar={() => dispensar(sessionId, messageId, 'permissao')}
        />
      </div>
    );
  }
  if (permissao.ferramenta === 'criar_agente' && permissao.argumentos) {
    return (
      <div className="sentury-needs-user my-4 max-w-[720px] overflow-hidden rounded-2xl border border-[#d8cfbd] bg-[#fffdf8] shadow-[0_1px_2px_rgba(35,31,24,.06)]">
          <FabricaDoResidente
            sessionId={sessionId}
            argumentos={permissao.argumentos}
            enviando={enviando !== null}
            erro={erro}
            onCriar={() => void responder('uma_vez')}
            onNaoCriar={() => void responder('negar')}
            onFechar={() => dispensar(sessionId, messageId, 'permissao')}
          />
      </div>
    );
  }
  return createPortal(
    <div className={`pointer-events-none ${chatCanvas ? 'absolute' : 'fixed'} inset-0 z-[66]`}>
      <div className="sentury-needs-user pointer-events-auto absolute inset-x-0 bottom-0 mx-auto w-[min(640px,calc(100%-32px))] rounded-t-2xl border border-b-0 border-[#d8cfbd] bg-[#fffdf8] shadow-[0_-18px_48px_rgba(35,31,24,.16)]">
        <header className="flex items-start gap-3 border-b border-stone-200 px-5 py-4">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-gold-ink" strokeWidth={1.8} />
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-gold-ink">Precisa da sua autorização</p>
            <code className="mt-1 block break-all font-mono text-sm text-zinc-950">{permissao.comando}</code>
            {permissao.motivo && <p className="mt-1 text-xs leading-5 text-zinc-500">{permissao.motivo}</p>}
          </div>
          <button
            type="button"
            onClick={() => dispensar(sessionId, messageId, 'permissao')}
            className="cursor-pointer rounded-md p-1 text-zinc-400 transition hover:bg-stone-100 hover:text-zinc-700"
            aria-label="Fechar sem decidir"
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </header>

        <div className="grid grid-cols-2 gap-2 p-4">
          {OPCOES.filter(o => !permissao.so_desta_vez || o.resposta === 'uma_vez' || o.resposta === 'negar').map(({ resposta, rotulo, explica: padrao, Icon }) => {
            const explica = resposta === 'sessao' && permissao.nesta_conversa === 'scripts'
              ? 'Os próximos scripts nesta pasta não perguntam; apagar arquivo ainda pergunta' : padrao;
            return (
            <button
              key={resposta}
              type="button"
              disabled={enviando !== null}
              onClick={() => void responder(resposta)}
              className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition disabled:cursor-wait disabled:opacity-50 ${
                resposta === 'negar'
                  ? 'border-stone-200 bg-white hover:border-red-300 hover:bg-red-50/50'
                  : 'border-stone-200 bg-white hover:border-gold-ink hover:bg-[#fdf8ec]'
              }`}
            >
              <Icon
                className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${resposta === 'negar' ? 'text-red-600' : 'text-gold-ink'}`}
                strokeWidth={1.8}
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-zinc-900">{rotulo}</span>
                <span className="block text-[11px] leading-4 text-zinc-500">{explica}</span>
              </span>
            </button>
            );
          })}
        </div>

        {erro && <p className="px-5 pb-3 text-xs text-red-600">{erro}</p>}

        {/* Banir fica fora da grade de propósito: é a única resposta que muda
            algo além deste turno, e não deve competir com "não" por um clique. */}
        <div className="px-4 pb-3">
          <button
            type="button"
            disabled={enviando !== null}
            onClick={() => void responder('negar_sempre')}
            className="cursor-pointer text-[11px] text-zinc-500 underline decoration-dotted underline-offset-2 transition hover:text-red-600 disabled:cursor-wait"
          >
            Não, e nunca mais pergunte por esse comando
          </button>
        </div>
        <p className="border-t border-stone-200 px-5 py-2.5 text-[11px] text-zinc-500">
          {permissao.so_desta_vez
            ? 'Esta ação tem uma consequência que exige confirmação: pergunto de novo a cada execução.'
            : <>A permissão cobre <span className="font-mono text-zinc-700">{permissao.chave}</span>, não esta linha exata.
          Leitura nunca passa por aqui.</>}
        </p>
      </div>
    </div>,
    chatCanvas || document.body,
  );
};
