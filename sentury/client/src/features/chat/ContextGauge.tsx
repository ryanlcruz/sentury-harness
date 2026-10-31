import React, { useMemo, useState } from 'react';
import { Gauge, Layers3, X } from 'lucide-react';
import { useHarnessStore } from '../../stores/harness-store';

const FATIAS = [
  { chave: 'sistema', rotulo: 'Sistema', cor: 'bg-gold' },
  { chave: 'ferramentas', rotulo: 'Ferramentas', cor: 'bg-zinc-500' },
  { chave: 'historico', rotulo: 'Histórico', cor: 'bg-stone-400' },
  { chave: 'pedido_e_contexto', rotulo: 'Pedido e contexto do turno', cor: 'bg-amber-200' },
] as const;

function ratio(used?: number, limit?: number): number | null {
  if (used == null || limit == null || limit <= 0) return null;
  return Math.max(0, Math.min(1, used / limit));
}

interface ContextGaugeProps {
  /** Quem controla a abertura e o composer: so uma superficie fica aberta. */
  aberto?: boolean;
  onAlternar?: (aberto: boolean) => void;
}

export const ContextGauge: React.FC<ContextGaugeProps> = ({ aberto, onAlternar }) => {
  const [interno, setInterno] = useState(false);
  const controlado = aberto !== undefined;
  const open = controlado ? aberto : interno;
  const setOpen = (valor: boolean | ((atual: boolean) => boolean)) => {
    const proximo = typeof valor === 'function' ? valor(open) : valor;
    if (controlado) onAlternar?.(proximo);
    else setInterno(proximo);
  };
  const telemetry = useHarnessStore(state => state.telemetry);
  const compacted = useHarnessStore(state => state.compacted);
  const compaction = useHarnessStore(state => state.compaction);
  const usage = ratio(telemetry?.context_chars, telemetry?.limit_chars);
  const percent = usage == null ? null : Math.round(usage * 100);
  const fatias = telemetry?.fatias ?? null;
  const totalFatias = fatias ? FATIAS.reduce((soma, f) => soma + (fatias[f.chave] || 0), 0) : 0;
  const entrada = telemetry?.tokens?.entrada ?? 0;
  const cacheado = telemetry?.tokens?.cacheado;
  const linhaDoCache = entrada > 0 && cacheado != null
    ? `Lido do cache: ${Math.round((cacheado / entrada) * 100)}% da entrada do turno.`
    : 'O provedor não informou o cache deste turno.';
  const ring = useMemo(() => ({
    background: usage == null
      ? 'conic-gradient(#d6d3d1 0 100%)'
      : `conic-gradient(var(--color-gold) 0 ${percent}%, #d6d3d1 ${percent}% 100%)`,
  }), [percent, usage]);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        className="relative flex h-8 w-8 items-center justify-center rounded-full text-zinc-700 hover:bg-stone-100"
        title={percent == null ? 'Contexto: aguardando telemetria real' : `Contexto usado: ${percent}%`}
        aria-expanded={open}
      >
        <span className="absolute inset-[5px] rounded-full" style={ring} />
        <span className="absolute inset-[7px] rounded-full bg-[#fffdf8]" />
        <Gauge className="relative h-3.5 w-3.5" />
      </button>

      {open && (
        <div className="absolute bottom-[calc(100%+10px)] right-0 w-72 rounded-xl border border-[#d8cfbd] bg-[#fffdf8] p-3.5 text-xs shadow-[0_18px_46px_rgba(22,22,22,.16)]">
          <div className="flex items-start gap-2">
            <Layers3 className="mt-0.5 h-4 w-4 text-gold-hover" />
            <div className="flex-1"><strong>Contexto da última resposta</strong><p className="mt-0.5 text-[10px] leading-4 text-zinc-500">Somente limites reportados pelo Harness; nenhum número é estimado pelo client.</p></div>
            <button type="button" onClick={() => setOpen(false)} className="rounded p-0.5 text-zinc-400 hover:bg-stone-100"><X className="h-3.5 w-3.5" /></button>
          </div>
          <dl className="mt-3 space-y-2 border-t border-stone-200 pt-3 text-[11px]">
            <div className="flex justify-between gap-3"><dt className="text-zinc-500">Caracteres</dt><dd className="font-mono">{telemetry?.context_chars != null && telemetry?.limit_chars != null ? `${telemetry.context_chars} / ${telemetry.limit_chars}` : 'não informado'}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-zinc-500">Mensagens</dt><dd className="font-mono">{telemetry?.context_messages != null && telemetry?.limit_messages != null ? `${telemetry.context_messages} / ${telemetry.limit_messages}` : 'não informado'}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-zinc-500">Tokens do turno</dt><dd className="font-mono">{telemetry?.tokens_used ?? 'não informado'}</dd></div>
            <div className="flex justify-between gap-3"><dt className="text-zinc-500">Compactação</dt><dd className={compacted ? 'font-semibold text-gold-ink' : ''}>{compacted ? 'executada' : telemetry?.context_status || 'não executada'}</dd></div>
          </dl>
          {fatias && totalFatias > 0 ? (
            <div className="mt-3 border-t border-stone-200 pt-3">
              <p className="text-[10px] font-semibold text-zinc-600">Composição da última chamada</p>
              <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-stone-200">
                {FATIAS.map(f => <span key={f.chave} className={f.cor} style={{ width: `${((fatias[f.chave] || 0) / totalFatias) * 100}%` }} />)}
              </div>
              <dl className="mt-2 space-y-1 text-[11px]">
                {FATIAS.map(f => <div key={f.chave} className="flex justify-between gap-3"><dt className="flex items-center gap-1.5 text-zinc-500"><span className={`h-2 w-2 rounded-full ${f.cor}`} />{f.rotulo}</dt><dd className="font-mono">{(fatias[f.chave] || 0).toLocaleString('pt-BR')} car.</dd></div>)}
              </dl>
              <p className="mt-2 text-[10px] leading-4 text-zinc-500">{linhaDoCache}</p>
            </div>
          ) : null}
          {compaction != null && <details className="mt-3 border-t border-stone-200 pt-2"><summary className="cursor-pointer text-[10px] font-semibold text-zinc-600">Detalhes reais da compactação</summary><pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap rounded bg-stone-100 p-2 text-[9px] text-zinc-600">{JSON.stringify(compaction, null, 2)}</pre></details>}
        </div>
      )}
    </div>
  );
};
