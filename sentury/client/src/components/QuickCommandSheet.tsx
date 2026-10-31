import React, { useEffect, useState } from 'react';
import { GraduationCap, RefreshCw, Sparkles, Wrench, X } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../runtime/config';
import { useHarnessStore } from '../stores/harness-store';
import { apiClient } from '../transport/http-client';
import { setProcessTraceEnabled, useProcessTraceEnabled } from '../runtime/preferences';

const FlagsSchema = z.object({
  native_tools: z.boolean(),
  autolearn: z.boolean(),
  gemini_embeddings: z.boolean(),
  fastembed_embeddings: z.boolean(),
  knowledge_mode: z.string().optional(),
}).passthrough();

type Flags = z.infer<typeof FlagsSchema>;

interface QuickCommandSheetProps {
  isOpen: boolean;
  onClose: () => void;
}

export const QuickCommandSheet: React.FC<QuickCommandSheetProps> = ({ isOpen, onClose }) => {
  const [flags, setFlags] = useState<Flags | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const model = useHarnessStore(state => state.model);
  const processTraceEnabled = useProcessTraceEnabled();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) return;
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setError(null);
    void apiClient.get<unknown>('/sentury/flags', { headers: authHeaders() })
      .then(value => setFlags(FlagsSchema.parse(value)))
      .catch(value => {
        setFlags(null);
        setError(value instanceof Error ? value.message : String(value));
      });
  }, [isOpen]);

  const updateFlag = async (name: keyof Flags, value: boolean) => {
    if (!flags) return;
    const previous = flags;
    setFlags({ ...flags, [name]: value });
    setIsSaving(true);
    setError(null);
    try {
      const updated = await apiClient.post<unknown>(
        '/sentury/flags',
        { [name]: value },
        { headers: authHeaders() },
      );
      setFlags(FlagsSchema.parse(updated));
    } catch (reason) {
      setFlags(previous);
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsSaving(false);
    }
  };

  if (!isOpen) return null;

  const controls = [
    {
      key: 'native_tools' as const,
      title: 'Tools nativas',
      description: 'Usa function calling nativo quando o provider oferece suporte.',
      icon: Wrench,
      color: 'text-emerald-400',
    },
    {
      key: 'autolearn' as const,
      title: 'Aprendizado pós-chat',
      description: 'Revisa conversas concluídas para propor aprendizados reutilizáveis.',
      icon: GraduationCap,
      color: 'text-gold',
    },
  ];

  return (
    <>
      <button type="button" className="pointer-events-auto fixed inset-0 cursor-default bg-transparent" onClick={onClose} aria-label="Fechar configuração rápida" />
      <div className="pointer-events-auto absolute inset-x-0 bottom-[calc(100%+10px)] z-10 flex max-h-[min(60vh,32rem)] animate-[sentury-sheet-up_180ms_ease-out] flex-col overflow-hidden rounded-2xl border border-zinc-700 bg-[#1a1a1e] text-zinc-200 shadow-2xl">
        <div className="flex items-center gap-3 border-b border-zinc-800 p-3.5">
          <Sparkles className="h-4 w-4 text-gold" />
          <div className="flex-1"><p className="text-sm font-semibold">Configuração rápida</p><p className="text-[10px] text-zinc-500">Ajustes do motor para esta instalação</p></div>
          <kbd className="rounded border border-zinc-700 bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">ESC</kbd>
          <button onClick={onClose} className="p-1 text-zinc-400 transition-colors hover:text-white" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="sentury-dark-scroll min-h-0 flex-1 space-y-3 overflow-y-auto border-b border-zinc-800/80 bg-[#161619] p-4">
          <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-400">Motor do Sentury</span>
          <label className="flex cursor-pointer items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/60 p-2.5 transition-colors hover:border-zinc-700">
            <div className="flex items-center gap-2.5">
              <Sparkles className="h-4 w-4 text-gold" />
              <div><div className="text-xs font-semibold text-zinc-200">Mostrar processo analítico</div><div className="text-[11px] text-zinc-400">Exibe a narração discreta e as etapas reais de cada resposta.</div></div>
            </div>
            <input type="checkbox" checked={processTraceEnabled} onChange={event => setProcessTraceEnabled(event.target.checked)} className="h-4 w-4 cursor-pointer accent-gold" />
          </label>
          {error && <p className="rounded-lg border border-red-500/30 bg-red-500/10 p-2.5 text-[11px] leading-4 text-red-300">Flags indisponíveis: {error}</p>}
          {!flags && !error && <p className="text-xs text-zinc-500">Carregando configuração real…</p>}
          {flags && controls.map(item => {
            const Icon = item.icon;
            return (
              <label key={item.key} className="flex cursor-pointer items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/60 p-2.5 transition-colors hover:border-zinc-700">
                <div className="flex items-center gap-2.5">
                  <Icon className={'h-4 w-4 ' + item.color} />
                  <div>
                    <div className="text-xs font-semibold text-zinc-200">{item.title}</div>
                    <div className="text-[11px] text-zinc-400">{item.description}</div>
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={Boolean(flags[item.key])}
                  disabled={isSaving}
                  onChange={event => void updateFlag(item.key, event.target.checked)}
                  className="h-4 w-4 cursor-pointer accent-gold"
                />
              </label>
            );
          })}
        </div>

        <div className="flex items-center justify-between bg-[#121214] p-3 text-[11px] text-zinc-500">
          <span>{model ? <>Modelo do último turno: <strong className="text-zinc-300">{model}</strong></> : 'Nenhum turno executado nesta sessão.'}{flags?.knowledge_mode ? <> · Contexto: <strong className="text-zinc-300">{flags.knowledge_mode}</strong></> : null}</span>
          {isSaving && <span className="flex items-center gap-1"><RefreshCw className="h-3 w-3 animate-spin" /> Salvando</span>}
        </div>
      </div>
    </>
  );
};
