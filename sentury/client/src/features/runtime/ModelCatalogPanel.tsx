import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Check,
  ChevronDown,
  CircleDollarSign,
  Eye,
  Boxes,
  Mic,
  RefreshCw,
  Search,
  Sparkles,
  Video,
  Volume2,
  Wrench,
} from 'lucide-react';
import { z } from 'zod';
import { ProviderLogo } from '../../components/ProviderLogo';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const ModelSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().default(''),
  price_class: z.enum(['free', 'paid', 'unknown']).default('unknown'),
  pricing: z.object({
    prompt_per_million: z.number().nullable().optional(),
    completion_per_million: z.number().nullable().optional(),
    request: z.number().nullable().optional(),
  }).default({}),
  context_length: z.number().nullable().optional(),
  max_output_tokens: z.number().nullable().optional(),
  input_modalities: z.array(z.string()).default([]),
  output_modalities: z.array(z.string()).default([]),
  capabilities: z.array(z.string()).default([]),
  active: z.boolean().default(true),
  selectable: z.boolean().default(true),
  roles: z.array(z.string()).default(['texto']),
}).passthrough();

const CatalogSchema = z.object({
  provider: z.string(),
  source: z.enum(['live', 'configured']),
  models: z.array(ModelSchema),
  warnings: z.array(z.string()).default([]),
  selected_models: z.array(z.string()).default([]),
  selected_by_role: z.record(z.string(), z.array(z.string())).default({}),
  models_overridden: z.boolean().default(false),
}).passthrough();

type Model = z.infer<typeof ModelSchema>;

interface ModelCatalogPanelProps {
  providerKey: string;
  providerLabel: string;
  onBack: () => void;
  onSaved: () => Promise<void> | void;
}

type Papel = string;

const PAPEL_ROTULO: Record<string, string> = {
  texto: 'Texto',
  imagem: 'Imagem',
  audio: 'Áudio',
  transcricao: 'Transcrição',
  embedding: 'Embedding',
  video: 'Vídeo',
};

const PAPEL_ICONE: Record<string, typeof Sparkles> = {
  texto: Sparkles,
  imagem: Eye,
  audio: Volume2,
  transcricao: Mic,
  embedding: Boxes,
  video: Video,
};
type PriceFilter = 'all' | 'free' | 'paid';
type CapabilityFilter = 'all' | 'tools' | 'vision' | 'reasoning';

const compactNumber = (value?: number | null) => {
  if (!value) return null;
  return new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
};

const formatPrice = (value?: number | null) => {
  if (value == null) return 'não informado';
  if (value === 0) return 'grátis';
  return `US$ ${value.toLocaleString('pt-BR', { maximumFractionDigits: 4 })}`;
};

export const ModelCatalogPanel: React.FC<ModelCatalogPanelProps> = ({ providerKey, providerLabel, onBack, onSaved }) => {
  const [models, setModels] = useState<Model[]>([]);
  const [papel, setPapel] = useState<Papel>('texto');
  const [porPapel, setPorPapel] = useState<Record<string, string[]>>({});
  const selected = porPapel[papel] || [];
  const setSelected = (valor: string[] | ((atual: string[]) => string[])) =>
    setPorPapel(mapa => ({ ...mapa, [papel]: typeof valor === 'function' ? valor(mapa[papel] || []) : valor }));
  const [query, setQuery] = useState('');
  const [manualId, setManualId] = useState('');
  const [priceFilter, setPriceFilter] = useState<PriceFilter>('all');
  const [capabilityFilter, setCapabilityFilter] = useState<CapabilityFilter>('all');
  const [visibleCount, setVisibleCount] = useState(18);
  const [source, setSource] = useState<'live' | 'configured'>('configured');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  const loadCatalog = async (force = false) => {
    setIsLoading(true);
    setError(null);
    try {
      const raw = await apiClient.get<unknown>(`/sentury/providers/${providerKey}/models${force ? '?force=true' : ''}`, { headers: authHeaders() });
      const data = CatalogSchema.parse(raw);
      setModels(data.models);
      setPorPapel({ ...data.selected_by_role, texto: data.selected_models });
      setSource(data.source);
      setWarnings(data.warnings);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadCatalog();
  }, [providerKey]);

  // As abas nascem do que o catalogo declarou, mais o que ja foi escolhido antes.
  const papeisDisponiveis = useMemo(() => {
    const vistos = new Set<string>(['texto']);
    models.forEach(model => (model.roles.length ? model.roles : ['texto']).forEach(r => vistos.add(r)));
    Object.keys(porPapel).forEach(r => { if ((porPapel[r] || []).length) vistos.add(r); });
    const ordem = ['texto', 'imagem', 'audio', 'transcricao', 'embedding', 'video'];
    return Array.from(vistos).sort((a, b) => {
      const ia = ordem.indexOf(a); const ib = ordem.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  }, [models, porPapel]);

  const modelById = useMemo(() => new Map(models.map(model => [model.id, model])), [models]);
  const missingSelected = selected.filter(id => !modelById.has(id));
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('pt-BR');
    return models.filter(model => {
      if (!(model.roles.length ? model.roles : ['texto']).includes(papel)) return false;
      if (priceFilter !== 'all' && model.price_class !== priceFilter) return false;
      if (capabilityFilter !== 'all' && !model.capabilities.includes(capabilityFilter)) return false;
      if (!needle) return true;
      return `${model.name} ${model.id} ${model.description}`.toLocaleLowerCase('pt-BR').includes(needle);
    });
  }, [models, query, priceFilter, capabilityFilter, papel]);

  const toggleModel = (modelId: string) => {
    setSavedNotice(null);
    setSelected(current => current.includes(modelId)
      ? current.filter(id => id !== modelId)
      : [...current, modelId]);
  };

  const addManualModel = () => {
    const id = manualId.trim();
    if (!id || id.length > 200 || /\s/.test(id)) {
      setError('O ID do modelo deve ter até 200 caracteres e não conter espaços.');
      return;
    }
    setSelected(current => current.includes(id) ? current : [...current, id]);
    setManualId('');
    setError(null);
    setSavedNotice(null);
  };

  const save = async (modelsToSave = selected) => {
    setIsSaving(true);
    setError(null);
    setSavedNotice(null);
    try {
      await apiClient.post(`/sentury/providers/${providerKey}/models`, {
        models: modelsToSave,
        role: papel,
        allow_unlisted: modelsToSave.some(id => !modelById.has(id)),
      }, { headers: authHeaders() });
      setSelected(modelsToSave);
      setSavedNotice(modelsToSave.length
        ? (papel === 'texto' ? 'Ordem salva no Router.' : `Modelos de ${(PAPEL_ROTULO[papel] || papel).toLowerCase()} salvos.`)
        : 'Seleção personalizada removida.');
      await onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="h-full overflow-y-auto px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-stone-200 pb-5">
          <div className="flex items-start gap-3">
            <button type="button" onClick={onBack} className="mt-0.5 rounded-lg border border-stone-200 bg-white p-2 text-zinc-600 hover:border-gold" aria-label="Voltar aos provedores"><ArrowLeft className="h-4 w-4" /></button>
            <ProviderLogo providerKey={providerKey} label={providerLabel} className="h-10 w-10" />
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[.15em] text-gold-ink">Catálogo de modelos</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight">{providerLabel}</h1>
              <p className="mt-1 text-sm text-zinc-500">Escolha por clique. A ordem da seleção é a ordem de tentativa dentro deste provedor.</p>
            </div>
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={() => void loadCatalog(true)} disabled={isLoading} className="inline-flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2 text-xs font-semibold disabled:opacity-40"><RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />Atualizar catálogo</button>
            <button type="button" onClick={() => void save()} disabled={isSaving} className="rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white disabled:opacity-35">{isSaving ? 'Salvando…' : selected.length ? `Salvar ${selected.length}` : 'Salvar (limpar)'}</button>
          </div>
        </header>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className="mr-1 text-[10px] font-bold uppercase tracking-[.12em] text-zinc-400">Para</span>
          {papeisDisponiveis.map(valor => {
            const Icon = PAPEL_ICONE[valor] || Sparkles;
            const n = (porPapel[valor] || []).length;
            return (
              <button
                key={valor}
                type="button"
                onClick={() => { setPapel(valor); setVisibleCount(18); }}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] font-semibold ${papel === valor ? 'border-zinc-800 bg-zinc-900 text-white' : 'border-stone-200 bg-white text-zinc-600'}`}
              >
                <Icon className="h-3 w-3" />
                {PAPEL_ROTULO[valor] || valor}
                {n ? <span className={`rounded-full px-1.5 text-[9px] ${papel === valor ? 'bg-white/20' : 'bg-stone-100'}`}>{n}</span> : null}
              </button>
            );
          })}
          <span className="ml-auto text-[11px] text-zinc-500">
            {papel === 'texto' ? 'A ordem da seleção é a ordem de tentativa.' : 'Escolhido por tarefa, fora da cadeia do Router.'}
          </span>
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_auto]">
          <label className="flex items-center gap-3 rounded-xl border border-stone-300 bg-white px-4 py-3 focus-within:border-gold"><Search className="h-4 w-4 text-zinc-400" /><input value={query} onChange={event => { setQuery(event.target.value); setVisibleCount(18); }} className="w-full bg-transparent text-sm outline-none" placeholder="Buscar pelo nome, ID ou descrição…" /></label>
          <div className="flex flex-wrap gap-2">
            {(['all', 'free', 'paid'] as const).map(value => <button key={value} type="button" onClick={() => setPriceFilter(value)} className={`rounded-lg border px-3 py-2 text-xs font-semibold ${priceFilter === value ? 'border-gold bg-gold-soft text-gold-ink' : 'border-stone-200 bg-white text-zinc-600'}`}>{value === 'all' ? 'Todos' : value === 'free' ? 'Grátis' : 'Pagos'}</button>)}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label className="min-w-52 flex-1"><span className="sr-only">ID manual do modelo</span><input value={manualId} onChange={event => setManualId(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') addManualModel(); }} placeholder="ID de modelo fora da lista" className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs outline-none focus:border-gold" /></label>
          <button type="button" onClick={addManualModel} disabled={!manualId.trim()} className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-semibold disabled:opacity-40">Adicionar ID</button>
          <span className="text-[10px] text-zinc-500">Não verificado: o provedor pode recusá-lo na execução.</span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="mr-1 text-[10px] font-bold uppercase tracking-[.12em] text-zinc-400">Capacidade</span>
          {([
            ['all', Sparkles, 'Todas'],
            ['tools', Wrench, 'Tools'],
            ['vision', Eye, 'Imagem'],
            ['reasoning', Sparkles, 'Raciocínio'],
          ] as const).map(([value, Icon, label]) => <button key={value} type="button" onClick={() => setCapabilityFilter(value)} className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[11px] ${capabilityFilter === value ? 'border-zinc-800 bg-zinc-900 text-white' : 'border-stone-200 bg-white text-zinc-600'}`}><Icon className="h-3 w-3" />{label}</button>)}
          <span className="ml-auto text-[11px] text-zinc-500">{source === 'live' ? 'Dados ao vivo do provedor' : 'Catálogo local de contingência'} · {filtered.length} modelos</span>
        </div>

        {warnings.map(warning => <p key={warning} className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">{warning}</p>)}
        {error && <p className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-800">{error}</p>}
        {savedNotice && <p className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs font-semibold text-emerald-800">{savedNotice}</p>}
        {missingSelected.length > 0 && <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900"><strong>IDs fora do catálogo:</strong> {missingSelected.join(', ')}. Não foram verificados; mantenha-os somente se souber que sua conta os aceita.</div>}

        {selected.length > 0 && <section className="mt-5 rounded-2xl border border-gold bg-gold-soft/60 p-4"><div className="flex items-center justify-between gap-3"><div><h2 className="text-xs font-bold uppercase tracking-[.12em] text-gold-ink">Ordem do Router</h2><p className="mt-1 text-[11px] text-zinc-600">Clique novamente em um modelo para removê-lo.</p></div><button type="button" onClick={() => void save([])} disabled={isSaving} className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-semibold">Usar padrão do provedor</button></div><ol className="mt-3 flex flex-wrap gap-2">{selected.map((id, index) => <li key={id}><button type="button" onClick={() => toggleModel(id)} className={`inline-flex max-w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-[11px] ${modelById.has(id) ? 'border-gold bg-white text-zinc-800' : 'border-red-300 bg-red-50 text-red-800'}`}><span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-[9px] font-bold text-white">{index + 1}</span><span className="truncate">{modelById.get(id)?.name || id}</span></button></li>)}</ol></section>}

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {isLoading && models.length === 0
            ? [1, 2, 3, 4, 5, 6].map(item => <div key={item} className="h-44 animate-pulse rounded-2xl border border-stone-200 bg-white/70" />)
            : filtered.slice(0, visibleCount).map(model => {
              const selectedIndex = selected.indexOf(model.id);
              return <button key={model.id} type="button" onClick={() => toggleModel(model.id)} className={`relative flex min-h-44 flex-col rounded-2xl border p-4 text-left shadow-sm transition ${selectedIndex >= 0 ? 'border-gold bg-gold-soft/45 ring-1 ring-gold' : 'border-stone-200 bg-white/85 hover:border-stone-400'}`}>
                <div className="flex w-full items-start gap-3"><ProviderLogo providerKey={providerKey} label={providerLabel} className="h-8 w-8 shrink-0" /><div className="min-w-0 flex-1"><strong className="block truncate text-sm text-zinc-900">{model.name}</strong><span className="mt-0.5 block truncate font-mono text-[10px] text-zinc-500">{model.id}</span></div>{selectedIndex >= 0 && <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-[10px] font-bold text-white">{selectedIndex + 1}</span>}</div>
                {model.description && <p className="mt-3 line-clamp-2 text-[11px] leading-4 text-zinc-500">{model.description}</p>}
                <div className="mt-auto flex flex-wrap gap-1.5 pt-4"><span className={`rounded-full px-2 py-1 text-[9px] font-bold uppercase ${model.price_class === 'free' ? 'bg-emerald-100 text-emerald-800' : model.price_class === 'paid' ? 'bg-violet-100 text-violet-800' : 'bg-stone-100 text-zinc-600'}`}>{model.price_class === 'free' ? 'Grátis' : model.price_class === 'paid' ? 'Pago' : 'Preço variável'}</span>{model.context_length && <span className="rounded-full bg-stone-100 px-2 py-1 text-[9px] text-zinc-600">Contexto {compactNumber(model.context_length)}</span>}{model.capabilities.map(capability => <span key={capability} className="rounded-full bg-sky-50 px-2 py-1 text-[9px] text-sky-800">{capability === 'vision' ? 'imagem' : capability === 'reasoning' ? 'raciocínio' : capability}</span>)}</div>
                <div className="mt-3 flex items-center gap-1 border-t border-stone-200 pt-2 text-[9px] text-zinc-500"><CircleDollarSign className="h-3 w-3" />entrada/M: {formatPrice(model.pricing.prompt_per_million)} · saída/M: {formatPrice(model.pricing.completion_per_million)}</div>
                {selectedIndex >= 0 && <Check className="absolute right-3 top-3 h-3 w-3 text-white" />}
              </button>;
            })}
        </div>

        {!isLoading && filtered.length === 0 && <p className="py-16 text-center text-sm text-zinc-500">Nenhum modelo corresponde aos filtros.</p>}
        {visibleCount < filtered.length && <button type="button" onClick={() => setVisibleCount(count => count + 18)} className="mx-auto mt-6 flex items-center gap-2 rounded-lg border border-stone-300 bg-white px-4 py-2 text-xs font-semibold"><ChevronDown className="h-4 w-4" />Mostrar mais 18</button>}
      </div>
    </section>
  );
};
