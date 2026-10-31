import React, { useEffect, useState } from 'react';
import { MessageSquare, Send, X } from 'lucide-react';
import { EVENTO_PROPOSTA, type PropostaDoBloco as Proposta } from '../../domain/blocoVivo/ponte';
import { useChatStore } from '../../stores/chat-store';

interface PropostaDoBlocoProps {
  corpo: React.RefObject<HTMLDivElement | null>;
  sessionId: string;
}

/** O bloco vivo pode propor uma mensagem; ela só vai quando a pessoa confirma,
 * e vai como mensagem dela, com o texto à vista. */
export const PropostaDoBloco: React.FC<PropostaDoBlocoProps> = ({ corpo, sessionId }) => {
  const [texto, setTexto] = useState<string | null>(null);
  const sendMessage = useChatStore(state => state.sendMessage);

  useEffect(() => {
    const aoPropor = (evento: Event) => {
      const { texto: proposto, quadro } = (evento as CustomEvent<Proposta>).detail;
      if (corpo.current?.contains(quadro)) setTexto(proposto);
    };
    window.addEventListener(EVENTO_PROPOSTA, aoPropor);
    return () => window.removeEventListener(EVENTO_PROPOSTA, aoPropor);
  }, [corpo]);

  if (!texto) return null;
  return (
    <div className="bloco-vivo-proposta" role="group" aria-label="Mensagem proposta pelo bloco">
      <MessageSquare className="h-3.5 w-3.5 shrink-0 text-gold-hover" />
      <span>O bloco quer enviar:</span>
      <q className="min-w-0 flex-1 font-medium text-zinc-800">{texto}</q>
      <button
        type="button"
        onClick={() => { void sendMessage(sessionId, texto); setTexto(null); }}
        className="inline-flex items-center gap-1 rounded-md bg-zinc-900 px-2.5 py-1 text-[11px] font-semibold text-white"
      >
        <Send className="h-3 w-3" />Enviar
      </button>
      <button
        type="button"
        onClick={() => setTexto(null)}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-zinc-500 hover:bg-stone-100"
      >
        <X className="h-3 w-3" />Descartar
      </button>
    </div>
  );
};
