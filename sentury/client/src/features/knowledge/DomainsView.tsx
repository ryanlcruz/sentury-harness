import React, { useCallback, useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, BriefcaseBusiness, RefreshCw } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const DomainSchema = z.object({
  nome: z.string(), ativo: z.boolean(), total_metricas: z.number(),
  metricas: z.array(z.object({
    nome: z.string(), label: z.string(), unidade: z.string().default(''), fonte: z.string().default(''),
    descricao: z.string().default(''), maior_melhor: z.boolean().nullable().optional(), grupo: z.string(),
  })).default([]),
});
const ResponseSchema = z.object({ ativo: z.string(), generalista: z.string().default('generalista'), setores: z.array(DomainSchema) });

/** Sigla curta vira maiúscula (cx → CX); nome comum ganha só a inicial. */
function nomeDoSetor(nome: string): string {
  return nome.length <= 3 ? nome.toUpperCase() : nome.charAt(0).toUpperCase() + nome.slice(1);
}

export const DomainsView: React.FC = () => {
  const [active, setActive] = useState('');
  const [domains, setDomains] = useState<z.infer<typeof DomainSchema>[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [trocando, setTrocando] = useState('');
  const load = useCallback(async () => {
    const config = getRuntimeConfig(); apiClient.setBaseUrl(config.apiUrl); setLoading(true); setError('');
    try { const result = ResponseSchema.parse(await apiClient.get('/sentury/domains', { headers: authHeaders() })); setActive(result.ativo); setDomains(result.setores); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const ligar = useCallback(async (nome: string) => {
    setTrocando(nome); setError('');
    try {
      await apiClient.put('/sentury/domains/ativo', { setor: nome }, { headers: authHeaders() });
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setTrocando(''); }
  }, [load]);

  return <section className="h-full overflow-y-auto px-7 py-7"><div className="mx-auto max-w-6xl">
    <header className="flex items-start justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Contexto de negócio</p><h1 className="mt-2 text-2xl font-semibold">Setores e métricas</h1><p className="mt-1 text-sm text-zinc-500">O setor ativo muda métricas, direção de qualidade e comportamento analítico. No generalista, o motor é o mesmo e nada do setor entra.</p></div><button type="button" onClick={() => void load()} className="rounded-lg border border-stone-300 bg-white p-2" title="Atualizar setores"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /></button></header>
    <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-gold/50 bg-gold-soft px-3 py-1.5 text-xs font-semibold text-gold-ink"><BriefcaseBusiness className="h-3.5 w-3.5" />Padrão ativo: {active || 'consultando…'}</div>
    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Não foi possível consultar os setores: {error}</p>}
    <div className="mt-6 space-y-5">{domains.map(domain => <article key={domain.nome} className={`overflow-hidden rounded-2xl border bg-white/80 ${domain.ativo ? 'border-gold shadow-[0_8px_30px_rgba(117,94,0,.08)]' : 'border-stone-200'}`}><header className="flex items-center gap-3 border-b border-stone-200 px-5 py-4"><h2 className="text-lg font-semibold">{nomeDoSetor(domain.nome)}</h2>{domain.ativo && <span className="rounded-full bg-gold px-2 py-0.5 text-[10px] font-bold text-zinc-950">ATIVO</span>}<span className="ml-auto text-xs text-zinc-500">{domain.total_metricas} métricas</span><button type="button" disabled={domain.ativo || trocando !== ''} onClick={() => void ligar(domain.nome)} className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-xs font-semibold text-zinc-700 transition-colors hover:border-gold disabled:cursor-not-allowed disabled:opacity-40">{domain.ativo ? 'Em uso' : trocando === domain.nome ? 'Ligando…' : 'Ligar'}</button></header>{domain.metricas.length === 0 ? <p className="px-5 py-4 text-xs text-zinc-500">Sem métricas de setor: o motor é o mesmo e nenhum vocabulário de setor entra.</p> : <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="border-b border-stone-200 bg-stone-100/60 text-zinc-500"><tr><th className="px-5 py-3">Métrica</th><th>Grupo</th><th>Direção</th><th className="pr-5">Descrição / fonte</th></tr></thead><tbody className="divide-y divide-stone-200">{domain.metricas.map(metric => <tr key={metric.nome}><td className="px-5 py-3"><strong>{metric.label}</strong>{metric.unidade && <span className="ml-1 text-zinc-400">({metric.unidade})</span>}<span className="block text-[10px] text-zinc-400">{metric.nome}</span></td><td className="capitalize">{metric.grupo}</td><td>{metric.maior_melhor == null ? 'Contextual' : metric.maior_melhor ? <span className="inline-flex items-center gap-1 text-emerald-700"><ArrowUp className="h-3 w-3" />Maior</span> : <span className="inline-flex items-center gap-1 text-red-700"><ArrowDown className="h-3 w-3" />Menor</span>}</td><td className="max-w-md py-3 pr-5 text-zinc-600">{metric.descricao || 'Sem descrição'}{metric.fonte && <span className="mt-0.5 block text-[10px] text-zinc-400">Fonte: {metric.fonte}</span>}</td></tr>)}</tbody></table></div>}</article>)}</div>
  </div></section>;
};
