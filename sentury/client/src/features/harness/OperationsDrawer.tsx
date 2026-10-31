import React, { useMemo, useState } from 'react';
import { ResizeHandle } from '../../components/ResizeHandle';
import { copiar } from '../../runtime/clipboard';
import { useHarnessStore } from '../../stores/harness-store';
import { X, ShieldCheck, CheckCircle2, Copy, Check } from 'lucide-react';

export const OperationsDrawer: React.FC = () => {
  const [largura, setLarguraBruta] = useState<number>(() => {
    const salvo = Number(localStorage.getItem('sentury_harness_w'));
    return Number.isFinite(salvo) && salvo >= 320 ? salvo : 448;
  });
  const setLargura = (v: number) => {
    setLarguraBruta(v);
    try { localStorage.setItem('sentury_harness_w', String(v)); } catch { /* modo privado */ }
  };

  const {
    isDrawerOpen,
    setDrawerOpen,
    activeTab,
    setActiveTab,
    status,
    model,
    proposed_tool,
    harness_allowed,
    harness_reason,
    events,
    telemetry,
    rawState,
    compacted,
    compaction,
  } = useHarnessStore();
  const [copied, setCopied] = useState(false);
  const rawOutput = useMemo(() => JSON.stringify({
    status,
    model,
    proposed_tool,
    harness_allowed,
    harness_reason,
    events,
    telemetry,
    state: rawState,
    compacted,
    compactacao: compaction,
  }, null, 2), [status, model, proposed_tool, harness_allowed, harness_reason, events, telemetry, rawState, compacted, compaction]);

  const copyRawOutput = async () => {
    setCopied(await copiar(rawOutput));
    window.setTimeout(() => setCopied(false), 1500);
  };

  if (!isDrawerOpen) return null;

  return (
    <aside className="fixed inset-y-0 right-0 z-[60] flex animate-[sentury-workbench-in_220ms_ease-out] flex-col border-l border-zinc-800 bg-[#121820] text-zinc-300 shadow-2xl"
      style={{ width: `min(${largura}px, calc(100vw - 3.5rem))` }}>
      <ResizeHandle width={largura} onResize={setLargura} min={320} />
      {/* Header */}
      <div className="h-14 px-4 flex items-center justify-between border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2 text-zinc-100 font-semibold text-sm">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span>Debug Operacional</span>
        </div>
        <button
          onClick={() => setDrawerOpen(false)}
          className="p-1 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
          title="Fechar painel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-zinc-800 bg-[#0d1217]">
        <button
          onClick={() => setActiveTab('operations')}
          className={`flex-1 py-2.5 text-xs font-medium text-center border-b-2 transition-colors ${
            activeTab === 'operations'
              ? 'border-gold text-gold bg-zinc-800/30'
              : 'border-transparent text-zinc-400 hover:text-zinc-200'
          }`}
        >
          Operações
        </button>
        <button
          onClick={() => setActiveTab('diagnostics')}
          className={`flex-1 py-2.5 text-xs font-medium text-center border-b-2 transition-colors ${
            activeTab === 'diagnostics'
              ? 'border-gold text-gold bg-zinc-800/30'
              : 'border-transparent text-zinc-400 hover:text-zinc-200'
          }`}
        >
          Diagnósticos
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5 text-xs">
        {/* Status Row */}
        <div className="flex items-center justify-between p-3 rounded-lg bg-zinc-900/80 border border-zinc-800">
          <span className="text-zinc-400">Status do Harness:</span>
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            {status.toUpperCase()}
          </span>
        </div>

        {activeTab === 'operations' ? (
          <>
            {/* Decisão Operacional */}
            <div className="space-y-2">
              <span className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider">Decisão da Policy</span>
              <div className="p-3 rounded-lg bg-zinc-900/60 border border-zinc-800/80 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400">Ferramenta proposta:</span>
                  <span className="text-zinc-200 font-semibold">{proposed_tool || 'Nenhuma neste turno'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400">Autorização:</span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/40">
                    {harness_allowed == null ? 'SEM DECISÃO' : harness_allowed ? 'PERMITIDO' : 'BLOQUEADO'}
                  </span>
                </div>
                <p className="text-[11px] text-zinc-400 pt-1 border-t border-zinc-800/50">
                  {harness_reason || 'Envie uma mensagem para ver a decisão real da policy.'}
                </p>
              </div>
            </div>

            {/* Pipeline de Execução */}
            <div className="space-y-2">
              <span className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider">Pipeline de Ferramentas</span>
              <div className="space-y-1.5">
                {(events || []).map((evt, idx) => (
                  <div key={idx} className="p-2.5 rounded-lg bg-zinc-900/40 border border-zinc-800/60 flex items-start gap-2">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                    <div className="flex-1 font-mono text-[11px] text-zinc-300">
                      <div className="font-semibold text-zinc-200">{evt.tool || evt.stage}</div>
                      {evt.duration_ms && <div className="text-[10px] text-zinc-500">{evt.duration_ms}ms decorridos</div>}
                      {evt.provider && <div className="text-[10px] text-zinc-500">{evt.provider} (score: {evt.score})</div>}
                    </div>
                  </div>
                ))}
                {!events?.length && <p className="text-zinc-500">Nenhum evento real registrado neste turno.</p>}
              </div>
            </div>

            {/* Telemetria e Contexto */}
            <div className="space-y-2">
              <span className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider">Telemetria do Turno</span>
              <div className="p-3 rounded-lg bg-zinc-900/60 border border-zinc-800/80 space-y-2 font-mono text-[11px]">
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400 font-sans">Provedor:</span>
                  <span className="text-zinc-200">{telemetry?.provider || '—'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400 font-sans">Latência Total:</span>
                  <span className="text-zinc-200">{telemetry?.execution_ms != null ? `${telemetry.execution_ms}ms` : '—'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400 font-sans">Tokens Utilizados:</span>
                  <span className="text-zinc-200">{telemetry?.tokens_used != null ? `${telemetry.tokens_used} tokens` : '—'}</span>
                </div>
                  <div className="pt-2 border-t border-zinc-800/50">
                    <div className="flex items-center justify-between text-[10px] mb-1 text-zinc-400">
                    <span>Contexto real:</span>
                    <span>{telemetry?.context_chars != null && telemetry?.limit_chars ? `${telemetry.context_chars}/${telemetry.limit_chars} chars` : 'Sem dado'}</span>
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                    <div className="h-full rounded-full bg-gold transition-[width] duration-500" style={{ width: `${telemetry?.context_chars != null && telemetry?.limit_chars ? Math.min(100, (telemetry.context_chars / telemetry.limit_chars) * 100) : 0}%` }} />
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[10px] text-zinc-500"><span>{telemetry?.context_messages != null && telemetry?.limit_messages ? `${telemetry.context_messages}/${telemetry.limit_messages} mensagens` : 'Limite de mensagens indisponível'}</span><span>{compacted ? 'Compactado neste turno' : telemetry?.context_status || '—'}</span></div>
                </div>
              </div>
            </div>
          </>
        ) : (
          /* Diagnósticos Avançados */
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3"><span className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider">Saída completa do Harness</span><button type="button" onClick={() => void copyRawOutput()} className="inline-flex items-center gap-1.5 rounded-md border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:bg-zinc-800">{copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}{copied ? 'Copiado' : 'Copiar JSON'}</button></div>
            <pre className="p-3 rounded-lg bg-black/60 border border-zinc-800 text-[10px] font-mono text-emerald-400 overflow-x-auto whitespace-pre-wrap">
              {rawOutput}
            </pre>
          </div>
        )}
      </div>
    </aside>
  );
};
