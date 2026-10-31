import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, Coins, RefreshCw, RotateCcw, Timer, TriangleAlert } from 'lucide-react';
import { z } from 'zod';
import { ProviderLogo } from '../../components/ProviderLogo';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const UsageProviderSchema = z.object({
  key: z.string(), label: z.string(), estado: z.string(), configured: z.boolean().default(false),
  ok: z.number().default(0), err: z.number().default(0), latency_ms: z.number().nullable().optional(),
  last_model: z.string().nullable().optional(), cooldown: z.number().default(0), rpm_used: z.number().default(0),
  rpm_remaining: z.number().nullable().optional(), rpd_remaining: z.number().nullable().optional(),
}).passthrough();
// Os nomes vêm do RobinBandit, que é o dono do dado de credencial — aqui só
// se mostra o que ele produz. `sem_medicao` não é "sem saldo": é provedor que
// não publica saldo, e a tela precisa dizer as duas coisas de formas diferentes.
const BalanceSchema = z.object({
  rotulo: z.string(), variavel: z.string().default(''), indice: z.number(), status: z.string(),
  usado: z.number().nullable().optional(), limite: z.number().nullable().optional(),
  saldo: z.number().nullable().optional(), detalhe: z.string().optional(),
}).passthrough();
const ResponseSchema = z.object({
  providers: z.array(UsageProviderSchema).default([]),
  ultra_info: UsageProviderSchema.nullable().optional(),
  openrouter_balances: z.array(BalanceSchema).default([]),
}).passthrough();
type UsageProvider = z.infer<typeof UsageProviderSchema>;

export const UsageView: React.FC = () => {
  const [providers, setProviders] = useState<UsageProvider[]>([]);
  const [balances, setBalances] = useState<z.infer<typeof BalanceSchema>[]>([]);
  const [ultra, setUltra] = useState<UsageProvider | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setLoading(true); setError('');
    try {
      const result = ResponseSchema.parse(await apiClient.get('/sentury/providers', { headers: authHeaders() }));
      setProviders(result.providers); setBalances(result.openrouter_balances); setUltra(result.ultra_info || null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const all = useMemo(() => ultra ? [ultra, ...providers] : providers, [providers, ultra]);
  const ok = all.reduce((sum, provider) => sum + provider.ok, 0);
  const failures = all.reduce((sum, provider) => sum + provider.err, 0);
  const calls = ok + failures;
  const usedProviders = all.filter(provider => provider.ok + provider.err > 0).length;
  const tiles: Array<{ label: string; value: React.ReactNode; Icon: React.ComponentType<{ className?: string }> }> = [
    { label: 'Chamadas de IA', value: calls, Icon: Activity },
    { label: 'Taxa de sucesso', value: calls ? `${Math.round(ok / calls * 100)}%` : '—', Icon: RotateCcw },
    { label: 'Provedores usados', value: usedProviders, Icon: Coins },
    { label: 'Falhas / fallbacks', value: failures, Icon: TriangleAlert },
  ];

  return <section className="h-full overflow-y-auto px-7 py-7"><div className="mx-auto max-w-6xl">
    <header className="flex items-start justify-between gap-4"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Uso real do Router</p><h1 className="mt-2 text-2xl font-semibold">Uso, limites e créditos</h1><p className="mt-1 text-sm text-zinc-500">Chamadas, fallbacks, RPM, latência e saldos informados pelo runtime.</p></div><button type="button" onClick={() => void load()} className="inline-flex items-center gap-2 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-medium"><RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />Atualizar</button></header>
    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Não foi possível ler o consumo: {error}</p>}
    <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map(({ label, value, Icon }) => <article key={label} className="rounded-xl border border-stone-200 bg-white/80 p-4"><Icon className="h-4 w-4 text-gold-hover" /><p className="mt-3 text-2xl font-semibold">{value}</p><p className="text-xs text-zinc-500">{label}</p></article>)}
    </div>
    <section className="mt-8"><h2 className="text-sm font-semibold">Cadeia de provedores</h2><div className="mt-3 overflow-x-auto rounded-xl border border-stone-200 bg-white/80"><table className="w-full text-left text-xs"><thead className="border-b border-stone-200 bg-stone-100/70 text-zinc-500"><tr><th className="px-4 py-3">Provedor</th><th>Chamadas</th><th>Falhas</th><th>Latência</th><th>RPM / limite</th><th>Último modelo</th></tr></thead><tbody className="divide-y divide-stone-200">{all.map(provider => <tr key={provider.key}><td className="px-4 py-3"><span className="flex items-center gap-2"><ProviderLogo providerKey={provider.key} label={provider.label} className="h-7 w-7" /><strong>{provider.label}</strong></span></td><td>{provider.ok}</td><td className={provider.err ? 'text-red-700' : ''}>{provider.err}</td><td>{provider.latency_ms != null ? `${Math.round(provider.latency_ms)} ms` : '—'}</td><td>{provider.cooldown > 0 ? `Cooldown ${provider.cooldown}s` : provider.rpm_remaining != null ? `${provider.rpm_remaining} restante` : provider.rpm_used ? `${provider.rpm_used} usado` : provider.estado}</td><td className="max-w-56 truncate pr-4">{provider.last_model || '—'}</td></tr>)}</tbody></table>{!loading && !all.length && <p className="p-5 text-sm text-zinc-500">Nenhum provedor retornado.</p>}</div></section>
    <section className="mt-8"><h2 className="flex items-center gap-2 text-sm font-semibold"><Coins className="h-4 w-4 text-gold-hover" />Créditos, consumo e saldo por credencial</h2><p className="mt-1 text-xs text-zinc-500">O backend consulta o saldo sem devolver qualquer fragmento do segredo.</p><div className="mt-3 overflow-x-auto rounded-xl border border-stone-200 bg-white/80"><table className="w-full text-left text-xs"><thead className="border-b border-stone-200 bg-stone-100/70 text-zinc-500"><tr><th className="px-4 py-3">Origem</th><th>Credencial</th><th>Consumo</th><th>Saldo / cota</th></tr></thead><tbody className="divide-y divide-stone-200">{balances.map(balance => <tr key={`${balance.rotulo}-${balance.indice}`}><td className="px-4 py-3 font-semibold">{balance.rotulo}</td><td className="text-[10px] font-mono text-zinc-500">{balance.variavel || `Configurada #${balance.indice + 1}`}</td><td>{balance.status === 'sem_medicao' ? 'Não informa' : balance.usado != null ? `$${balance.usado.toFixed(4)}` : '—'}</td><td className="pr-4">{balance.status === 'error' ? <span className="text-red-700">{balance.detalhe || 'Erro ao consultar'}</span> : balance.saldo != null ? `$${balance.saldo.toFixed(4)}` : balance.limite != null ? `$${balance.limite.toFixed(4)}` : 'Provedor não publica saldo'}</td></tr>)}</tbody></table>{!loading && !balances.length && <p className="p-5 text-sm text-zinc-500">Nenhuma credencial com saldo reportado pelo backend.</p>}</div></section>
    {loading && <p className="mt-5 flex items-center gap-2 text-xs text-zinc-500"><Timer className="h-3.5 w-3.5 animate-pulse" />Consultando métricas e créditos reais…</p>}
  </div></section>;
};
