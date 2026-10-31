import { useEffect, useState } from 'react';
import { Play, ServerCrash, X } from 'lucide-react';
import { useChatStore } from '../../stores/chat-store';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { funcoesDoEnvio } from '../../runtime/funcoes-nativas';

/**
 * O servidor caiu no meio de um turno desta conversa (harness/registro_do_turno.py).
 *
 * O turno não continua sozinho: a conversa avisa, mostra o que já
 * tinha rodado e oferece Continuar. Continuar faz o turno seguinte começar
 * com a lista do que já foi feito, para nada ser feito duas vezes.
 */

interface Passo {
  ferramenta: string;
  status: string;
  efeito_colateral?: boolean;
}

interface Registro {
  status?: string;
  pedido?: string;
  passos?: Passo[];
}

export function TurnoInterrompidoCard({ sessionId, conversando }: { sessionId: string; conversando: boolean }) {
  const sendMessage = useChatStore(state => state.sendMessage);
  const [registro, setRegistro] = useState<Registro | null>(null);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    if (conversando) return;
    let vivo = true;
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    apiClient.get<Registro>(`/sentury/sessions/${encodeURIComponent(sessionId)}/turno`, { headers: authHeaders() })
      .then(dado => { if (vivo) setRegistro(dado && dado.status === 'reinicio' ? dado : null); })
      .catch(() => { if (vivo) setRegistro(null); });
    return () => { vivo = false; };
  }, [sessionId, conversando]);

  if (!registro || conversando) return null;
  const passos = registro.passos || [];
  const feitos = passos.filter(p => p.status === 'ok' || p.status === 'erro').length;
  const incertos = passos.filter(p => p.status === 'incerto');

  const agir = async (acao: 'continuar' | 'dispensar') => {
    setOcupado(true);
    try {
      const resposta = await apiClient.post<{ mensagem?: string; funcoes?: string[] }>(
        `/sentury/sessions/${encodeURIComponent(sessionId)}/turno/${acao}`, {}, { headers: authHeaders() });
      setRegistro(null);
      if (acao === 'continuar') {
        const pedido = resposta.mensagem || registro.pedido;
        if (pedido) await sendMessage(sessionId, pedido, [], resposta.funcoes ?? funcoesDoEnvio(sessionId, pedido), [], { retomar: true });
      }
    } finally {
      setOcupado(false);
    }
  };

  return (
    <section aria-label="Turno interrompido pelo reinício" className="mb-6 max-w-3xl rounded-[14px] border border-amber-200 bg-amber-50/70 px-4 py-3">
      <div className="flex items-start gap-3">
        <ServerCrash className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-zinc-900">O servidor reiniciou no meio deste turno</p>
          {registro.pedido ? <p className="mt-0.5 truncate text-xs text-zinc-600">Pedido: {registro.pedido}</p> : null}
          <p className="mt-1 text-xs text-zinc-600">
            {feitos} passo{feitos === 1 ? '' : 's'} já tinha{feitos === 1 ? '' : 'm'} rodado.
            {incertos.length ? ` ${incertos.map(p => p.ferramenta).join(', ')} estava no meio: pode ter acontecido ou não.` : ''}
            {' '}Continuar retoma daí sem refazer o que já foi feito.
          </p>
        </div>
      </div>
      <div className="mt-2.5 flex justify-end gap-2">
        <button type="button" disabled={ocupado} onClick={() => void agir('dispensar')}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 text-xs font-medium text-zinc-700 hover:bg-stone-100 disabled:opacity-50">
          <X className="h-3.5 w-3.5" />Dispensar
        </button>
        <button type="button" disabled={ocupado} onClick={() => void agir('continuar')}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-gold px-3 text-xs font-semibold text-zinc-950 hover:bg-gold-hover disabled:opacity-50">
          <Play className="h-3.5 w-3.5" />Continuar
        </button>
      </div>
    </section>
  );
}
