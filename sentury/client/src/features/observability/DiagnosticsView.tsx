import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { copiar } from '../../runtime/clipboard';
import { Check, Copy, Database, HeartPulse, Mic2, RefreshCw, Route, TriangleAlert } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { ArmazenamentoDaMemoria } from './ArmazenamentoDaMemoria';

const HealthSchema = z.object({ status: z.string(), app: z.string(), version: z.string() });
const StatusSchema = z.object({ llm_chain: z.array(z.string()), data_store: z.string(), session_store: z.string(), knowledge_base: z.string() });
const LiveSchema = z.object({ available: z.boolean(), has_key: z.boolean(), has_lib: z.boolean() });
const FlagsSchema = z.record(z.string(), z.unknown());

interface Snapshot {
  checkedAt: string;
  health: z.infer<typeof HealthSchema>;
  status: z.infer<typeof StatusSchema>;
  live: z.infer<typeof LiveSchema>;
  flags: z.infer<typeof FlagsSchema>;
}

export const DiagnosticsView: React.FC = () => {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [rodada, setRodada] = useState(0);
  const load = useCallback(async () => {
    const config = getRuntimeConfig(); apiClient.setBaseUrl(config.apiUrl); setLoading(true); setError(''); setRodada(n => n + 1);
    try {
      const [health, status, live, flags] = await Promise.all([
        apiClient.get('/health'), apiClient.get('/sentury/status', { headers: authHeaders() }),
        apiClient.get('/sentury/live/status', { headers: authHeaders() }), apiClient.get('/sentury/flags', { headers: authHeaders() }),
      ]);
      setSnapshot({ checkedAt: new Date().toISOString(), health: HealthSchema.parse(health), status: StatusSchema.parse(status), live: LiveSchema.parse(live), flags: FlagsSchema.parse(flags) });
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const raw = useMemo(() => JSON.stringify(snapshot, null, 2), [snapshot]);
  const copy = async () => { setCopied(await copiar(raw)); window.setTimeout(() => setCopied(false), 1500); };
  const checks = snapshot ? [
    { label: 'API', detail: `${snapshot.health.app} ${snapshot.health.version}`, ok: snapshot.health.status === 'ok', Icon: HeartPulse },
    { label: 'Router', detail: `${snapshot.status.llm_chain.length} etapas declaradas`, ok: snapshot.status.llm_chain.length > 0, Icon: Route },
    { label: 'Sessões', detail: snapshot.status.session_store, ok: Boolean(snapshot.status.session_store), Icon: Database },
    { label: 'Voz ao vivo', detail: snapshot.live.available ? 'Disponível' : 'Indisponível', ok: snapshot.live.available, Icon: Mic2 },
  ] : [];

  return <section className="h-full overflow-y-auto px-7 py-7"><div className="mx-auto max-w-6xl">
    <header className="flex items-start justify-between gap-4"><div><p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Estado da instalação</p><h1 className="mt-2 text-2xl font-semibold">Diagnósticos</h1><p className="mt-1 text-sm text-zinc-500">Verificações reais do runtime, armazenamento, Router e voz — sem resultados sintéticos.</p></div><button type="button" onClick={() => void load()} className="inline-flex items-center gap-2 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs"><RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />Verificar</button></header>
    {error && <p className="mt-5 flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"><TriangleAlert className="h-4 w-4" />{error}</p>}
    <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{checks.map(({ label, detail, ok, Icon }) => <article key={label} className="rounded-xl border border-stone-200 bg-white/80 p-4"><div className="flex items-center justify-between"><Icon className="h-4 w-4 text-gold-hover" /><span className={`h-2 w-2 rounded-full ${ok ? 'bg-emerald-500' : 'bg-red-500'}`} /></div><strong className="mt-3 block text-sm">{label}</strong><span className="mt-1 block text-xs text-zinc-500">{detail}</span></article>)}</div>
    {snapshot && <div className="mt-7 grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]"><section className="rounded-2xl border border-stone-200 bg-white/80 p-5"><h2 className="text-sm font-semibold">Cadeia ativa</h2><ol className="mt-4 space-y-2">{snapshot.status.llm_chain.map((provider, index) => <li key={`${provider}-${index}`} className="flex items-center gap-3 text-xs"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-stone-100 font-mono text-[10px]">{index + 1}</span><span>{provider}</span></li>)}</ol><dl className="mt-5 space-y-2 border-t border-stone-200 pt-4 text-xs"><div className="flex justify-between"><dt className="text-zinc-500">Dados</dt><dd>{snapshot.status.data_store}</dd></div><div className="flex justify-between"><dt className="text-zinc-500">Memória de sessão</dt><dd>{snapshot.status.session_store}</dd></div><div className="flex justify-between"><dt className="text-zinc-500">Knowledge base</dt><dd>{snapshot.status.knowledge_base}</dd></div></dl></section><section className="overflow-hidden rounded-2xl border border-zinc-800 bg-[#121820] text-zinc-300"><header className="flex items-center justify-between border-b border-zinc-800 px-4 py-3"><div><h2 className="text-xs font-semibold text-zinc-100">Snapshot completo</h2><time className="text-[9px] text-zinc-500">{new Date(snapshot.checkedAt).toLocaleString()}</time></div><button type="button" onClick={() => void copy()} className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2 py-1 text-[10px]">{copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}{copied ? 'Copiado' : 'Copiar JSON'}</button></header><pre className="max-h-[34rem] overflow-auto whitespace-pre-wrap p-4 text-[9px] leading-5 text-emerald-400">{raw}</pre></section></div>}
    <ArmazenamentoDaMemoria recarregar={rodada} />
  </div></section>;
};
