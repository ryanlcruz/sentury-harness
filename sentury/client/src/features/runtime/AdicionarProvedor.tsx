import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ExternalLink, KeyRound, MonitorSmartphone, Search } from 'lucide-react';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { ProviderLogo } from '../../components/ProviderLogo';

export type ProvedorSemChave = {
  key: string;
  label: string;
  models: string[];
  cost_class: string;
  key_env?: string;
  key_url?: string;
};

type Local = {
  provedor: string; rotulo: string; instalado: boolean; ligado: boolean;
  modelos: string[]; em_uso: string[]; onde_rodar: string;
};

/** Servidores de modelo desta máquina: reconhecidos sozinhos, sem chave. */
const NestaMaquina: React.FC<{ onUsado: () => void }> = ({ onUsado }) => {
  const [locais, setLocais] = useState<Local[] | null>(null);
  const [escolha, setEscolha] = useState<Record<string, string>>({});
  const [salvando, setSalvando] = useState('');
  const [erro, setErro] = useState('');

  const detectar = useCallback(async () => {
    try {
      const lido = await apiClient.get<{ locais: Local[] }>('/sentury/ajustes/locais', { headers: authHeaders() });
      setLocais(lido.locais);
    } catch { setLocais([]); }
  }, []);
  useEffect(() => { void detectar(); }, [detectar]);

  const usar = async (local: Local) => {
    const modelo = escolha[local.provedor] || local.em_uso[0] || local.modelos[0];
    if (!modelo) return;
    setSalvando(local.provedor);
    setErro('');
    try {
      await apiClient.post(`/sentury/providers/${local.provedor}/models`, { models: [modelo], allow_unlisted: true }, { headers: authHeaders() });
      await detectar();
      onUsado();
    } catch (e) { setErro(e instanceof Error ? e.message : 'Não consegui usar este modelo.'); } finally { setSalvando(''); }
  };

  if (!locais?.length) return null;
  return (
    <div className="mb-5">
      <h3 className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-zinc-700"><MonitorSmartphone className="h-3.5 w-3.5" />Nesta máquina</h3>
      <p className="mb-2 text-[11px] leading-5 text-zinc-500">Rodam no seu computador e não pedem chave. O Sentury procura sozinho o que está instalado e ligado.</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {locais.map(local => (
          <article key={local.provedor} className={`rounded-xl border p-3 ${local.instalado ? 'border-stone-200 bg-white/80' : 'border-dashed border-stone-200 bg-white/40'}`}>
            <div className="flex items-center gap-3">
              <ProviderLogo providerKey={local.provedor} label={local.rotulo} className="h-8 w-8 shrink-0" />
              <span className="min-w-0 flex-1">
                <strong className="block truncate text-sm text-zinc-900">{local.rotulo}</strong>
                <span className="block text-[10px] text-zinc-500">
                  {!local.instalado ? 'Não encontrado nesta máquina'
                    : local.ligado ? `Ligado · ${local.modelos.length} ${local.modelos.length === 1 ? 'modelo' : 'modelos'}`
                      : 'Instalado · servidor desligado'}
                </span>
              </span>
              {local.em_uso.length ? <span className="flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[9px] font-bold text-emerald-700"><Check className="h-3 w-3" />EM USO</span> : null}
            </div>
            {local.ligado && local.modelos.length ? (
              <div className="mt-3 flex gap-2 border-t border-stone-100 pt-3">
                <select value={escolha[local.provedor] || local.em_uso[0] || local.modelos[0]} aria-label={`Modelo de ${local.rotulo}`}
                  onChange={event => setEscolha(atual => ({ ...atual, [local.provedor]: event.target.value }))}
                  className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-xs">
                  {local.modelos.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
                <button type="button" disabled={salvando !== ''} onClick={() => void usar(local)}
                  className="rounded-lg bg-zinc-900 px-3 text-[11px] font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">{salvando === local.provedor ? 'Salvando…' : 'Usar'}</button>
              </div>
            ) : local.instalado && local.onde_rodar ? <p className="mt-2 text-[10px] leading-4 text-zinc-500">{local.onde_rodar}</p> : null}
          </article>
        ))}
      </div>
      {erro ? <p className="mt-2 text-[10px] text-red-700">{erro}</p> : null}
    </div>
  );
};

const CUSTO: Record<string, string> = {
  free: 'grátis', free_limited: 'grátis com limite', free_preferred: 'grátis', paid: 'pago', local: 'local',
  subscription: 'assinatura', credits: 'créditos', mixed: 'grátis e pago', none: '',
};

/** O catálogo inteiro do roteador: todo provedor sem chave fica à vista, com a chave colada ali mesmo. */
export const AdicionarProvedor: React.FC<{ provedores: ProvedorSemChave[]; onGuardado: () => void; onAbrirContas: () => void }> = ({ provedores, onGuardado, onAbrirContas }) => {
  const [busca, setBusca] = useState('');
  const [aberto, setAberto] = useState('');
  const [chave, setChave] = useState('');
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');

  // Os locais aparecem em "Nesta máquina", reconhecidos sozinhos; chave só para os que vivem na internet.
  const visiveis = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    return provedores.filter(p => p.cost_class !== 'local')
      .filter(p => !termo || `${p.label} ${p.key} ${p.models.join(' ')}`.toLowerCase().includes(termo));
  }, [provedores, busca]);

  const guardar = async (provedor: ProvedorSemChave) => {
    if (!provedor.key_env || !chave.trim()) return;
    setSalvando(true);
    setErro('');
    try {
      await apiClient.post('/sentury/providers/keys', { key_env: provedor.key_env, valor: chave.trim() }, { headers: authHeaders() });
      setChave('');
      setAberto('');
      onGuardado();
    } catch (e) { setErro(e instanceof Error ? e.message : 'Não consegui guardar a chave.'); } finally { setSalvando(false); }
  };

  return (
    <section>
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-xs font-bold uppercase tracking-[0.13em] text-zinc-800">Adicionar provedor</h2>
        <span className="h-px flex-1 bg-stone-200" />
        <span className="text-[10px] text-zinc-400">{visiveis.length} na internet</span>
      </div>
      <NestaMaquina onUsado={onGuardado} />
      <p className="mb-3 text-[11px] leading-5 text-zinc-500">
        Os da internet pedem chave: cole e ele entra na cadeia na hora. A chave fica no cofre do servidor.
      </p>
      <label className="mb-3 flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2">
        <Search className="h-3.5 w-3.5 text-zinc-400" />
        <input value={busca} onChange={event => setBusca(event.target.value)} placeholder="Procurar: nvidia, groq, mistral…"
          aria-label="Procurar provedor" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
      </label>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {visiveis.map(provedor => (
          <article key={provedor.key} className="rounded-xl border border-stone-200 bg-white/70 p-3">
            <div className="flex items-center gap-3">
              <ProviderLogo providerKey={provedor.key} label={provedor.label} className="h-8 w-8 shrink-0" />
              <span className="min-w-0 flex-1">
                <strong className="block truncate text-sm text-zinc-900">{provedor.label}</strong>
                <span className="block truncate text-[10px] text-zinc-500">
                  {CUSTO[provedor.cost_class] || provedor.cost_class}{provedor.models.length ? ` · ${provedor.models.slice(0, 2).join(', ')}` : ''}
                </span>
              </span>
              {provedor.key_env ? (
                <button type="button" onClick={() => { setAberto(aberto === provedor.key ? '' : provedor.key); setChave(''); setErro(''); }}
                  className="flex items-center gap-1 rounded-md border border-stone-200 px-2 py-1 text-[10px] font-medium text-zinc-600 hover:border-gold hover:text-gold-ink">
                  <KeyRound className="h-3 w-3" />Chave
                </button>
              ) : (
                <button type="button" onClick={onAbrirContas}
                  className="rounded-md border border-stone-200 px-2 py-1 text-[10px] font-medium text-zinc-600 hover:border-gold hover:text-gold-ink">
                  Conectar
                </button>
              )}
            </div>
            {aberto === provedor.key ? (
              <form className="mt-3 border-t border-stone-100 pt-3" onSubmit={event => { event.preventDefault(); void guardar(provedor); }}>
                <span className="flex gap-2">
                  <input type="password" autoComplete="off" value={chave} onChange={event => setChave(event.target.value)} autoFocus
                    placeholder={provedor.key_env} aria-label={`Chave de ${provedor.label}`}
                    className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-2.5 py-1.5 text-xs outline-none focus:border-gold" />
                  <button type="submit" disabled={!chave.trim() || salvando}
                    className="rounded-lg bg-zinc-900 px-3 text-[11px] font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">{salvando ? 'Guardando…' : 'Guardar'}</button>
                </span>
                {provedor.key_url ? (
                  <a href={provedor.key_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[10px] font-medium text-gold-ink hover:underline">
                    Criar a chave no site<ExternalLink className="h-3 w-3" />
                  </a>
                ) : null}
                {erro ? <p className="mt-2 text-[10px] text-red-700">{erro}</p> : null}
              </form>
            ) : null}
          </article>
        ))}
        {!visiveis.length ? <p className="text-xs text-zinc-500">Nenhum provedor com esse nome.</p> : null}
      </div>
    </section>
  );
};
