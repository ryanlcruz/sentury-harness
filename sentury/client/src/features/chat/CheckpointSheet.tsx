import React, { useCallback, useEffect, useState } from 'react';
import { History, RotateCcw, TriangleAlert, X } from 'lucide-react';
import { z } from 'zod';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { useChatStore } from '../../stores/chat-store';

const CheckpointSchema = z.object({
  checkpoints: z.array(z.object({
    indice: z.number(),
    texto: z.string().default(''),
    respondido: z.boolean().default(false),
    passos: z.number().default(0),
    interrompidos: z.array(z.string()).default([]),
  })).default([]),
  total_mensagens: z.number().default(0),
});

type Ponto = z.infer<typeof CheckpointSchema>['checkpoints'][number];

interface CheckpointSheetProps {
  sessionId: string;
  onClose: () => void;
}

export const CheckpointSheet: React.FC<CheckpointSheetProps> = ({ sessionId, onClose }) => {
  const [pontos, setPontos] = useState<Ponto[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState('');
  const [restaurando, setRestaurando] = useState<Ponto | null>(null);
  const loadSession = useChatStore(state => state.loadSession);

  const load = useCallback(async () => {
    const config = getRuntimeConfig();
    setCarregando(true);
    setErro('');
    try {
      const dados = CheckpointSchema.parse(await apiClient.get(
        `/sentury/sessions/${encodeURIComponent(sessionId)}/checkpoints?user_id=${encodeURIComponent(config.userId)}`,
        { headers: authHeaders() },
      ));
      setPontos(dados.checkpoints);
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : String(causa));
    } finally {
      setCarregando(false);
    }
  }, [sessionId]);

  useEffect(() => { void load(); }, [load]);

  const restaurar = async (ponto: Ponto) => {
    setRestaurando(null);
    try {
      await apiClient.post(
        `/sentury/sessions/${encodeURIComponent(sessionId)}/restaurar`,
        { user_id: getRuntimeConfig().userId, indice: ponto.indice },
        { headers: authHeaders() },
      );
      await loadSession(sessionId);
      onClose();
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : String(causa));
    }
  };

  return (
    <div className="fixed inset-0 z-[80] flex justify-end bg-black/25" onClick={onClose}>
      <aside
        onClick={event => event.stopPropagation()}
        className="flex w-[min(28rem,calc(100vw-3.5rem))] animate-[sentury-workbench-in_220ms_ease-out] flex-col border-l border-stone-200 bg-[#fffdf8] shadow-2xl"
      >
        <header className="flex items-center gap-3 border-b border-stone-200 px-5 py-4">
          <History className="h-4 w-4 text-gold-hover" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">Pontos da conversa</h2>
            <p className="text-[10px] text-zinc-500">Cada pergunta é um ponto ao qual dá para voltar.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1.5 text-zinc-400 hover:bg-stone-100" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="sentury-scroll flex-1 space-y-2 overflow-y-auto p-4">
          {erro ? <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">{erro}</p> : null}
          {pontos.map(ponto => (
            <article key={ponto.indice} className="rounded-xl border border-stone-200 bg-white/85 p-3">
              <p className="line-clamp-2 text-xs font-medium text-zinc-800">{ponto.texto || 'Turno sem texto'}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-zinc-500">
                <span>{ponto.passos} {ponto.passos === 1 ? 'passo' : 'passos'}</span>
                {!ponto.respondido ? (
                  <span className="inline-flex items-center gap-1 text-amber-700">
                    <TriangleAlert className="h-3 w-3" />sem resposta
                  </span>
                ) : null}
                {ponto.interrompidos.length ? (
                  <span className="inline-flex items-center gap-1 text-amber-700">
                    <TriangleAlert className="h-3 w-3" />parou em: {ponto.interrompidos.join(', ')}
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={() => setRestaurando(ponto)}
                  className="ml-auto inline-flex items-center gap-1 rounded-md border border-stone-300 px-2 py-1 font-medium text-zinc-600 hover:border-gold hover:text-gold-ink"
                >
                  <RotateCcw className="h-3 w-3" />Voltar aqui
                </button>
              </div>
            </article>
          ))}
          {!carregando && !pontos.length ? (
            <p className="rounded-xl border border-dashed border-stone-300 p-5 text-center text-xs text-zinc-500">
              Esta conversa ainda não tem pontos.
            </p>
          ) : null}
        </div>
      </aside>

      <ConfirmDialog
        open={restaurando !== null}
        destructive
        title="Voltar a conversa a este ponto?"
        description="Tudo que veio depois deste turno sai do histórico, no servidor também. Não dá para desfazer."
        confirmLabel="Voltar aqui"
        onCancel={() => setRestaurando(null)}
        onConfirm={() => { if (restaurando) void restaurar(restaurando); }}
      />
    </div>
  );
};
