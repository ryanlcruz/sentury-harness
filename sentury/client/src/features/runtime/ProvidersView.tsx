import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ModelCatalogPanel } from './ModelCatalogPanel';
import { ConectarConta } from './ConectarConta';
import { SelecaoDeModo } from './SelecaoDeModo';
import { AdicionarProvedor, type ProvedorSemChave } from './AdicionarProvedor';
import { Activity, Info, KeyRound, RefreshCw, Route, Server, Settings2, TriangleAlert, X } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { ProviderLogo } from '../../components/ProviderLogo';

const ProviderSchema = z.object({
  ultimo_recurso: z.boolean().default(false),
  key: z.string(),
  label: z.string(),
  tier: z.number(),
  configured: z.boolean(),
  enabled: z.boolean().default(true),
  disabled_reason: z.string().default(''),
  models: z.array(z.string()).default([]),
  cost_class: z.string().default(''),
  kinds: z.array(z.string()).default(['text']),
  categoria: z.string().default('provedor'),
  estado: z.enum(['off', 'limit', 'ok', 'error', 'idle']),
  last_model: z.string().nullable().optional(),
  detail: z.string().nullable().optional(),
  latency_ms: z.number().nullable().optional(),
  cooldown: z.number().default(0),
  quality: z.number().nullable().optional(),
  samples: z.number().default(0),
  ok: z.number().default(0),
  err: z.number().default(0),
}).passthrough();

const ProvidersResponseSchema = z.object({
  router_backend: z.string(),
  providers: z.array(ProviderSchema),
  accounts: z.object({
    contas: z.array(z.object({
      id: z.string(), provider: z.string(), label: z.string(), key_env: z.string().default(''), auth_type: z.string().default(''), login_direto: z.boolean().default(false),
      models: z.array(z.string()).default([]), paga: z.boolean().default(false), configurada: z.boolean().default(false), origem: z.string().default(''),
      chaves: z.array(z.object({ i: z.number() }).passthrough()).default([]),
    }).passthrough()).default([]),
    tiers: z.record(z.string(), z.string()).default({}),
  }).optional(),
  avisos: z.array(z.object({
    provedor: z.string().default(''),
    gravidade: z.enum(['ok', 'info', 'atencao']).catch('info'),
    titulo: z.string(),
    detalhe: z.string().default(''),
  })).default([]),
}).passthrough();


type Provider = z.infer<typeof ProviderSchema>;
type Account = NonNullable<z.infer<typeof ProvidersResponseSchema>['accounts']>['contas'][number];

const tierLabels: Record<number, string> = {
  1: 'Prioridade alta',
  2: 'Prioridade normal',
  3: 'Reserva',
  9: 'Fallback de regras',
};

const stateLabels: Record<Provider['estado'], string> = {
  ok: 'Saudável',
  idle: 'Disponível',
  limit: 'Em espera',
  error: 'Falhou',
  off: 'Sem credencial',
};

const stateClasses: Record<Provider['estado'], string> = {
  ok: 'bg-emerald-500',
  idle: 'bg-sky-500',
  limit: 'bg-gold',
  error: 'bg-red-500',
  off: 'bg-zinc-300',
};

export const ProvidersView: React.FC = () => {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [routerBackend, setRouterBackend] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [isConfiguring, setIsConfiguring] = useState(false);
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({});
  const [catalogo, setCatalogo] = useState<{ key: string; label: string } | null>(null);
  const [avisos, setAvisos] = useState<z.infer<typeof ProvidersResponseSchema>['avisos']>([]);
  const [arrastando, setArrastando] = useState<string | null>(null);
  const [tierAlvo, setTierAlvo] = useState<number | null>(null);
  const [savingAccount, setSavingAccount] = useState<string | null>(null);

  // A conta diz a credencial; os modelos, quando ela nao declara os seus,
  // vem do provedor. Sem essa tabela o seletor mostraria conta sem modelo.
  const modelosPorProvedor = useMemo(
    () => Object.fromEntries(providers.map(p => [p.key, p.models])),
    [providers],
  );
  const custoPorProvedor = useMemo(
    () => Object.fromEntries(providers.map(p => [p.key, p.cost_class])),
    [providers],
  );

  const loadProviders = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.get<unknown>('/sentury/providers', { headers: authHeaders() });
      const data = ProvidersResponseSchema.parse(response);
      setProviders(data.providers);
      setRouterBackend(data.router_backend);
      setAccounts(data.accounts?.contas || []);
      setAvisos(data.avisos || []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const saveKey = async (account: Account) => {
    const value = keyDrafts[account.id]?.trim();
    if (!account.key_env || !value) return;
    setSavingAccount(account.id); setError(null);
    try {
      await apiClient.post('/sentury/providers/keys', { key_env: account.key_env, valor: value, adicionar: account.chaves.length > 0 }, { headers: authHeaders() });
      setKeyDrafts(current => ({ ...current, [account.id]: '' }));
      await loadProviders();
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setSavingAccount(null); }
  };

  const soltarNoTier = async (tier: number) => {
    const chave = arrastando;
    setArrastando(null);
    setTierAlvo(null);
    const provider = providers.find(item => item.key === chave);
    if (!provider || provider.tier === tier) return;
    setError(null);
    try {
      await apiClient.post('/sentury/providers/routing', { provider: provider.key, tier }, { headers: authHeaders() });
      await loadProviders();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  // Marca contas pagas para reservar crédito aos modos mais caros.
  const setContaPaga = async (account: Account, paga: boolean) => {
    setSavingAccount(account.id);
    setError(null);
    try {
      await apiClient.post('/sentury/providers/accounts', {
        id: account.id,
        provider: account.provider,
        key_env: account.key_env,
        label: account.label,
        models: account.models,
        paga,
      }, { headers: authHeaders() });
      await loadProviders();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSavingAccount(null);
    }
  };

  const setProviderTier = async (provider: Provider, value: string) => {
    setSavingAccount(provider.key); setError(null);
    try { await apiClient.post('/sentury/providers/routing', { provider: provider.key, tier: value ? Number(value) : null }, { headers: authHeaders() }); await loadProviders(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setSavingAccount(null); }
  };

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  // Gateway nao serve modelo: e outro roteador, que repassa para provedores.
  // Listado junto dos provedores, parece que o Sentury fala com ele como fala
  // com a Groq.
  const gateways = useMemo(
    () => providers.filter(item => item.categoria === 'gateway'), [providers]);

  // O motor de regras é a rede de segurança interna: só entra quando todos falham, e não se configura.
  const internos = (item: Provider) => item.key === 'fallback' || item.ultimo_recurso;
  // Sem chave, o provedor vai para "Adicionar provedor", com a chave colada ali mesmo.
  const semChave = useMemo<ProvedorSemChave[]>(
    () => providers.filter(item => item.categoria !== 'gateway' && !internos(item) && item.estado === 'off')
      .map(item => ({ key: item.key, label: item.label, models: item.models, cost_class: item.cost_class,
        key_env: String((item as Record<string, unknown>).key_env || ''), key_url: String((item as Record<string, unknown>).key_url || '') })),
    [providers]);
  const semCredencial = semChave.length;

  // So o que pede acao. `info` ("conta fora da cadeia", "variavel nao esta no
  // ambiente") repete o "Sem credencial" do cartao, e o proprio texto dizia
  // "nada a fazer se voce nao usa este provedor".
  const avisosDeAtencao = useMemo(() => avisos.filter(item => item.gravidade === 'atencao'), [avisos]);

  const groups = useMemo(() => {
    const byTier = new Map<number, Provider[]>();
    for (const provider of providers) {
      if (provider.categoria === 'gateway' || internos(provider) || provider.estado === 'off') continue;
      byTier.set(provider.tier, [...(byTier.get(provider.tier) || []), provider]);
    }
    return [...byTier.entries()].sort(([a], [b]) => a - b);
  }, [providers]);

  if (catalogo) {
    return (
      <ModelCatalogPanel
        providerKey={catalogo.key}
        providerLabel={catalogo.label}
        onBack={() => setCatalogo(null)}
        onSaved={() => loadProviders()}
      />
    );
  }

  return (
    <section className="h-full overflow-y-auto px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <header className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">
              <Route className="h-3.5 w-3.5" />
              RobinBandit runtime
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-900">Provedores</h1>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-500">
              Disponibilidade, modelos e sinais reais usados pelo Router. As credenciais permanecem no servidor.
            </p>
            <p className="mt-1 text-[11px] text-zinc-500">
              {providers.length} provedores no catálogo · {accounts.filter(account => account.configurada).length} contas configuradas · {semCredencial} para adicionar em "Adicionar provedor".
              Chaves separadas por vírgula contam como várias chaves da mesma conta, não como novos provedores.
            </p>
          </div>
          <div className="flex gap-2"><button type="button" onClick={() => setIsConfiguring(value => !value)} className="inline-flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2 text-xs font-medium text-zinc-700 shadow-sm"><Settings2 className="h-3.5 w-3.5" />{isConfiguring ? 'Fechar configuração' : 'Configurar'}</button><button type="button" onClick={() => void loadProviders()} disabled={isLoading} className="inline-flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2 text-xs font-medium text-zinc-700 shadow-sm transition-colors hover:bg-stone-50 disabled:opacity-50"><RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />Atualizar</button></div>
        </header>

        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-stone-200 bg-white/80 p-4">
            <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-zinc-400">Router</span>
            <div className="mt-2 flex items-center gap-2 text-sm font-semibold text-zinc-800">
              <Server className="h-4 w-4 text-gold-hover" />
              {routerBackend || (isLoading ? 'Consultando…' : 'Indisponível')}
            </div>
          </div>
          <div className="rounded-xl border border-stone-200 bg-white/80 p-4">
            <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-zinc-400">Provedores configurados</span>
            <div className="mt-2 text-xl font-semibold text-zinc-900">{providers.filter(provider => provider.configured).length}</div>
          </div>
          <div className="rounded-xl border border-stone-200 bg-white/80 p-4">
            {/* "Disponível" (idle) e provedor configurado que ainda nao foi chamado:
                contar so os "ok" dava 0 num servidor recem-ligado, ao lado de
                cartoes dizendo "Disponível". */}
            <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-zinc-400">Prontos para uso</span>
            <div className="mt-2 flex items-center gap-2 text-xl font-semibold text-zinc-900">
              <Activity className="h-4 w-4 text-emerald-600" />
              {providers.filter(provider => provider.estado === 'ok' || provider.estado === 'idle').length}
            </div>
            <p className="mt-1 text-[11px] text-zinc-500">
              {providers.filter(provider => provider.estado === 'ok').length} com resposta recente
            </p>
          </div>
        </div>

        {/* Reforcado e Dedicado ficavam no fim do "Configurar", depois de
            todos os provedores e todas as contas: a escolha que mais muda a
            resposta era a mais dificil de achar. */}
        <section className="mt-7">
          <h2 className="text-xs font-bold uppercase tracking-[0.13em] text-zinc-700">Modos</h2>
          <p className="mt-1 text-[11px] leading-5 text-zinc-500">
            O Router escolhe sozinho entre os provedores abaixo. Nos modos, quem escolhe é você: conta e modelo.
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <SelecaoDeModo
              modo="ultra"
              rotulo="Reforçado"
              descricao="Tenta estes primeiro, na ordem; se todos falharem, cai no Router."
              contas={accounts}
              modelosDoProvedor={modelosPorProvedor}
              custoDoProvedor={custoPorProvedor}
              onSalvo={() => void loadProviders()}
            />
            <SelecaoDeModo
              modo="ultra_max"
              rotulo="Dedicado"
              descricao="Só estes, na ordem. Nunca cai no Router."
              contas={accounts}
              modelosDoProvedor={modelosPorProvedor}
              custoDoProvedor={custoPorProvedor}
              onSalvo={() => void loadProviders()}
            />
          </div>
        </section>

        {error && (
          <div className="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <strong className="font-semibold">Não foi possível consultar os provedores.</strong>
            <span className="mt-1 block text-xs text-red-700">{error}</span>
          </div>
        )}

        {isLoading && providers.length === 0 && (
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {[1, 2, 3, 4].map(item => <div key={item} className="h-32 animate-pulse rounded-xl border border-stone-200 bg-white/60" />)}
          </div>
        )}

        {!isLoading && !error && providers.length === 0 && (
          <p className="mt-6 rounded-xl border border-stone-200 bg-white/70 p-5 text-sm text-zinc-500">Nenhum provedor foi retornado pelo runtime.</p>
        )}

        {avisosDeAtencao.length > 0 && (
          <section className="mt-7 space-y-2">
            <h2 className="text-xs font-bold uppercase tracking-[0.13em] text-zinc-700">Precisa de atenção</h2>
            {avisosDeAtencao.map((aviso, indice) => (
              <article
                key={`${aviso.provedor}-${indice}`}
                className={`flex items-start gap-2.5 rounded-xl border p-3.5 ${
                  aviso.gravidade === 'atencao' ? 'border-amber-200 bg-amber-50' : 'border-stone-200 bg-white/70'
                }`}
              >
                {aviso.gravidade === 'atencao'
                  ? <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  : <Info className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />}
                <div className="min-w-0">
                  <strong className="block text-xs">
                    <span className="font-mono text-[10px] uppercase text-zinc-500">{aviso.provedor}</span>
                    {' · '}{aviso.titulo}
                  </strong>
                  {aviso.detalhe ? <p className="mt-1 text-[11px] leading-5 text-zinc-600">{aviso.detalhe}</p> : null}
                </div>
              </article>
            ))}
          </section>
        )}

        <div className="mt-7 space-y-7">
          {groups.map(([tier, tierProviders]) => (
            <section
              key={tier}
              onDragOver={event => { if (arrastando) { event.preventDefault(); setTierAlvo(tier); } }}
              onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setTierAlvo(atual => (atual === tier ? null : atual)); }}
              onDrop={event => { event.preventDefault(); void soltarNoTier(tier); }}
              className={`rounded-2xl p-2 transition-colors ${tierAlvo === tier ? 'bg-gold-soft/50' : ''}`}
            >
              <div className="mb-3 flex items-center gap-3">
                <h2 className="text-xs font-bold uppercase tracking-[0.13em] text-zinc-800">{tierLabels[tier] || `Tier ${tier}`}</h2>
                <span className="h-px flex-1 bg-stone-200" />
                <span className="text-[10px] text-zinc-400">{tierProviders.length}</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {tierProviders.map(provider => (
                  <article
                    key={provider.key}
                    draggable={provider.key !== 'fallback'}
                    onDragStart={event => { setArrastando(provider.key); event.dataTransfer.setData('text/plain', provider.key); }}
                    onDragEnd={() => { setArrastando(null); setTierAlvo(null); }}
                    title={provider.key !== 'fallback' ? 'Arraste para outro tier' : undefined}
                    className={`rounded-xl border border-stone-200 bg-white/85 p-4 shadow-sm transition-opacity ${provider.key !== 'fallback' ? 'cursor-grab active:cursor-grabbing' : ''} ${arrastando === provider.key ? 'opacity-40' : ''}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <ProviderLogo providerKey={provider.key} label={provider.label} className="h-9 w-9 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <h3 className="flex items-center gap-2 truncate text-sm font-semibold text-zinc-900">
                          {provider.label}
                          {provider.ultimo_recurso && (
                            <span className="shrink-0 rounded-full border border-stone-300 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-zinc-500" title="Rede de segurança do sistema: só entra quando todos os outros falham. Não é uma escolha de configuração.">
                              último recurso
                            </span>
                          )}
                        </h3>
                        <p className="mt-1 truncate text-[11px] text-zinc-500">{provider.models.join(', ') || 'Motor de regras'}</p>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1.5">
                        <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-zinc-600">
                          <span className={`h-2 w-2 rounded-full ${stateClasses[provider.estado]}`} />
                          {provider.enabled ? stateLabels[provider.estado] : 'Encerrado'}
                        </span>
                        {provider.key !== 'fallback' && (
                          <button
                            type="button"
                            onClick={() => setCatalogo({ key: provider.key, label: provider.label })}
                            className="rounded-md border border-stone-200 px-2 py-1 text-[10px] font-medium text-zinc-600 hover:border-gold hover:text-gold-ink"
                          >
                            Modelos
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-stone-100 pt-3 text-[10px] text-zinc-500">
                        {!provider.enabled && <span className="font-medium text-zinc-600">{provider.disabled_reason || 'Integração desativada'}</span>}
                      {provider.last_model && <span>Último: {provider.last_model}</span>}
                      {provider.latency_ms != null && <span>{provider.latency_ms} ms</span>}
                      {provider.quality != null && <span>Qualidade {Math.round(provider.quality * 100)}%</span>}
                      {(provider.ok > 0 || provider.err > 0) && <span>{provider.ok} ok · {provider.err} falhas</span>}
                      {provider.cooldown > 0 && <span>Espera {provider.cooldown}s</span>}
                    </div>
                    {isConfiguring && <label className="mt-3 flex items-center justify-between gap-3 border-t border-stone-100 pt-3 text-[10px] text-zinc-500"><span>Tier do Router</span><select value={provider.tier} disabled={savingAccount === provider.key} onChange={event => void setProviderTier(provider, event.target.value)} className="rounded-md border border-stone-300 bg-white px-2 py-1 text-xs text-zinc-700"><option value="1">Tier 1</option><option value="2">Tier 2</option><option value="3">Tier 3</option><option value="">Padrão do YAML</option></select></label>}
                  </article>
                ))}
                {arrastando && tierAlvo === tier && !tierProviders.some(item => item.key === arrastando) ? (
                  <div className="flex min-h-24 items-center justify-center rounded-xl border-2 border-dashed border-gold bg-gold-soft/40 text-[11px] font-medium text-gold-ink">
                    Soltar aqui
                  </div>
                ) : null}
              </div>
            </section>
          ))}

          <AdicionarProvedor provedores={semChave} onGuardado={() => void loadProviders()} onAbrirContas={() => setIsConfiguring(true)} />

          {gateways.length > 0 && (
            <section>
              <div className="mb-3 flex items-center gap-3">
                <h2 className="text-xs font-bold uppercase tracking-[0.13em] text-zinc-800">Gateways</h2>
                <span className="h-px flex-1 bg-stone-200" />
                <span className="text-[10px] text-zinc-400">{gateways.length}</span>
              </div>
              <p className="mb-3 text-[11px] leading-5 text-zinc-500">
                Roteadores de terceiros. Não servem modelo: recebem o pedido e escolhem
                por conta própria para onde mandar. Plugado e ligado, quem decide dali
                para frente é ele, não o RobinBandit.
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {gateways.map(gateway => (
                  <article key={gateway.key} className="rounded-xl border border-stone-200 bg-white/60 p-4">
                    <div className="flex items-start gap-3">
                      <ProviderLogo providerKey={gateway.key} label={gateway.label} className="h-9 w-9 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <h3 className="truncate text-sm font-semibold text-zinc-900">{gateway.label}</h3>
                        <p className="mt-1 text-[11px] text-zinc-500">
                          {gateway.enabled ? (gateway.models.join(', ') || 'sem modelos listados') : 'desligado'}
                        </p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}
        </div>

        {isConfiguring && <section className="mt-8 rounded-2xl border border-stone-300 bg-[#fffdf8] p-5"><div className="flex items-start gap-3"><KeyRound className="mt-0.5 h-4 w-4 text-gold-hover" /><div><h2 className="text-sm font-semibold">Contas e credenciais</h2><p className="mt-1 text-xs leading-5 text-zinc-500">A chave entra no cofre do RobinBandit e nunca volta na resposta — nem prefixo nem sufixo. Contas por assinatura usam o botão de conexão.</p></div><button type="button" onClick={() => setIsConfiguring(false)} className="ml-auto rounded-md p-1 text-zinc-400 hover:bg-stone-100"><X className="h-4 w-4" /></button></div><div className="mt-4 space-y-2">{accounts.map(account => <article key={account.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-stone-200 bg-white p-3"><ProviderLogo providerKey={account.provider} label={account.label} className="h-8 w-8" /><div className="min-w-44 flex-1"><strong className="block text-xs">{account.label}</strong><span className="text-[10px] text-zinc-500">{account.login_direto ? 'Uma assinatura, conexão direta ou Codex CLI' : account.auth_type === 'codex_cli' ? 'Autenticação pelo Codex CLI' : account.auth_type === 'claude_cli' ? 'Autenticação pelo Claude Code' : account.auth_type === 'chatgpt_oauth' ? 'Autorização direta do plano ChatGPT' : `${account.key_env} · ${account.chaves.length} chave(s) presente(s) · ${account.origem || 'não configurada'}`}</span></div>{account.key_env && (
                    <label className="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full border border-stone-200 px-2.5 py-1 text-[10px] font-semibold text-zinc-600 hover:border-gold" title="Crédito pago: reservado para os tiers caros">
                      <input
                        type="checkbox"
                        checked={Boolean(account.paga)}
                        disabled={savingAccount === account.id}
                        onChange={event => void setContaPaga(account, event.target.checked)}
                        className="h-3 w-3 accent-zinc-900"
                      />
                      {account.paga ? <span className="text-gold-ink">CRÉDITO PAGO</span> : 'conta paga'}
                    </label>
                  )}{account.auth_type !== 'codex_cli' && account.key_env && <><input type="password" value={keyDrafts[account.id] || ''} onChange={event => setKeyDrafts(current => ({ ...current, [account.id]: event.target.value }))} placeholder={account.configurada ? 'Adicionar outra chave' : 'Inserir chave'} className="min-w-56 rounded-lg border border-stone-300 px-3 py-2 text-xs outline-none focus:border-gold" /><button type="button" disabled={!keyDrafts[account.id]?.trim() || savingAccount === account.id} onClick={() => void saveKey(account)} className="rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-35">Salvar no cofre</button></>}
                  {['codex_cli', 'claude_cli', 'chatgpt_oauth'].includes(account.auth_type) &&
                    <ConectarConta provedor={account.provider} tipo={account.auth_type} loginDireto={account.login_direto} onConnected={loadProviders} />}
                  {/* Digitar id de modelo e convite a errar: quem escolhe e o
                      catalogo, por clique. Aqui fica so o que ja esta escolhido. */}
                  <div className="mt-1 flex w-full flex-wrap items-center gap-1.5 border-t border-stone-100 pt-2 text-[10px] text-zinc-500">
                    <span className="shrink-0">Modelos desta conta</span>
                    {account.models.length ? account.models.map(modelo => (
                      <span key={modelo} className="rounded-md bg-stone-100 px-1.5 py-0.5 font-mono text-[9px] text-zinc-600">{modelo}</span>
                    )) : <span className="italic">usa os do provedor</span>}
                    <button
                      type="button"
                      onClick={() => setCatalogo({ key: account.provider, label: account.label })}
                      className="ml-auto shrink-0 rounded-lg border border-stone-300 px-2 py-1.5 font-semibold text-zinc-600 hover:border-gold"
                    >
                      Escolher no catálogo
                    </button>
                  </div>
                </article>)}</div></section>}
      </div>
    </section>
  );
};
