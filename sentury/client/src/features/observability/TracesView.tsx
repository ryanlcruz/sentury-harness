import React, { useCallback, useEffect, useState } from 'react';
import { Activity, BrainCircuit, ChevronDown, Clock3, RefreshCw, ShieldCheck, Wrench } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const TraceSchema = z.object({
  id: z.string(), ts: z.number(), session_id: z.string(), mode: z.string().default('router'), intent: z.string().nullable().optional(), complexity: z.string().nullable().optional(),
  input: z.string().default(''), output: z.string().default(''), total_ms: z.number().nullable().optional(),
  harness: z.object({ proposed_tool: z.string().nullable().optional(), allowed: z.boolean().nullable().optional(), reason: z.string().default('') }).passthrough(),
  generations: z.array(z.object({ name: z.string(), model: z.string(), ms: z.number().nullable().optional(), reasoning: z.string().default('') }).passthrough()).default([]),
  spans: z.array(z.object({ tool: z.string().nullable().optional(), observation: z.string().default('') }).passthrough()).default([]),
}).passthrough();
const InterventionsSchema = z.object({ interventions: z.object({ total: z.number().default(0), by_kind: z.record(z.string(), z.number()).default({}), recent: z.array(z.record(z.string(), z.unknown())).default([]) }).passthrough(), latencia_por_etapa: z.record(z.string(), z.object({ media_ms: z.number(), amostras: z.number() })).default({}) });

export const TracesView: React.FC = () => {
  const [traces, setTraces] = useState<z.infer<typeof TraceSchema>[]>([]);
  const [interventions, setInterventions] = useState<z.infer<typeof InterventionsSchema> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    const config = getRuntimeConfig(); apiClient.setBaseUrl(config.apiUrl); setLoading(true); setError('');
    try {
      const [traceResult, interventionResult] = await Promise.all([
        apiClient.get('/sentury/traces?limit=50', { headers: authHeaders() }),
        apiClient.get('/sentury/interventions', { headers: authHeaders() }),
      ]);
      setTraces(z.object({ traces: z.array(TraceSchema) }).parse(traceResult).traces);
      setInterventions(InterventionsSchema.parse(interventionResult));
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  return <section className="h-full overflow-y-auto px-7 py-7"><div className="mx-auto max-w-6xl">
    <header className="flex items-start justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Observabilidade local</p><h1 className="mt-2 text-2xl font-semibold">Traces e intervenções</h1><p className="mt-1 text-sm text-zinc-500">Turnos, gerações, ferramentas, latência e correções feitas pelo Harness.</p></div><button type="button" onClick={() => void load()} className="rounded-lg border border-stone-300 bg-white p-2"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /></button></header>
    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    <div className="mt-6 grid gap-3 sm:grid-cols-3"><article className="rounded-xl border border-stone-200 bg-white/80 p-4"><Activity className="h-4 w-4 text-gold-hover" /><p className="mt-2 text-2xl font-semibold">{traces.length}</p><p className="text-xs text-zinc-500">traces no processo atual</p></article><article className="rounded-xl border border-stone-200 bg-white/80 p-4"><ShieldCheck className="h-4 w-4 text-gold-hover" /><p className="mt-2 text-2xl font-semibold">{interventions?.interventions.total ?? 0}</p><p className="text-xs text-zinc-500">intervenções do Harness</p></article><article className="rounded-xl border border-stone-200 bg-white/80 p-4"><Clock3 className="h-4 w-4 text-gold-hover" /><p className="mt-2 text-2xl font-semibold">{Object.keys(interventions?.latencia_por_etapa || {}).length}</p><p className="text-xs text-zinc-500">etapas com latência medida</p></article></div>
    <div className="mt-7 space-y-3">{traces.map(trace => <details key={trace.id} className="group rounded-xl border border-stone-200 bg-white/80"><summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3"><BrainCircuit className="h-4 w-4 text-gold-hover" /><span className="min-w-0 flex-1"><strong className="block truncate text-sm">{trace.input || 'Turno sem entrada registrada'}</strong><span className="text-[10px] text-zinc-500">{new Date(trace.ts * 1000).toLocaleString()} · {trace.mode} · {trace.intent || 'sem intent'} · {trace.complexity || 'sem complexidade'}</span></span>{trace.total_ms != null && <span className="text-xs tabular-nums text-zinc-500">{trace.total_ms} ms</span>}<ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" /></summary><div className="grid gap-5 border-t border-stone-200 px-4 py-4 lg:grid-cols-2"><div><h3 className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">Gerações</h3><div className="mt-2 space-y-2">{trace.generations.map((generation, index) => <div key={`${generation.name}-${index}`} className="rounded-lg bg-stone-100 p-3 text-xs"><div className="flex justify-between"><strong>{generation.name}</strong><span>{generation.model} {generation.ms != null ? `· ${generation.ms} ms` : ''}</span></div>{generation.reasoning && <p className="mt-2 leading-5 text-zinc-500">{generation.reasoning}</p>}</div>)}</div></div><div><h3 className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">Ferramentas e Harness</h3><p className="mt-2 text-xs leading-5 text-zinc-600">{trace.harness.reason || 'Sem intervenção registrada.'}</p><div className="mt-2 space-y-2">{trace.spans.map((span, index) => <div key={`${span.tool}-${index}`} className="flex gap-2 rounded-lg border border-stone-200 p-3 text-xs"><Wrench className="mt-0.5 h-3.5 w-3.5 text-zinc-400" /><span><strong>{span.tool || 'ferramenta'}</strong>{span.observation && <span className="mt-1 block leading-5 text-zinc-500">{span.observation}</span>}</span></div>)}</div></div></div></details>)}</div>
    {!loading && !traces.length && <p className="mt-7 rounded-xl border border-dashed border-stone-300 p-6 text-sm text-zinc-500">Nenhum trace neste processo. Execute um turno e atualize para ver a linha do tempo real.</p>}
  </div></section>;
};
