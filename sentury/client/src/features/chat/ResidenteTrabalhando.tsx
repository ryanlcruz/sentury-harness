import React, { useEffect } from 'react';
import type { ChatMessage } from '../../contracts/domain/session';
import { useChatStore } from '../../stores/chat-store';
import { Digitando } from '../residentes/Digitando';
import { useHQ } from '../residentes/useEsperando';

// A resposta do residente chega pelo servidor quando ele termina; sem consultar,
// ela só aparecia ao trocar de tela, e nada dizia que ele estava trabalhando.
const INTERVALO_MS = 4000;
const TETO_MS = 10 * 60 * 1000;

/** Quem a pessoa chamou nesta mensagem; histórico antigo só tem `mencao`. */
export function mencionados(mensagem: ChatMessage): string[] {
  if (mensagem.mencoes?.length) return mensagem.mencoes;
  return mensagem.mencao ? [mensagem.mencao] : [];
}

/** Os residentes que receberam uma tarefa nesta conversa e ainda não responderam,
 * na ordem em que foram chamados: com o chip "Falando com", podem ser vários. */
export function residentesEmCurso(mensagens: ChatMessage[]): string[] {
  const esperando: string[] = [];
  for (const mensagem of mensagens) {
    if (mensagem.role !== 'assistant') continue;
    if (mensagem.residente) {
      const i = esperando.indexOf(mensagem.residente);
      if (i >= 0) esperando.splice(i, 1);
    } else {
      for (const nome of mencionados(mensagem)) if (!esperando.includes(nome)) esperando.push(nome);
    }
  }
  return esperando;
}

export const ResidenteTrabalhando: React.FC<{ sessionId: string; mensagens: ChatMessage[] }> = ({ sessionId, mensagens }) => {
  const nomes = residentesEmCurso(mensagens);
  const chave = nomes.join(',');
  const loadSession = useChatStore(state => state.loadSession);
  const hq = useHQ();
  useEffect(() => {
    if (!chave) return;
    const inicio = Date.now();
    const timer = window.setInterval(() => {
      if (Date.now() - inicio > TETO_MS) { window.clearInterval(timer); return; }
      void loadSession(sessionId);
    }, INTERVALO_MS);
    return () => window.clearInterval(timer);
  }, [chave, sessionId, loadSession]);
  if (!nomes.length) return null;
  // Cada residente chamado aparece escrevendo, como um colega no chat.
  return (
    <div className="mb-6 space-y-3">
      {nomes.map(nome => <Digitando key={nome} nome={nome} agente={hq.agentes.find(a => a.nome === nome)} />)}
    </div>
  );
};
