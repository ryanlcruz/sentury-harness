import React, { useCallback, useEffect, useState } from 'react';
import {
  Anchor,
  Blocks,
  Bot,
  Check,
  ChevronRight,
  CircleAlert,
  Database,
  FileText,
  Globe2,
  GraduationCap,
  HardDrive,
  KeyRound,
  LayoutDashboard,
  Library,
  LifeBuoy,
  ListTree,
  Plug,
  Radio,
  RefreshCw,
  Repeat,
  Route,
  Server,
  Settings,
  ShieldCheck,
  Wifi,
  Wrench,
  X,
} from 'lucide-react';
import { z } from 'zod';
import { Toggle } from '../../components/Toggle';
import { ChannelsSection } from './ChannelsSection';
import { PermissionsSection } from './PermissionsSection';
import { BrowserConnectionSection } from './BrowserConnectionSection';
import { TarefasLateraisSection } from './TarefasLateraisSection';
import { EmbeddingsSection } from './EmbeddingsSection';
import { ModelosLocaisSection } from './ModelosLocaisSection';
import {
  authHeaders,
  getRuntimeConfig,
  SenturyEffort,
  SenturyMode,
  setRuntimeConnection,
  setRuntimeEffort,
  setRuntimeMode,
} from '../../runtime/config';
import { setProcessTraceEnabled, useProcessTraceEnabled } from '../../runtime/preferences';
import { apiClient } from '../../transport/http-client';

interface FullSettingsViewProps {
  onClose: () => void;
  onNavigate: (feature: SettingsDestination) => void;
  initialSection?: SettingsSection;
}

export type SettingsSection = 'overview' | 'connection' | 'browser' | 'agent' | 'memory' | 'channels' | 'permissoes' | 'integrations' | 'locais';
type SettingsDestination = 'providers' | 'context' | 'skills' | 'mcp';

const ChannelsSummarySchema = z.object({
  canais: z.array(z.object({
    id: z.string(),
    available: z.boolean().default(false),
    active: z.boolean().optional(),
  }).passthrough()).default([]),
});

const FlagsSchema = z.object({
  native_tools: z.boolean(),
  autolearn: z.boolean(),
  aprender_a_cada: z.number().int().nonnegative().optional(),
  gemini_embeddings: z.boolean(),
  fastembed_embeddings: z.boolean(),
  knowledge_mode: z.string().optional(),
}).passthrough();

const SystemStatusSchema = z.object({
  llm_chain: z.array(z.string()).default([]),
  data_store: z.string(),
  session_store: z.string(),
  knowledge_base: z.string(),
});

type Flags = z.infer<typeof FlagsSchema>;
type SystemStatus = z.infer<typeof SystemStatusSchema>;

const SECTIONS = [
  { id: 'overview' as const, title: 'Visão geral', description: 'Estado desta instalação', icon: LayoutDashboard },
  { id: 'connection' as const, title: 'Conexão', description: 'API, identidade e acesso', icon: Wifi },
  { id: 'browser' as const, title: 'Navegador', description: 'Extensão e abas próprias', icon: Globe2 },
  { id: 'agent' as const, title: 'Agente', description: 'Router, esforço e execução', icon: Bot },
  { id: 'memory' as const, title: 'Memória e contexto', description: 'Persistência e recuperação', icon: Database },
  { id: 'channels' as const, title: 'Canais', description: 'Web, Telegram e voz', icon: Radio },
  { id: 'permissoes' as const, title: 'Permissões', description: 'O que ele pode fazer sem perguntar', icon: ShieldCheck },
  { id: 'integrations' as const, title: 'Integrações', description: 'Provedores, skills e MCP', icon: Plug },
  { id: 'locais' as const, title: 'Modelos locais', description: 'Baixar, rodar e testar', icon: HardDrive },
];

const MODE_OPTIONS: Array<{ value: SenturyMode; title: string; description: string; icon: typeof Route }> = [
  { value: 'router', title: 'Router', description: 'RobinBandit escolhe a melhor cadeia disponível.', icon: Route },
  { value: 'ultra', title: 'Reforçado', description: 'Começa no provedor escolhido e usa fallback se necessário.', icon: LifeBuoy },
  { value: 'ultra_max', title: 'Dedicado', description: 'Permanece no provedor escolhido; se falhar, o turno termina.', icon: Anchor },
];

const EFFORT_OPTIONS: Array<{ value: SenturyEffort; title: string; description: string }> = [
  { value: 'auto', title: 'Automático', description: 'Usa o padrão do provedor.' },
  { value: 'low', title: 'Leve', description: 'Respostas rápidas e diretas.' },
  { value: 'medium', title: 'Médio', description: 'Equilíbrio entre velocidade e análise.' },
  { value: 'high', title: 'Profundo', description: 'Mais investigação quando a tarefa exige.' },
];

const FLAG_OPTIONS: Array<{
  key: keyof Flags;
  title: string;
  description: string;
  icon: typeof Wrench;
}> = [
  { key: 'native_tools', title: 'Tools nativas', description: 'Usa function calling nativo quando o provedor oferece suporte.', icon: Wrench },
  { key: 'autolearn', title: 'Aprendizado pós-chat', description: 'De tempos em tempos revê a conversa e guarda o que vale em memória e skills.', icon: GraduationCap },
];

export const FullSettingsView: React.FC<FullSettingsViewProps> = ({ onClose, onNavigate, initialSection = 'overview' }) => {
  const [initialConfig] = useState(() => getRuntimeConfig());
  const [activeSection, setActiveSection] = useState<SettingsSection>(initialSection);
  const [apiUrl, setApiUrl] = useState(initialConfig.apiUrl);
  const [userId, setUserId] = useState(initialConfig.userId);
  const [token, setToken] = useState(initialConfig.token);
  const [mode, setMode] = useState<SenturyMode>(initialConfig.mode);
  const [effort, setEffort] = useState<SenturyEffort>(initialConfig.effort);
  const [connectionStatus, setConnectionStatus] = useState<'idle' | 'testing' | 'ok' | 'error'>('idle');
  const [connectionMessage, setConnectionMessage] = useState('');
  const [canaisAtivos, setCanaisAtivos] = useState<{ ativos: number; total: number }>({ ativos: 0, total: 0 });
  const [flags, setFlags] = useState<Flags | null>(null);
  const [savingFlag, setSavingFlag] = useState<keyof Flags | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const processTraceEnabled = useProcessTraceEnabled();

  const loadRuntimeSettings = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setLoading(true);
    setLoadError('');
    const headers = authHeaders();
    const [channelsResult, flagsResult, statusResult] = await Promise.allSettled([
      apiClient.get('/sentury/channels', { headers }),
      apiClient.get('/sentury/flags', { headers }),
      apiClient.get('/sentury/status', { headers }),
    ]);

    const failures: string[] = [];
    if (channelsResult.status === 'fulfilled') {
      const data = ChannelsSummarySchema.parse(channelsResult.value);
      setCanaisAtivos({
        ativos: data.canais.filter(canal => canal.available && canal.active !== false).length,
        total: data.canais.length,
      });
    } else {
      failures.push('canais');
    }
    if (flagsResult.status === 'fulfilled') {
      setFlags(FlagsSchema.parse(flagsResult.value));
    } else {
      failures.push('motor');
    }
    if (statusResult.status === 'fulfilled') {
      setSystemStatus(SystemStatusSchema.parse(statusResult.value));
    } else {
      failures.push('persistência');
    }
    if (failures.length > 0) setLoadError(`Não foi possível consultar: ${failures.join(', ')}.`);
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadRuntimeSettings();
  }, [loadRuntimeSettings]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const saveConnection = async () => {
    setRuntimeConnection({ apiUrl, userId, token });
    apiClient.setBaseUrl(apiUrl);
    setConnectionStatus('testing');
    setConnectionMessage('');
    try {
      await apiClient.get('/health');
      setConnectionStatus('ok');
      setConnectionMessage('Conexão salva e validada.');
      await loadRuntimeSettings();
    } catch (reason) {
      setConnectionStatus('error');
      setConnectionMessage(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const chooseMode = (value: SenturyMode) => {
    setMode(value);
    setRuntimeMode(value);
  };

  const chooseEffort = (value: SenturyEffort) => {
    setEffort(value);
    setRuntimeEffort(value);
  };

  const updateAprenderACada = async (value: number) => {
    if (!flags || !Number.isInteger(value) || value < 0 || value === flags.aprender_a_cada) return;
    const previous = flags;
    setFlags({ ...flags, aprender_a_cada: value });
    setSavingFlag('aprender_a_cada');
    setLoadError('');
    try {
      const updated = await apiClient.post('/sentury/flags', { aprender_a_cada: value }, { headers: authHeaders() });
      setFlags(FlagsSchema.parse(updated));
    } catch (reason) {
      setFlags(previous);
      setLoadError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSavingFlag(null);
    }
  };

  const updateFlag = async (name: keyof Flags, value: boolean) => {
    if (!flags || typeof flags[name] !== 'boolean') return;
    const previous = flags;
    setFlags({ ...flags, [name]: value });
    setSavingFlag(name);
    setLoadError('');
    try {
      const updated = await apiClient.post(
        '/sentury/flags',
        { [name]: value },
        { headers: authHeaders() },
      );
      setFlags(FlagsSchema.parse(updated));
    } catch (reason) {
      setFlags(previous);
      setLoadError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSavingFlag(null);
    }
  };

  const navigateTo = (feature: SettingsDestination) => {
    onNavigate(feature);
  };

  return (
    <section className="fixed inset-0 z-[70] animate-[sentury-settings-in_220ms_ease-out] overflow-hidden bg-[#f6f5f0] text-zinc-900">
      <header className="flex h-16 items-center gap-3 border-b border-stone-200 bg-[#f6f5f0]/95 px-5 backdrop-blur-md sm:px-6">
        <Settings className="h-5 w-5 text-gold-hover" />
        <div className="min-w-0 flex-1">
          <h1 className="text-sm font-semibold">Configurações do Sentury</h1>
          <p className="truncate text-[10px] text-zinc-500">Instalação, inteligência, memória, provedores e integrações</p>
        </div>
        {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin text-zinc-400" /> : null}
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-stone-300 bg-white p-2 text-zinc-600 hover:text-zinc-950"
          title="Fechar configurações"
          aria-label="Fechar configurações"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="mx-auto grid h-[calc(100vh-4rem)] max-w-[1440px] grid-cols-1 overflow-hidden md:grid-cols-[250px_minmax(0,1fr)]">
        <aside className="overflow-x-auto border-b border-stone-200 bg-white/45 p-3 md:overflow-y-auto md:border-b-0 md:border-r md:p-4">
          <nav className="flex gap-2 md:block md:space-y-1" aria-label="Seções das configurações">
            {SECTIONS.map(item => {
              const Icon = item.icon;
              const active = activeSection === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveSection(item.id)}
                  className={`flex min-w-44 items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors md:w-full ${active ? 'bg-zinc-900 text-white' : 'text-zinc-700 hover:bg-white'}`}
                >
                  <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${active ? 'text-gold' : 'text-zinc-400'}`} />
                  <span className="min-w-0 flex-1">
                    <strong className="block text-xs">{item.title}</strong>
                    <span className={`mt-0.5 block truncate text-[10px] ${active ? 'text-zinc-400' : 'text-zinc-500'}`}>{item.description}</span>
                  </span>
                  {item.id === 'channels' ? (
                    <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${canaisAtivos.ativos > 0 ? 'bg-emerald-500' : 'bg-stone-300'}`} />
                  ) : null}
                </button>
              );
            })}
          </nav>
          <div className="mt-5 hidden rounded-xl border border-stone-200 bg-white/70 p-3 text-[10px] leading-4 text-zinc-500 md:block">
            <span className={`mr-2 inline-block h-2 w-2 rounded-full ${loadError ? 'bg-amber-400' : 'bg-emerald-500'}`} />
            {loadError || 'Configuração conectada ao runtime real.'}
          </div>
        </aside>

        <main className="overflow-y-auto px-5 py-6 sm:px-8 sm:py-8 lg:px-12">
          <div className="mx-auto max-w-5xl">
            {loadError ? (
              <div className="mb-5 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
                <CircleAlert className="h-4 w-4 shrink-0" />{loadError}
              </div>
            ) : null}

            {activeSection === 'overview' ? (
              <section>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Visão geral</p>
                <h2 className="mt-1 text-3xl font-semibold tracking-tight">Esta instalação</h2>
                <p className="mt-2 text-sm text-zinc-500">Veja rapidamente o que está ativo e entre direto na configuração necessária.</p>
                <div className="mt-7 grid gap-3 sm:grid-cols-2">
                  <button type="button" onClick={() => setActiveSection('agent')} className="rounded-2xl border border-stone-200 bg-white/80 p-5 text-left transition-colors hover:border-gold">
                    <div className="flex items-center justify-between"><Bot className="h-4 w-4 text-gold-hover" /><ChevronRight className="h-4 w-4 text-zinc-300" /></div>
                    <strong className="mt-4 block text-sm">Agente</strong>
                    <span className="mt-1 block text-xs text-zinc-500">{MODE_OPTIONS.find(item => item.value === mode)?.title} · esforço {EFFORT_OPTIONS.find(item => item.value === effort)?.title.toLowerCase()}</span>
                  </button>
                  <button type="button" onClick={() => setActiveSection('channels')} className="rounded-2xl border border-stone-200 bg-white/80 p-5 text-left transition-colors hover:border-gold">
                    <div className="flex items-center justify-between"><Radio className="h-4 w-4 text-gold-hover" /><span className={`rounded-full px-2 py-1 text-[9px] font-bold ${canaisAtivos.ativos > 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-stone-100 text-zinc-500'}`}>{canaisAtivos.ativos} DE {canaisAtivos.total}</span></div>
                    <strong className="mt-4 block text-sm">Canais</strong>
                    <span className="mt-1 block text-xs text-zinc-500">Web, bot do Telegram e ligação por voz, cada um com sua configuração.</span>
                  </button>
                  <button type="button" onClick={() => setActiveSection('memory')} className="rounded-2xl border border-stone-200 bg-white/80 p-5 text-left transition-colors hover:border-gold">
                    <div className="flex items-center justify-between"><Database className="h-4 w-4 text-gold-hover" /><ChevronRight className="h-4 w-4 text-zinc-300" /></div>
                    <strong className="mt-4 block text-sm">Memória e contexto</strong>
                    <span className="mt-1 block text-xs text-zinc-500">Sessões: {systemStatus?.session_store || 'consultando'} · contexto: {systemStatus?.knowledge_base || flags?.knowledge_mode || 'consultando'}</span>
                  </button>
                  <button type="button" onClick={() => setActiveSection('integrations')} className="rounded-2xl border border-stone-200 bg-white/80 p-5 text-left transition-colors hover:border-gold">
                    <div className="flex items-center justify-between"><Plug className="h-4 w-4 text-gold-hover" /><ChevronRight className="h-4 w-4 text-zinc-300" /></div>
                    <strong className="mt-4 block text-sm">Provedores e integrações</strong>
                    <span className="mt-1 block text-xs text-zinc-500">{systemStatus?.llm_chain.length || 0} rotas na cadeia · dados em {systemStatus?.data_store || 'consultando'}</span>
                  </button>
                </div>
              </section>
            ) : null}

            {activeSection === 'connection' ? (
              <section>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Conexão</p>
                <h2 className="mt-1 text-3xl font-semibold tracking-tight">API e identidade</h2>
                <p className="mt-2 text-sm text-zinc-500">Esses valores permanecem somente neste navegador. Deixe a URL vazia para usar o proxy local.</p>
                <div className="mt-7 max-w-3xl space-y-5 rounded-2xl border border-stone-200 bg-white/80 p-5 shadow-sm">
                  <label className="block"><span className="text-xs font-semibold text-zinc-700">URL da API</span><input value={apiUrl} onChange={event => setApiUrl(event.target.value)} placeholder="Vazio = backend local" className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-gold" /></label>
                  <label className="block"><span className="text-xs font-semibold text-zinc-700">Identidade local</span><input value={userId} onChange={event => setUserId(event.target.value)} className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-gold" /></label>
                  <label className="block"><span className="text-xs font-semibold text-zinc-700">Token da API</span><span className="relative mt-1.5 block"><KeyRound className="absolute left-3 top-3 h-4 w-4 text-zinc-400" /><input type="password" value={token} onChange={event => setToken(event.target.value)} placeholder="Opcional" className="w-full rounded-lg border border-stone-300 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-gold" /></span></label>
                  <div className="flex flex-wrap items-center gap-3 border-t border-stone-200 pt-4"><button type="button" onClick={() => void saveConnection()} disabled={connectionStatus === 'testing'} className="rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-50">{connectionStatus === 'testing' ? 'Validando…' : 'Salvar e testar'}</button>{connectionStatus === 'ok' ? <span className="flex items-center gap-1 text-xs text-emerald-700"><Check className="h-3.5 w-3.5" />{connectionMessage}</span> : null}{connectionStatus === 'error' ? <span className="text-xs text-red-700">{connectionMessage}</span> : null}</div>
                </div>
              </section>
            ) : null}

            {activeSection === 'browser' ? <BrowserConnectionSection /> : null}

            {activeSection === 'agent' ? (
              <section>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Agente</p>
                <h2 className="mt-1 text-3xl font-semibold tracking-tight">Comportamento e execução</h2>
                <p className="mt-2 text-sm text-zinc-500">Escolhas padrão para novos turnos e recursos aplicados ao runtime atual.</p>

                <div className="mt-7">
                  <h3 className="text-sm font-semibold">Modo de provedor</h3>
                  <div className="mt-3 grid gap-3 lg:grid-cols-3" role="radiogroup" aria-label="Modo padrão de provedor">
                    {MODE_OPTIONS.map(item => {
                      const Icon = item.icon;
                      const selected = item.value === mode;
                      return <button key={item.value} type="button" role="radio" aria-checked={selected} onClick={() => chooseMode(item.value)} className={`rounded-xl border p-4 text-left transition-colors ${selected ? 'border-gold bg-gold-soft' : 'border-stone-200 bg-white/80 hover:border-stone-300'}`}><Icon className="h-4 w-4 text-gold-hover" /><strong className="mt-3 block text-sm">{item.title}</strong><span className="mt-1 block text-xs leading-5 text-zinc-500">{item.description}</span></button>;
                    })}
                  </div>
                </div>

                <div className="mt-7">
                  <h3 className="text-sm font-semibold">Esforço padrão</h3>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4" role="radiogroup" aria-label="Esforço padrão">
                    {EFFORT_OPTIONS.map(item => {
                      const selected = item.value === effort;
                      return <button key={item.value} type="button" role="radio" aria-checked={selected} onClick={() => chooseEffort(item.value)} className={`rounded-xl border p-3 text-left transition-colors ${selected ? 'border-gold bg-gold-soft' : 'border-stone-200 bg-white/80 hover:border-stone-300'}`}><strong className="block text-xs">{item.title}</strong><span className="mt-1 block text-[10px] leading-4 text-zinc-500">{item.description}</span></button>;
                    })}
                  </div>
                </div>

                <div className="mt-7 space-y-2">
                  <div className="flex items-center justify-between"><div><h3 className="text-sm font-semibold">Recursos do motor</h3><p className="mt-1 text-[11px] text-zinc-500">As flags do servidor são aplicadas ao vivo; preferências visuais ficam neste navegador.</p></div>{savingFlag ? <RefreshCw className="h-3.5 w-3.5 animate-spin text-zinc-400" /> : null}</div>
                  <div className="rounded-xl border border-stone-200 bg-white/80">
                    <div className="flex items-center gap-3 border-b border-stone-200 p-4"><ListTree className="h-4 w-4 text-gold-hover" /><span className="min-w-0 flex-1"><strong className="block text-xs">Mostrar processo analítico</strong><span className="mt-0.5 block text-[10px] text-zinc-500">Exibe etapas operacionais reais sem revelar raciocínio privado.</span></span><Toggle label="Mostrar processo analítico" checked={processTraceEnabled} onChange={setProcessTraceEnabled} /></div>
                    {flags ? FLAG_OPTIONS.map((item, index) => {
                      const Icon = item.icon;
                      return <div key={item.key} className={`flex items-center gap-3 p-4 ${index < FLAG_OPTIONS.length - 1 ? 'border-b border-stone-200' : ''}`}><Icon className="h-4 w-4 text-gold-hover" /><span className="min-w-0 flex-1"><strong className="block text-xs">{item.title}</strong><span className="mt-0.5 block text-[10px] text-zinc-500">{item.description}</span></span><Toggle label={item.title} checked={Boolean(flags[item.key])} disabled={savingFlag !== null} onChange={value => void updateFlag(item.key, value)} /></div>;
                    }) : <p className="p-4 text-xs text-zinc-500">Carregando configuração do motor…</p>}
                    {flags && typeof flags.aprender_a_cada === 'number' ? <div className="flex items-center gap-3 border-t border-stone-200 p-4"><Repeat className="h-4 w-4 text-gold-hover" /><span className="min-w-0 flex-1"><strong className="block text-xs">Revisar a cada</strong><span className="mt-0.5 block text-[10px] text-zinc-500">Voltas entre uma revisão e outra (cada ferramenta, ou turno só de conversa, conta uma). Na revisão o agente decide se há algo a guardar; zero desliga.</span></span><input type="number" min={0} max={1000} aria-label="Voltas entre revisões" defaultValue={flags.aprender_a_cada} disabled={!flags.autolearn || savingFlag !== null} onBlur={event => void updateAprenderACada(Number(event.currentTarget.value))} className="w-16 rounded-md border border-stone-200 bg-white px-2 py-1 text-right text-xs disabled:opacity-50" /></div> : null}
                  </div>
                </div>
              </section>
            ) : null}

            {activeSection === 'memory' ? (
              <section>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Memória e contexto</p>
                <h2 className="mt-1 text-3xl font-semibold tracking-tight">Persistência local primeiro</h2>
                <p className="mt-2 text-sm text-zinc-500">Sessões, experiências, contexto semântico e skills continuam separados para que cada camada possa evoluir sem perder dados.</p>
                <dl className="mt-7 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-stone-200 bg-white/80 p-4"><dt className="text-[10px] font-bold uppercase tracking-wide text-zinc-400">Sessões</dt><dd className="mt-2 text-sm font-semibold">{systemStatus?.session_store || 'Consultando…'}</dd></div>
                  <div className="rounded-xl border border-stone-200 bg-white/80 p-4"><dt className="text-[10px] font-bold uppercase tracking-wide text-zinc-400">Knowledge base</dt><dd className="mt-2 text-sm font-semibold">{systemStatus?.knowledge_base || flags?.knowledge_mode || 'Consultando…'}</dd></div>
                  <div className="rounded-xl border border-stone-200 bg-white/80 p-4"><dt className="text-[10px] font-bold uppercase tracking-wide text-zinc-400">Dados analíticos</dt><dd className="mt-2 text-sm font-semibold">{systemStatus?.data_store || 'Consultando…'}</dd></div>
                </dl>
                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                  <button type="button" onClick={() => navigateTo('context')} className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white/80 p-4 text-left hover:border-gold"><FileText className="mt-0.5 h-4 w-4 text-gold-hover" /><span className="flex-1"><strong className="block text-sm">Abrir Context Engine</strong><span className="mt-1 block text-xs text-zinc-500">Identidade, contrato central e playbooks editáveis.</span></span><ChevronRight className="h-4 w-4 text-zinc-300" /></button>
                  <button type="button" onClick={() => navigateTo('skills')} className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white/80 p-4 text-left hover:border-gold"><Library className="mt-0.5 h-4 w-4 text-gold-hover" /><span className="flex-1"><strong className="block text-sm">Abrir Skills</strong><span className="mt-1 block text-xs text-zinc-500">Rotinas salvas, curadoria e telemetria de uso.</span></span><ChevronRight className="h-4 w-4 text-zinc-300" /></button>
                </div>
                <EmbeddingsSection />
                <TarefasLateraisSection />
              </section>
            ) : null}

            {activeSection === 'channels' ? <ChannelsSection /> : null}

            {activeSection === 'permissoes' ? <PermissionsSection /> : null}

            {activeSection === 'locais' ? <ModelosLocaisSection /> : null}
            {activeSection === 'integrations' ? (
              <section>
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Integrações</p>
                <h2 className="mt-1 text-3xl font-semibold tracking-tight">Componentes plugáveis</h2>
                <p className="mt-2 text-sm text-zinc-500">Cada área abre sua configuração completa sem fingir conexões ou capacidades inexistentes.</p>
                <div className="mt-7 grid gap-3 sm:grid-cols-2">
                  {[
                    { id: 'providers' as const, title: 'Provedores e RobinBandit', description: 'Credenciais, contas, modelos, tiers e prioridades.', icon: Server },
                    { id: 'context' as const, title: 'Context Engine', description: 'Identidade, contrato central e playbooks editáveis.', icon: FileText },
                    { id: 'skills' as const, title: 'Skills', description: 'Biblioteca procedural, telemetria e curadoria.', icon: Library },
                    { id: 'mcp' as const, title: 'Tools e MCP', description: 'Catálogo real de ferramentas e integrações externas.', icon: Blocks },
                  ].map(item => {
                    const Icon = item.icon;
                    return <button key={item.id} type="button" onClick={() => navigateTo(item.id)} className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white/80 p-4 text-left transition-colors hover:border-gold"><Icon className="mt-0.5 h-4 w-4 text-gold-hover" /><span className="min-w-0 flex-1"><strong className="block text-sm">{item.title}</strong><span className="mt-1 block text-xs leading-5 text-zinc-500">{item.description}</span></span><ChevronRight className="h-4 w-4 text-zinc-300" /></button>;
                  })}
                </div>
              </section>
            ) : null}
          </div>
        </main>
      </div>
    </section>
  );
};
