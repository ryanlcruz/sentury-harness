import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BellRing, Check, Clock3, Pause, Pencil, Play, RefreshCw, Trash2, X } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { Coruja } from '../residentes/Coruja';
import { coresDoAgente, useHQ } from '../residentes/useEsperando';
import { nomeVisivel, residentes } from '../residentes/api';

const JobSchema = z.object({
  id: z.string(), session_id: z.string(), origin_session_id: z.string().nullable().optional(),
  workflow: z.string().nullable().optional(), prompt: z.string(), kind: z.string(),
  residente: z.string().nullable().optional(),
  interval_sec: z.number().nullable().optional(), cron_expr: z.string().nullable().optional(),
  run_at: z.string().nullable().optional(),
  metric: z.string().nullable().optional(), op: z.string().nullable().optional(),
  threshold: z.number().nullable().optional(),
  active: z.boolean(), created_at: z.number(), last_run: z.number().nullable().optional(),
  run_count: z.number().default(0),
}).passthrough();

type Job = z.infer<typeof JobSchema>;

const DIAS = [
  { valor: '1', curto: 'Seg' }, { valor: '2', curto: 'Ter' },
  { valor: '3', curto: 'Qua' }, { valor: '4', curto: 'Qui' },
  { valor: '5', curto: 'Sex' }, { valor: '6', curto: 'Sáb' },
  { valor: '0', curto: 'Dom' },
];

function cronParts(expr?: string | null) {
  const [minuto = '0', hora = '9', dia = '*', mes = '*', semana = '*'] = (expr || '').trim().split(/\s+/);
  const horario = /^\d+$/.test(hora) && /^\d+$/.test(minuto)
    ? `${hora.padStart(2, '0')}:${minuto.padStart(2, '0')}` : '09:00';
  const dias = semana === '*' ? DIAS.map(d => d.valor) : semana.split(',').filter(Boolean);
  return { horario, dias, simples: dia === '*' && mes === '*' };
}

function cronFrom(horario: string, dias: string[]) {
  const [hora = '9', minuto = '0'] = horario.split(':');
  const semana = dias.length === 0 || dias.length === 7 ? '*' : dias.join(',');
  return `${Number(minuto)} ${Number(hora)} * * ${semana}`;
}

function resumoAgenda(job: Job) {
  if (job.kind === 'alert') return `Checa a cada ${job.interval_sec || 0}s · ${String(job.metric || '').toUpperCase()} ${job.op} ${job.threshold}`;
  if (job.kind === 'once') return `Uma vez em ${job.run_at ? new Date(job.run_at).toLocaleString() : 'horário não definido'}`;
  if (job.kind !== 'cron') return `A cada ${job.interval_sec || 0} segundos`;
  const partes = cronParts(job.cron_expr);
  const dias = partes.dias.length === 7
    ? 'todos os dias'
    : DIAS.filter(d => partes.dias.includes(d.valor)).map(d => d.curto).join(', ');
  return `${dias} às ${partes.horario}`;
}

function JobCard({ job, metricas, onChanged, onRemove, onResidente }: {
  metricas: Record<string, string>;
  job: Job; onChanged: (job: Job) => void; onRemove: (id: string) => void;
  onResidente?: (nome: string) => void;
}) {
  const hq = useHQ();
  const dono = hq.agentes.find(agente => agente.nome === job.residente);
  const inicial = useMemo(() => cronParts(job.cron_expr), [job.cron_expr]);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [prompt, setPrompt] = useState(job.prompt);
  const [kind, setKind] = useState(job.kind === 'alert' ? 'alert' : job.kind === 'interval' ? 'interval' : job.kind === 'once' ? 'once' : 'cron');
  const [horario, setHorario] = useState(inicial.horario);
  const [dias, setDias] = useState<string[]>(inicial.dias);
  const [cron, setCron] = useState(job.cron_expr || '0 9 * * *');
  const [intervalo, setIntervalo] = useState(Math.max(30, job.interval_sec || 1800));
  const [runAt, setRunAt] = useState(job.run_at ? job.run_at.slice(0, 16) : '');
  const [metric, setMetric] = useState(job.metric || Object.keys(metricas)[0] || '');
  const [op, setOp] = useState(job.op || '<');
  const [threshold, setThreshold] = useState(job.threshold ?? 0);
  const [error, setError] = useState('');

  const toggleDia = (dia: string) => {
    const proximos = dias.includes(dia) ? dias.filter(item => item !== dia) : [...dias, dia];
    setDias(proximos);
    setCron(cronFrom(horario, proximos));
  };
  const changeHorario = (valor: string) => {
    setHorario(valor);
    setCron(cronFrom(valor, dias));
  };
  const save = async () => {
    setSaving(true); setError('');
    try {
      if (job.residente) {
        const rota = `/sentury/residentes/${encodeURIComponent(job.residente)}/rotinas/${encodeURIComponent(job.id)}`;
        const rotina = await apiClient.patch(rota, { pedido: prompt,
          ...(kind === 'cron' ? { cron_expr: cron } : kind === 'once' ? { run_at: runAt } : { interval_sec: intervalo }) }, { headers: authHeaders() });
        onChanged(JobSchema.parse(rotina));
        setEditing(false);
        return;
      }
      const resposta = await apiClient.patch<{ job: Job }>(
        `/sentury/cron/${encodeURIComponent(job.id)}`,
        {
          prompt, kind, cron_expr: kind === 'cron' ? cron : null,
          interval_sec: kind === 'interval' || kind === 'alert' ? intervalo : null,
          run_at: kind === 'once' ? runAt : null,
          metric: kind === 'alert' ? metric : null,
          op: kind === 'alert' ? op : null,
          threshold: kind === 'alert' ? threshold : null,
        },
        { headers: authHeaders() },
      );
      onChanged(JobSchema.parse(resposta.job));
      setEditing(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setSaving(false); }
  };
  const toggleActive = async () => {
    setSaving(true); setError('');
    try {
      if (job.residente) {
        onChanged(JobSchema.parse(await residentes.mudarRotina(job.residente, job.id, !job.active)));
        return;
      }
      const resposta = await apiClient.post<{ job: Job }>(
        `/sentury/cron/${encodeURIComponent(job.id)}/${job.active ? 'pause' : 'activate'}`,
        {},
        { headers: authHeaders() },
      );
      onChanged(JobSchema.parse(resposta.job));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setSaving(false); }
  };

  return (
    <article className="rounded-xl border border-stone-200 bg-white/80 p-4">
      <div className="flex items-start gap-4">
        <span className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gold-soft text-gold-ink">
          {job.residente ? <Coruja tamanho={32} rotulo={job.residente} cores={coresDoAgente(dono)} acessorios={dono?.aparencia.acessorios} estado="parado" /> : <Clock3 className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {job.residente ? <button type="button" onClick={() => onResidente?.(job.residente!)} className="rounded bg-gold-soft px-2 py-1 text-xs font-semibold text-gold-ink">{nomeVisivel(job.residente)} · Abrir na HQ</button> : <span className="text-xs text-zinc-500">Sentury</span>}
            {job.workflow && <span className="rounded bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-700">workflow · {job.workflow}</span>}
            <span className="rounded bg-stone-100 px-2 py-0.5 text-[10px] text-zinc-500" title={job.session_id}>conversa {job.session_id.slice(0, 8)}</span>
            <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${job.active ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
              {job.active ? 'ativo' : job.residente ? 'pausado' : 'aguardando aprovação'}
            </span>
          </div>
          {!editing ? <>
            <h2 className="mt-2 text-sm font-semibold text-zinc-900">{job.prompt}</h2>
            <p className="mt-1 text-xs text-zinc-500">{resumoAgenda(job)} · {job.run_count} execuções{job.last_run ? ` · última ${new Date(job.last_run * 1000).toLocaleString()}` : ''}</p>
            {job.kind === 'cron' && <p className="mt-1 font-mono text-[10px] text-zinc-400">{job.cron_expr}</p>}
          </> : <div className="mt-3 space-y-3">
            <label className="block text-xs font-medium text-zinc-700">Prompt<textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={3} className="mt-1 w-full resize-y rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-normal outline-none focus:border-gold" /></label>
            {kind !== 'alert' ? <div className="flex gap-2">
              <button onClick={() => setKind('cron')} className={`rounded-lg px-3 py-1.5 text-xs ${kind === 'cron' ? 'bg-zinc-900 text-white' : 'border border-stone-300'}`}>Dias e horário</button>
              <button onClick={() => setKind('interval')} className={`rounded-lg px-3 py-1.5 text-xs ${kind === 'interval' ? 'bg-zinc-900 text-white' : 'border border-stone-300'}`}>Intervalo</button>
              <button onClick={() => setKind('once')} className={`rounded-lg px-3 py-1.5 text-xs ${kind === 'once' ? 'bg-zinc-900 text-white' : 'border border-stone-300'}`}>Uma vez</button>
            </div> : <p className="text-xs font-medium text-amber-700">Alerta por limiar</p>}
            {kind === 'cron' ? <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">{DIAS.map(dia => <button key={dia.valor} onClick={() => toggleDia(dia.valor)} className={`rounded-full px-2.5 py-1 text-[11px] ${dias.includes(dia.valor) ? 'bg-indigo-600 text-white' : 'border border-stone-300 text-zinc-600'}`}>{dia.curto}</button>)}</div>
              <label className="block text-xs text-zinc-600">Horário <input type="time" value={horario} onChange={e => changeHorario(e.target.value)} className="ml-2 rounded-md border border-stone-300 px-2 py-1" /></label>
              <label className="block text-[10px] text-zinc-500">Cron avançado <input value={cron} onChange={e => setCron(e.target.value)} className="ml-2 w-48 rounded-md border border-stone-300 px-2 py-1 font-mono" /></label>
            </div> : kind === 'once' ? <label className="block text-xs text-zinc-600">Executar em <input type="datetime-local" value={runAt} onChange={e => setRunAt(e.target.value)} className="ml-2 rounded-md border border-stone-300 px-2 py-1" /></label> : kind === 'alert' ? <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-600">
              <select value={metric} onChange={e => setMetric(e.target.value)} className="rounded-md border border-stone-300 px-2 py-1">{Object.entries({ ...(job.metric ? { [job.metric]: job.metric.toUpperCase() } : {}), ...metricas }).map(([valor, rotulo]) => <option key={valor} value={valor}>{rotulo}</option>)}</select>
              <select value={op} onChange={e => setOp(e.target.value)} className="rounded-md border border-stone-300 px-2 py-1"><option value="<">abaixo de</option><option value=">">acima de</option></select>
              <input type="number" value={threshold} onChange={e => setThreshold(Number(e.target.value))} className="w-24 rounded-md border border-stone-300 px-2 py-1" />
              <span>a cada</span><input type="number" min={30} value={intervalo} onChange={e => setIntervalo(Number(e.target.value))} className="w-24 rounded-md border border-stone-300 px-2 py-1" /><span>segundos</span>
            </div> : <label className="block text-xs text-zinc-600">A cada <input type="number" min={30} value={intervalo} onChange={e => setIntervalo(Number(e.target.value))} className="mx-2 w-28 rounded-md border border-stone-300 px-2 py-1" /> segundos</label>}
            {error && <p className="text-xs text-red-700">{error}</p>}
          </div>}
        </div>
        <div className="flex shrink-0 gap-1">
          {editing ? <>
            <button onClick={() => void save()} disabled={saving} className="rounded-md p-2 text-emerald-700 hover:bg-emerald-50" title="Salvar"><Check className="h-4 w-4" /></button>
            <button onClick={() => setEditing(false)} className="rounded-md p-2 text-zinc-500 hover:bg-stone-100" title="Cancelar"><X className="h-4 w-4" /></button>
          </> : <>
            <button onClick={() => void toggleActive()} disabled={saving} className="rounded-md p-2 text-zinc-500 hover:bg-stone-100" title={job.active ? 'Pausar' : 'Ativar'}>
              {job.active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </button>
            <button onClick={() => setEditing(true)} className="rounded-md p-2 text-zinc-500 hover:bg-stone-100" title="Editar"><Pencil className="h-4 w-4" /></button>
            <button onClick={() => onRemove(job.id)} className="rounded-md p-2 text-zinc-400 hover:bg-red-50 hover:text-red-700" title="Excluir agendamento"><Trash2 className="h-4 w-4" /></button>
          </>}
        </div>
      </div>
    </article>
  );
}

export const SchedulesView: React.FC<{ onResidente?: (nome: string) => void }> = ({ onResidente }) => {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [metricas, setMetricas] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filtro, setFiltro] = useState('todos');
  const load = useCallback(async () => {
    const config = getRuntimeConfig(); apiClient.setBaseUrl(config.apiUrl);
    setLoading(true); setError('');
    try {
      const resposta = await apiClient.get('/sentury/cron', { headers: authHeaders() });
      const lido = z.object({ jobs: z.array(JobSchema), metricas: z.record(z.string(), z.string()).default({}) }).parse(resposta);
      setJobs(lido.jobs);
      setMetricas(lido.metricas);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const remove = async (id: string) => {
    try {
      const job = jobs.find(item => item.id === id);
      if (job?.residente) await residentes.apagarRotina(job.residente, id);
      else await apiClient.delete(`/sentury/cron/${encodeURIComponent(id)}`, { headers: authHeaders() });
      setJobs(current => current.filter(job => job.id !== id));
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  };
  return <section className="h-full overflow-y-auto px-7 py-7"><div className="mx-auto max-w-6xl">
    <header className="flex items-start justify-between"><div>
      <p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Automação persistente</p>
      <h1 className="mt-2 text-2xl font-semibold">Agendamentos e alertas</h1>
      <p className="mt-1 text-sm text-zinc-500">Todas as rotinas. Cada execução volta para a conversa onde nasceu; se ela não existir mais, o Sentury cria uma nova.</p>
    </div><button onClick={() => void load()} className="rounded-lg border border-stone-300 bg-white p-2"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /></button></header>
    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    <label className="mt-5 block text-sm">Mostrar <select value={filtro} onChange={e => setFiltro(e.target.value)} className="ml-2 rounded-lg border bg-white p-2"><option value="todos">Todos</option><option value="sentury">Sentury</option><option value="residentes">Residentes</option></select></label>
    <div className="mt-6 space-y-3">{jobs.filter(job => filtro === 'todos' || (filtro === 'residentes' ? Boolean(job.residente) : !job.residente)).map(job => <JobCard key={job.id} job={job} metricas={metricas} onResidente={onResidente} onChanged={novo => setJobs(current => current.map(item => item.id === novo.id ? novo : item))} onRemove={id => void remove(id)} />)}</div>
    {!loading && !jobs.length && <div className="mt-8 rounded-2xl border border-dashed border-stone-300 p-8 text-center"><BellRing className="mx-auto h-8 w-8 animate-[sentury-bell_2.2s_ease-in-out_infinite] text-gold-hover" /><h2 className="mt-3 text-sm font-semibold">Nenhum agendamento ativo</h2><p className="mt-1 text-xs text-zinc-500">Peça um lembrete ou uma automação com dias e horário quando precisar.</p></div>}
  </div></section>;
};
