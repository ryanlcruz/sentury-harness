import React, { useCallback, useEffect, useState } from 'react';
import { Activity, RefreshCw, Route } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { ProviderLogo } from '../../components/ProviderLogo';

const ProviderSchema = z.object({
  key: z.string(),
  quality: z.number().nullable().optional(),
  latency_ms: z.number().nullable().optional(),
  ok: z.number().nullable().optional(),
  err: z.number().nullable().optional(),
  cooldown: z.number().nullable().optional(),
  estado: z.string().nullable().optional(),
  rpm_remaining: z.number().nullable().optional(),
}).passthrough();

const EstadoSchema = z.object({
  backend: z.string().default('robinbandit'),
  providers: z.array(ProviderSchema).default([]),
  profiles: z.record(z.string(), z.array(z.object({ provider: z.string(), model: z.string() }).passthrough())).default({}),
}).passthrough();

export const RobinBanditView: React.FC = () => {
  const [dados, setDados] = useState<z.infer<typeof EstadoSchema> | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState('');

  const load = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setLoading(true);
    setErro('');
    try {
      setDados(EstadoSchema.parse(await apiClient.get('/sentury/robinbandit', { headers: authHeaders() })));
    } catch (reason) {
      setErro(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Ordem aprendida: quem o roteador tentaria primeiro agora.
  const ordenados = [...(dados?.providers || [])].sort(
    (a, b) => (b.quality ?? 0) - (a.quality ?? 0),
  );

  return (
    <section className="h-full overflow-y-auto px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <header className="flex items-start justify-between">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Roteamento</p>
            <h1 className="mt-2 text-2xl font-semibold">RobinBandit</h1>
            <p className="mt-1 text-sm text-zinc-500">
              Estado aprendido em runtime: qualidade, latência, falhas e os perfis que definem a ordem.
            </p>
          </div>
          <button onClick={() => void load()} className="rounded-lg border border-stone-300 bg-white p-2" title="Atualizar">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </header>

        {erro && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{erro}</p>}

        {dados && (
          <>
            <section className="mt-6">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Activity className="h-4 w-4 text-gold-hover" />Qualidade aprendida por provedor
              </h2>
              <div className="mt-3 space-y-2">
                {ordenados.map(p => (
                  <article key={p.key} className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white/85 p-3">
                    <ProviderLogo providerKey={p.key} label={p.key} className="h-8 w-8" />
                    <div className="min-w-32 flex-1">
                      <strong className="block text-xs capitalize">{p.key}</strong>
                      <span className="text-[10px] text-zinc-500">
                        {p.ok ?? 0} ok · {p.err ?? 0} falhas
                        {p.latency_ms != null && ` · ${p.latency_ms} ms`}
                        {p.cooldown ? ` · cooldown ${p.cooldown}s` : ''}
                      </span>
                    </div>
                    <div className="flex w-40 items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-200">
                        <div className="h-full rounded-full bg-gold" style={{ width: `${Math.round((p.quality ?? 0) * 100)}%` }} />
                      </div>
                      <span className="w-9 text-right text-[11px] font-semibold tabular-nums text-zinc-600">
                        {p.quality != null ? `${Math.round(p.quality * 100)}%` : '—'}
                      </span>
                    </div>
                  </article>
                ))}
                {!ordenados.length && <p className="text-sm text-zinc-500">Nenhum provedor com estado registrado.</p>}
              </div>
            </section>

            <section className="mt-8">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <Route className="h-4 w-4 text-gold-hover" />Perfis e ordem de tentativa
              </h2>
              <p className="mt-1 text-xs text-zinc-500">Cada perfil declara quem tenta primeiro; a saúde acima reordena dentro disso.</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {Object.entries(dados.profiles).map(([nome, alvos]) => (
                  <div key={nome} className="rounded-xl border border-stone-200 bg-white/85 p-3">
                    <strong className="text-xs capitalize">{nome}</strong>
                    <ol className="mt-2 space-y-1">
                      {alvos.map((alvo, i) => (
                        <li key={`${alvo.provider}-${alvo.model}-${i}`} className="flex items-center gap-2 text-[11px] text-zinc-600">
                          <span className="w-4 text-right text-[10px] text-zinc-400">{i + 1}</span>
                          <ProviderLogo providerKey={alvo.provider} label={alvo.provider} className="h-4 w-4" />
                          <span className="truncate font-mono text-[10px]">{alvo.model}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </section>
  );
};
