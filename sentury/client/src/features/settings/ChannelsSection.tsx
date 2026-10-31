import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Bot, Globe, PhoneCall, RefreshCw, Radio, Search } from 'lucide-react';
import { z } from 'zod';
import { Toggle } from '../../components/Toggle';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { setVoiceCallEnabled, useVoiceCallEnabled } from '../../runtime/preferences';
import { apiClient } from '../../transport/http-client';
import { VozConfig } from './VozConfig';

const CampoSchema = z.object({
  name: z.string(),
  label: z.string(),
  type: z.enum(['text', 'secret']).catch('text'),
  required: z.boolean().default(false),
  placeholder: z.string().optional(),
  hint: z.string().optional(),
});

const CanalSchema = z.object({
  id: z.string(),
  label: z.string(),
  categoria: z.string().default('outros'),
  transport: z.string(),
  description: z.string(),
  configurable: z.boolean().default(false),
  implemented: z.boolean().default(true),
  fields: z.array(CampoSchema).default([]),
  actions: z.array(z.string()).default([]),
  available: z.boolean().default(false),
  configured: z.boolean().default(false),
  status: z.string().default('desconhecido'),
  active: z.boolean().optional(),
  motivo: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
  values: z.record(z.string(), z.string()).default({}),
}).passthrough();

type Canal = z.infer<typeof CanalSchema>;

const ICONES: Record<string, typeof Bot> = { telegram: Bot, web: Globe, voz: PhoneCall };

const TRANSPORTE: Record<string, string> = {
  http: 'HTTP',
  long_polling: 'long polling',
  websocket: 'WebSocket',
  webhook: 'webhook',
};

const CATEGORIA: Record<string, string> = {
  aplicacao: 'Aplicação',
  mensageria: 'Mensageria',
  voz: 'Voz',
  email: 'E-mail',
  automacao: 'Automação',
  outros: 'Outros',
};

function situacao(canal: Canal): { rotulo: string; classe: string; ponto: string } {
  if (!canal.implemented) return { rotulo: 'EM PREPARO', classe: 'bg-stone-200 text-zinc-600', ponto: 'bg-stone-300' };
  if (!canal.available) return { rotulo: 'INDISPONÍVEL', classe: 'bg-stone-200 text-zinc-600', ponto: 'bg-stone-300' };
  if (canal.active) return { rotulo: 'ATIVO', classe: 'bg-emerald-100 text-emerald-700', ponto: 'bg-emerald-500' };
  if (canal.configurable && canal.configured) return { rotulo: 'CONFIGURADO · PARADO', classe: 'bg-amber-100 text-amber-700', ponto: 'bg-amber-400' };
  if (canal.configurable) return { rotulo: 'NÃO CONFIGURADO', classe: 'bg-stone-200 text-zinc-600', ponto: 'bg-stone-300' };
  return { rotulo: 'PRONTO', classe: 'bg-emerald-100 text-emerald-700', ponto: 'bg-emerald-500' };
}

export const ChannelsSection: React.FC = () => {
  const [canais, setCanais] = useState<Canal[]>([]);
  const [selecionado, setSelecionado] = useState<string>('');
  const [busca, setBusca] = useState('');
  const [rascunho, setRascunho] = useState<Record<string, string>>({});
  const [mensagem, setMensagem] = useState('');
  const [salvando, setSalvando] = useState(false);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState('');
  const vozLigada = useVoiceCallEnabled();

  const load = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setLoading(true);
    setErro('');
    try {
      const dados = z.object({ canais: z.array(CanalSchema) })
        .parse(await apiClient.get('/sentury/channels', { headers: authHeaders() }));
      setCanais(dados.canais);
      setSelecionado(atual => atual || dados.canais.find(c => c.configurable)?.id || dados.canais[0]?.id || '');
    } catch (reason) {
      setErro(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const canal = useMemo(() => canais.find(item => item.id === selecionado), [canais, selecionado]);

  const filtrados = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    if (!termo) return canais;
    return canais.filter(item =>
      item.label.toLowerCase().includes(termo)
      || item.description.toLowerCase().includes(termo)
      || (CATEGORIA[item.categoria] || item.categoria).toLowerCase().includes(termo));
  }, [canais, busca]);

  // Conectado primeiro: com muitos canais, o que já funciona é o que se procura.
  const grupos = useMemo(() => {
    const ativos = filtrados.filter(item => item.active || (!item.configurable && item.available));
    const restantes = filtrados.filter(item => !ativos.includes(item));
    const porCategoria = new Map<string, Canal[]>();
    restantes.forEach(item => {
      const chave = CATEGORIA[item.categoria] || item.categoria;
      porCategoria.set(chave, [...(porCategoria.get(chave) || []), item]);
    });
    return [
      ...(ativos.length ? [['Em uso', ativos] as const] : []),
      ...Array.from(porCategoria.entries()).sort(([a], [b]) => a.localeCompare(b, 'pt-BR')),
    ];
  }, [filtrados]);

  useEffect(() => {
    if (!canal) return;
    const inicial: Record<string, string> = {};
    canal.fields.forEach(campo => {
      inicial[campo.name] = campo.type === 'secret' ? '' : (canal.values[campo.name] || '');
    });
    setRascunho(inicial);
    setMensagem('');
  }, [canal?.id, canais]);

  const aplicar = async (proximoAtivo: boolean) => {
    if (!canal) return;
    setSalvando(true);
    setMensagem(proximoAtivo && !canal.active ? 'Iniciando…' : !proximoAtivo && canal.active ? 'Parando…' : 'Salvando…');
    try {
      const corpo: Record<string, unknown> = { active: proximoAtivo };
      canal.fields.forEach(campo => {
        const valor = (rascunho[campo.name] || '').trim();
        corpo[campo.name] = campo.type === 'secret' ? (valor || null) : valor;
      });
      await apiClient.post(`/sentury/channels/${encodeURIComponent(canal.id)}/config`, corpo, { headers: authHeaders() });
      setMensagem('Aplicado.');
      await load();
    } catch (reason) {
      setMensagem(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSalvando(false);
    }
  };

  const emUso = canais.filter(item => item.active || (!item.configurable && item.available)).length;

  return (
    <section>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Canais</p>
          <h2 className="mt-1 text-3xl font-semibold tracking-tight">Por onde a Sentury atende</h2>
          <p className="mt-2 text-sm text-zinc-500">
            {emUso} de {canais.length} em uso. Cada canal tem o próprio jeito de configurar.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded-lg border border-stone-300 bg-white p-2 text-zinc-600"
          title="Atualizar canais"
          aria-label="Atualizar canais"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {erro ? <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-xs text-red-700">{erro}</p> : null}

      <div className="mt-6 grid gap-5 md:grid-cols-[240px_minmax(0,1fr)]">
        <div className="min-w-0">
          <label className="relative block">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-400" />
            <input
              value={busca}
              onChange={event => setBusca(event.target.value)}
              placeholder="Buscar canal"
              aria-label="Buscar canal"
              className="w-full rounded-lg border border-stone-300 bg-white py-2 pl-8 pr-3 text-xs outline-none focus:border-gold"
            />
          </label>

          <div className="sentury-scroll mt-3 max-h-[26rem] space-y-4 overflow-y-auto pr-1">
            {grupos.map(([titulo, itens]) => (
              <div key={titulo}>
                <p className="px-1 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-zinc-400">{titulo}</p>
                <div className="space-y-1">
                  {itens.map(item => {
                    const Icon = ICONES[item.id] || Radio;
                    const estado = situacao(item);
                    const ativo = canal?.id === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setSelecionado(item.id)}
                        className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${ativo ? 'bg-zinc-900 text-white' : 'text-zinc-700 hover:bg-white'}`}
                      >
                        <Icon className={`h-3.5 w-3.5 shrink-0 ${ativo ? 'text-gold' : 'text-zinc-400'}`} />
                        <span className="min-w-0 flex-1">
                          <strong className="block truncate text-xs">{item.label}</strong>
                          <span className={`block truncate text-[9px] uppercase tracking-wider ${ativo ? 'text-zinc-400' : 'text-zinc-400'}`}>
                            {TRANSPORTE[item.transport] || item.transport}
                          </span>
                        </span>
                        <span className={`h-2 w-2 shrink-0 rounded-full ${estado.ponto}`} />
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
            {!filtrados.length && !loading ? (
              <p className="px-1 text-xs text-zinc-500">Nenhum canal corresponde à busca.</p>
            ) : null}
          </div>
        </div>

        {canal ? (
          <div className="min-w-0 rounded-2xl border border-stone-200 bg-white/80 p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-stone-200 pb-4">
              <div className="flex items-start gap-3">
                <span className="rounded-xl bg-gold-soft p-3 text-gold-ink">
                  {React.createElement(ICONES[canal.id] || Radio, { className: 'h-5 w-5' })}
                </span>
                <div>
                  <h3 className="text-sm font-semibold">{canal.label}</h3>
                  <p className="mt-1 max-w-md text-xs leading-5 text-zinc-500">{canal.description}</p>
                </div>
              </div>
              <span className={`rounded-full px-3 py-1.5 text-[10px] font-bold ${situacao(canal).classe}`}>{situacao(canal).rotulo}</span>
            </div>

            {canal.motivo ? (
              <p className="mt-4 rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs text-zinc-600">{canal.motivo}</p>
            ) : null}

            {canal.fields.length > 0 ? (
              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                {canal.fields.map(campo => (
                  <label key={campo.name} className="block">
                    <span className="text-xs font-semibold">{campo.label}</span>
                    <input
                      type={campo.type === 'secret' ? 'password' : 'text'}
                      value={rascunho[campo.name] ?? ''}
                      onChange={event => setRascunho(atual => ({ ...atual, [campo.name]: event.target.value }))}
                      placeholder={campo.type === 'secret' && canal.configured ? 'Deixe vazio para preservar o atual' : campo.placeholder}
                      className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-gold"
                    />
                    {campo.hint ? <span className="mt-1.5 block text-[10px] text-zinc-400">{campo.hint}</span> : null}
                  </label>
                ))}
              </div>
            ) : null}

            {canal.id === 'voz' ? (
              <div className="mt-5 flex items-center gap-3 rounded-lg border border-stone-200 p-4">
                <PhoneCall className="h-4 w-4 text-gold-hover" />
                <span className="min-w-0 flex-1">
                  <strong className="block text-xs">Oferecer ligação por voz</strong>
                  <span className="mt-0.5 block text-[10px] text-zinc-500">
                    {canal.available
                      ? `Modelo ${canal.model || 'de voz'} disponível. Com isto ligado, a conversa ganha o botão de chamada.`
                      : 'Só pode ser ligado quando houver um modelo com áudio bidirecional.'}
                  </span>
                </span>
                <Toggle
                  label="Oferecer ligação por voz"
                  checked={vozLigada && canal.available}
                  disabled={!canal.available}
                  onChange={setVoiceCallEnabled}
                />
              </div>
            ) : null}
            {canal.id === 'voz' && canal.available ? <VozConfig /> : null}

            {canal.configurable ? (
              <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-stone-200 pt-4">
                <button
                  type="button"
                  disabled={salvando}
                  onClick={() => void aplicar(Boolean(canal.active))}
                  className="rounded-lg border border-stone-300 bg-white px-4 py-2 text-xs font-semibold text-zinc-700 hover:border-gold disabled:opacity-50"
                >
                  Salvar acesso
                </button>
                {canal.actions.includes('start') ? (
                  <button
                    type="button"
                    disabled={salvando}
                    onClick={() => void aplicar(!canal.active)}
                    className={`rounded-lg px-4 py-2 text-xs font-semibold text-white disabled:opacity-50 ${canal.active ? 'bg-red-600 hover:bg-red-700' : 'bg-zinc-900 hover:bg-zinc-800'}`}
                  >
                    {salvando ? 'Aplicando…' : canal.active ? 'Parar canal' : 'Iniciar canal'}
                  </button>
                ) : null}
                {mensagem ? <span className="text-xs text-zinc-500">{mensagem}</span> : null}
              </div>
            ) : (
              <p className="mt-5 border-t border-stone-200 pt-4 text-[11px] text-zinc-500">
                Este canal não tem configuração própria; ele acompanha o estado do servidor.
              </p>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
};
