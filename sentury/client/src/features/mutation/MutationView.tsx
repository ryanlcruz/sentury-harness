import React, { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Check, Copy, Dna, Eye, FlaskConical, GitBranch, GitMerge, RefreshCw, Sparkles, TriangleAlert, Undo2, X } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const ResumoSchema = z.object({
  id: z.string(),
  alvo: z.string(),
  estado: z.string(),
  hipotese: z.string().default(''),
  branch: z.string().default(''),
  copia: z.string().default(''),
  motivo: z.string().default(''),
  fitness: z.record(z.unknown()).default({}),
});

const ListaSchema = z.object({
  mutacoes: z.array(ResumoSchema).default([]),
  medindo: z.string().nullable().optional(),
  arvore_limpa: z.boolean().default(true),
  baseline: z.string().default(''),
  portoes: z.array(z.string()).default([]),
});

const DetalheSchema = z.object({
  id: z.string(),
  alvo: z.string(),
  estado: z.string(),
  hipotese: z.string().default(''),
  observacao: z.string().default(''),
  baseline_commit: z.string().default(''),
  branch: z.string().default(''),
  motivo: z.string().default(''),
  fitness: z.record(z.unknown()).default({}),
  eventos: z.array(z.object({
    tipo: z.string().default(''),
    detalhe: z.string().default(''),
    em: z.number().optional(),
  }).passthrough()).default([]),
  diff: z.object({
    caminho: z.string().default(''),
    alterados: z.array(z.string()).default([]),
    novos: z.array(z.string()).default([]),
    patch: z.string().default(''),
    patch_cortado: z.boolean().default(false),
  }).nullable().optional(),
  medindo: z.boolean().default(false),
});

type Detalhe = z.infer<typeof DetalheSchema>;

const SinalSchema = z.object({
  id: z.string(),
  ferramenta: z.string(),
  tipo: z.string().default(''),
  vezes: z.number().default(0),
  pedido: z.string().default(''),
  erro: z.string().default(''),
});

const RascunhoSchema = z.object({
  alvo: z.string(),
  hipotese: z.string(),
  observacao: z.string().default(''),
  pelo_modelo: z.boolean().default(false),
});

type Rascunho = z.infer<typeof RascunhoSchema>;

// O ciclo, na ordem em que a pessoa o percorre. Os terminais ficam no fim.
const ESTADOS: Array<{ id: string; nome: string; tom: string }> = [
  { id: 'proposta', nome: 'Proposta', tom: 'border-stone-300 bg-white text-zinc-600' },
  { id: 'candidata', nome: 'Candidata', tom: 'border-sky-200 bg-sky-50 text-sky-800' },
  { id: 'em_avaliacao', nome: 'Medindo', tom: 'border-amber-200 bg-amber-50 text-amber-800' },
  { id: 'aprovada', nome: 'Aprovada nos portões', tom: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  { id: 'promovida', nome: 'Promovida', tom: 'border-emerald-300 bg-emerald-100 text-emerald-900' },
  { id: 'rejeitada', nome: 'Rejeitada', tom: 'border-red-200 bg-red-50 text-red-700' },
  { id: 'revertida', nome: 'Revertida', tom: 'border-red-200 bg-red-50 text-red-700' },
  { id: 'descartada', nome: 'Descartada', tom: 'border-stone-200 bg-stone-50 text-zinc-500' },
];

const estado = (id: string) => ESTADOS.find(item => item.id === id) || ESTADOS[0];

const Selo: React.FC<{ id: string }> = ({ id }) => (
  <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${estado(id).tom}`}>
    {estado(id).nome}
  </span>
);

function erroDe(causa: unknown): string {
  const texto = causa instanceof Error ? causa.message : String(causa);
  const detalhe = texto.match(/"detail"\s*:\s*"([^"]+)"/);
  return detalhe ? detalhe[1] : texto;
}

function numero(valor: unknown, campo: string): number {
  return valor && typeof valor === 'object' ? Number((valor as Record<string, unknown>)[campo] || 0) : 0;
}

const Portao: React.FC<{ nome: string; valor: unknown }> = ({ nome, valor }) => {
  const ok = Boolean(valor && typeof valor === 'object' && (valor as Record<string, unknown>).ok);
  const linha = nome === 'suite'
    ? `${numero(valor, 'passaram')} passaram, ${numero(valor, 'falharam')} falharam`
    : nome === 'replay'
      ? `${numero(valor, 'iguais')} iguais, ${numero(valor, 'mudaram')} mudaram, ${numero(valor, 'falharam')} falharam`
      : `${numero(valor, 'passaram')}/${numero(valor, 'total')} casos reais`;
  const titulo = { suite: 'Suíte', replay: 'Replay contra a produção', evals: 'Evals dos traços' }[nome] || nome;
  return (
    <article className={`rounded-xl border p-3 ${ok ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'}`}>
      <p className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
        {ok ? <Check className="h-3 w-3 text-emerald-700" /> : <X className="h-3 w-3 text-red-700" />}{titulo}
      </p>
      <p className="mt-1 text-sm font-medium tabular-nums">{linha}</p>
      <p className="text-[11px] text-zinc-500">{numero(valor, 'segundos')}s</p>
    </article>
  );
};

export const MutationView: React.FC = () => {
  const [lista, setLista] = useState<z.infer<typeof ListaSchema> | null>(null);
  const [aberta, setAberta] = useState<string | null>(null);
  const [detalhe, setDetalhe] = useState<Detalhe | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState('');
  const [frase, setFrase] = useState('');
  const [sinais, setSinais] = useState<Array<z.infer<typeof SinalSchema>>>([]);
  const [rascunho, setRascunho] = useState<Rascunho | null>(null);
  const [ajustar, setAjustar] = useState(false);
  const [razao, setRazao] = useState('');

  const carregar = useCallback(async () => {
    apiClient.setBaseUrl(getRuntimeConfig().apiUrl);
    setCarregando(true);
    try {
      setLista(ListaSchema.parse(await apiClient.get('/sentury/mutacoes', { headers: authHeaders() })));
      const vistos = await apiClient.get('/sentury/mutacoes/sinais', { headers: authHeaders() }) as { sinais?: unknown[] };
      setSinais(z.array(SinalSchema).parse(vistos?.sinais || []));
      if (aberta) setDetalhe(DetalheSchema.parse(await apiClient.get(`/sentury/mutacoes/${aberta}`, { headers: authHeaders() })));
    } catch (causa) {
      setErro(erroDe(causa));
    } finally {
      setCarregando(false);
    }
  }, [aberta]);

  useEffect(() => { void carregar(); }, [carregar]);

  // A medição leva minutos: enquanto houver uma, a tela pergunta de novo.
  const medindo = Boolean(lista?.medindo) || (lista?.mutacoes || []).some(m => m.estado === 'em_avaliacao');
  useEffect(() => {
    if (!medindo) return undefined;
    const vez = window.setInterval(() => { void carregar(); }, 4000);
    return () => window.clearInterval(vez);
  }, [medindo, carregar]);

  const agir = async (caminho: string, corpo: Record<string, string> = {}) => {
    setOcupado(true);
    setErro('');
    try {
      await apiClient.post(caminho, corpo, { headers: authHeaders() });
      setRazao('');
      await carregar();
    } catch (causa) {
      setErro(erroDe(causa));
    } finally {
      setOcupado(false);
    }
  };

  const preparar = async (corpo: { texto?: string; sinal?: string }) => {
    setOcupado(true);
    setErro('');
    setAjustar(false);
    try {
      const modo = getRuntimeConfig().mode;
      setRascunho(RascunhoSchema.parse(await apiClient.post('/sentury/mutacoes/rascunho', { ...corpo, modo }, { headers: authHeaders() })));
    } catch (causa) {
      setErro(erroDe(causa));
    } finally {
      setOcupado(false);
    }
  };

  const propor = async () => {
    if (!rascunho) return;
    setOcupado(true);
    setErro('');
    try {
      const criada = await apiClient.post('/sentury/mutacoes', {
        alvo: rascunho.alvo, hipotese: rascunho.hipotese, observacao: rascunho.observacao,
      }, { headers: authHeaders() }) as { id?: string };
      setRascunho(null);
      setFrase('');
      if (criada?.id) setAberta(criada.id);
      else await carregar();
    } catch (causa) {
      setErro(erroDe(causa));
    } finally {
      setOcupado(false);
    }
  };

  const base = detalhe ? `/sentury/mutacoes/${detalhe.id}` : '';
  const campo = 'w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-zinc-500';
  const botao = 'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold disabled:opacity-40';

  return (
    <section className="h-full overflow-y-auto px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Evolução do Sentury</p>
            <h1 className="mt-2 flex items-center gap-2 text-2xl font-semibold"><Dna className="h-6 w-6" />Mutação</h1>
            <p className="mt-1 max-w-2xl text-sm text-zinc-500">
              Cada mudança no próprio Sentury nasce numa cópia isolada, passa pela suíte, pelo replay contra a
              produção e pelos evals, e só entra com a sua decisão. O que não passou fica registrado como evidência.
            </p>
          </div>
          <button type="button" onClick={() => void carregar()} aria-label="Atualizar"
            className="rounded-lg border border-stone-300 bg-white p-2">
            <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} />
          </button>
        </header>

        {erro ? <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{erro}</p> : null}

        <form className="mt-6 flex items-center gap-2 rounded-2xl border border-stone-300 bg-white p-2 shadow-sm"
          onSubmit={evento => { evento.preventDefault(); if (frase.trim()) void preparar({ texto: frase }); }}>
          <Sparkles className="ml-2 h-4 w-4 shrink-0 text-gold-ink" />
          <input className="min-w-0 flex-1 bg-transparent px-1 py-2 text-sm outline-none"
            placeholder="O que você quer que o Sentury melhore em si mesmo?"
            value={frase} onChange={evento => setFrase(evento.target.value)} />
          <button type="submit" disabled={ocupado || !frase.trim()} className={`${botao} bg-zinc-900 py-2 text-white`}>
            Preparar<ArrowRight className="h-3.5 w-3.5" />
          </button>
        </form>

        {rascunho ? (
          <div className="mt-4 rounded-2xl border border-zinc-300 bg-white p-5">
            <p className="text-[10px] font-bold uppercase tracking-[.16em] text-zinc-400">
              {rascunho.pelo_modelo ? 'Rascunho do Sentury' : 'Rascunho'}
            </p>
            {ajustar ? (
              <div className="mt-2 space-y-2">
                <input className={campo} value={rascunho.alvo} aria-label="Alvo"
                  onChange={evento => setRascunho({ ...rascunho, alvo: evento.target.value })} />
                <textarea className={`${campo} min-h-[64px]`} value={rascunho.hipotese} aria-label="Hipótese"
                  onChange={evento => setRascunho({ ...rascunho, hipotese: evento.target.value })} />
                <textarea className={`${campo} min-h-[48px]`} value={rascunho.observacao} aria-label="O que motivou"
                  onChange={evento => setRascunho({ ...rascunho, observacao: evento.target.value })} />
              </div>
            ) : (
              <>
                <h2 className="mt-1 text-lg font-semibold">{rascunho.alvo}</h2>
                <p className="mt-1 text-sm text-zinc-700">{rascunho.hipotese}</p>
                {rascunho.observacao ? <p className="mt-1 text-xs text-zinc-500">Motivou: {rascunho.observacao}</p> : null}
              </>
            )}
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button type="button" disabled={ocupado || !lista?.arvore_limpa || !rascunho.alvo.trim() || !rascunho.hipotese.trim()}
                onClick={() => void propor()} className={`${botao} bg-zinc-900 py-2 text-white`}>
                <GitBranch className="h-3.5 w-3.5" />Testar numa cópia isolada
              </button>
              <button type="button" onClick={() => setAjustar(valor => !valor)} className={`${botao} border border-stone-300 bg-white py-2`}>
                {ajustar ? 'Pronto' : 'Ajustar'}
              </button>
              <button type="button" onClick={() => setRascunho(null)} className={`${botao} py-2 text-zinc-500`}>Deixar para lá</button>
              {lista && !lista.arvore_limpa ? (
                <span className="flex items-center gap-1.5 text-xs text-amber-800">
                  <TriangleAlert className="h-3.5 w-3.5" />Antes, commite ou guarde o que está aberto na pasta do Sentury.
                </span>
              ) : null}
            </div>
          </div>
        ) : null}

        {sinais.length ? (
          <div className="mt-6">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500"><Eye className="h-3.5 w-3.5" />O que o Sentury notou no uso</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {sinais.map(sinal => (
                <article key={sinal.id} className="flex flex-col rounded-xl border border-stone-200 bg-white/80 p-4">
                  <p className="text-sm font-medium">
                    <span className="font-mono">{sinal.ferramenta}</span> falhou {sinal.vezes === 1 ? 'uma vez' : `${sinal.vezes} vezes`}
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs text-zinc-600">{sinal.erro}</p>
                  {sinal.pedido ? <p className="mt-1 line-clamp-1 text-[11px] text-zinc-400">Pedido: {sinal.pedido}</p> : null}
                  <button type="button" disabled={ocupado} onClick={() => void preparar({ sinal: sinal.id })}
                    className={`${botao} mt-3 self-start border border-stone-300 bg-white`}>
                    Investigar<ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </article>
              ))}
            </div>
          </div>
        ) : null}

        {(lista?.mutacoes || []).length ? (
        <div className="mt-8 grid gap-5 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          <div className="space-y-2">
            {(lista?.mutacoes || []).slice().reverse().map(item => (
              <button key={item.id} type="button" onClick={() => setAberta(item.id)}
                className={`block w-full rounded-xl border p-3 text-left transition-colors ${
                  aberta === item.id ? 'border-zinc-500 bg-white' : 'border-stone-200 bg-white/70 hover:bg-white'
                }`}>
                <span className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-zinc-500">{item.id}</span><Selo id={item.estado} />
                </span>
                <span className="mt-1 block truncate text-sm font-medium">{item.alvo}</span>
                <span className="mt-0.5 line-clamp-2 block text-xs text-zinc-500">{item.hipotese}</span>
              </button>
            ))}
          </div>

          {detalhe ? (
            <div className="min-w-0 space-y-4 rounded-xl border border-stone-200 bg-white/85 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-mono text-[11px] text-zinc-500">{detalhe.id}</p>
                  <h2 className="text-lg font-semibold">{detalhe.alvo}</h2>
                </div>
                <Selo id={detalhe.estado} />
              </div>
              <p className="text-sm text-zinc-700">{detalhe.hipotese}</p>
              {detalhe.observacao ? <p className="text-xs text-zinc-500">Motivou: {detalhe.observacao}</p> : null}
              {detalhe.motivo ? <p className="rounded-lg bg-stone-100 p-3 text-xs text-zinc-600">Motivo: {detalhe.motivo}</p> : null}

              <dl className="grid gap-2 text-xs sm:grid-cols-2">
                <div><dt className="text-zinc-400">Partiu de</dt><dd className="font-mono">{detalhe.baseline_commit.slice(0, 10) || '—'}</dd></div>
                <div><dt className="text-zinc-400">Branch</dt><dd className="truncate font-mono">{detalhe.branch || '—'}</dd></div>
                {detalhe.diff?.caminho ? (
                  <div className="sm:col-span-2">
                    <dt className="text-zinc-400">Cópia isolada (é aqui que a mudança é feita)</dt>
                    <dd className="flex items-center gap-2">
                      <span className="truncate font-mono">{detalhe.diff.caminho}</span>
                      <button type="button" aria-label="Copiar caminho" onClick={() => void navigator.clipboard.writeText(detalhe.diff?.caminho || '')}
                        className="rounded border border-stone-300 p-1"><Copy className="h-3 w-3" /></button>
                    </dd>
                  </div>
                ) : null}
              </dl>

              {Object.keys(detalhe.fitness).length ? (
                <div className="space-y-2">
                  <div className="grid gap-2 sm:grid-cols-3">
                    {(lista?.portoes || []).map(nome => <Portao key={nome} nome={nome} valor={detalhe.fitness[nome]} />)}
                  </div>
                  {Array.isArray(detalhe.fitness.mexe_em_teste) && detalhe.fitness.mexe_em_teste.length ? (
                    <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                      <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      A mutação mexe em teste ({(detalhe.fitness.mexe_em_teste as string[]).join(', ')}). Os portões rodaram
                      com esses testes; confira no diff se nenhum foi afrouxado.
                    </p>
                  ) : null}
                </div>
              ) : null}

              <div className="flex flex-wrap items-center gap-2 border-t border-stone-200 pt-4">
                {detalhe.estado === 'proposta' ? (
                  <button type="button" disabled={ocupado} onClick={() => void agir(`${base}/construida`)}
                    className={`${botao} bg-zinc-900 text-white`}><Check className="h-3.5 w-3.5" />Pronta para medir</button>
                ) : null}
                {detalhe.estado === 'candidata' ? (
                  <button type="button" disabled={ocupado || Boolean(lista?.medindo)} onClick={() => void agir(`${base}/medir`)}
                    className={`${botao} bg-zinc-900 text-white`}><FlaskConical className="h-3.5 w-3.5" />Medir nos portões</button>
                ) : null}
                {detalhe.estado === 'em_avaliacao' ? (
                  <span className="inline-flex items-center gap-2 text-xs text-amber-800">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />Medindo na cópia: suíte, replay e evals. Leva alguns minutos.
                  </span>
                ) : null}
                {['proposta', 'candidata', 'aprovada', 'promovida'].includes(detalhe.estado) ? (
                  <input className={`${campo} max-w-xs py-1.5 text-xs`} value={razao} onChange={evento => setRazao(evento.target.value)}
                    placeholder={detalhe.estado === 'aprovada' ? 'Seu nome para promover, ou o motivo para rejeitar' : 'Motivo'} />
                ) : null}
                {detalhe.estado === 'aprovada' ? (
                  <>
                    <button type="button" disabled={ocupado || !razao.trim()} onClick={() => void agir(`${base}/promover`, { decidido_por: razao })}
                      className={`${botao} bg-emerald-700 text-white`}><GitMerge className="h-3.5 w-3.5" />Promover</button>
                    <button type="button" disabled={ocupado || !razao.trim()} onClick={() => void agir(`${base}/rejeitar`, { motivo: razao })}
                      className={`${botao} border border-red-300 bg-white text-red-700`}><X className="h-3.5 w-3.5" />Rejeitar</button>
                  </>
                ) : null}
                {['proposta', 'candidata'].includes(detalhe.estado) ? (
                  <button type="button" disabled={ocupado || !razao.trim()} onClick={() => void agir(`${base}/descartar`, { motivo: razao })}
                    className={`${botao} border border-stone-300 bg-white`}><X className="h-3.5 w-3.5" />Descartar</button>
                ) : null}
                {detalhe.estado === 'promovida' ? (
                  <button type="button" disabled={ocupado || !razao.trim()} onClick={() => void agir(`${base}/reverter`, { motivo: razao })}
                    className={`${botao} border border-red-300 bg-white text-red-700`}><Undo2 className="h-3.5 w-3.5" />Reverter</button>
                ) : null}
                {['rejeitada', 'revertida'].includes(detalhe.estado) && detalhe.diff ? (
                  <button type="button" disabled={ocupado} onClick={() => void agir(`${base}/limpar`)}
                    className={`${botao} border border-stone-300 bg-white`}>Apagar a cópia (o branch fica)</button>
                ) : null}
              </div>
              {detalhe.estado === 'promovida' && detalhe.branch ? (
                <p className="text-xs text-zinc-500">
                  Promover registra a decisão; o código entra no Sentury quando você juntar o branch:
                  <code className="ml-1 rounded bg-stone-100 px-1.5 py-0.5 font-mono">git merge {detalhe.branch}</code>
                </p>
              ) : null}

              {detalhe.diff ? (
                <details className="rounded-lg border border-stone-200" open={Boolean(detalhe.diff.patch)}>
                  <summary className="cursor-pointer px-3 py-2 text-xs font-semibold">
                    Diff: {detalhe.diff.alterados.length} alterado(s), {detalhe.diff.novos.length} novo(s)
                  </summary>
                  {detalhe.diff.novos.length ? (
                    <p className="px-3 pb-2 text-xs text-zinc-500">Novos: {detalhe.diff.novos.join(', ')}</p>
                  ) : null}
                  {detalhe.diff.patch ? (
                    <pre className="max-h-[420px] overflow-auto border-t border-stone-200 bg-stone-50 p-3 font-mono text-[11px] leading-relaxed">
                      {detalhe.diff.patch}{detalhe.diff.patch_cortado ? '\n[o diff continua; abra a cópia para ver o resto]' : ''}
                    </pre>
                  ) : <p className="px-3 pb-3 text-xs text-zinc-500">A cópia ainda não mudou nada.</p>}
                </details>
              ) : null}

              {detalhe.eventos.length ? (
                <ol className="space-y-1 border-t border-stone-200 pt-3 text-xs">
                  {detalhe.eventos.slice().reverse().map((evento, indice) => (
                    <li key={indice} className="flex gap-2">
                      <span className="shrink-0 text-zinc-400">{evento.em ? new Date(evento.em * 1000).toLocaleString('pt-BR') : ''}</span>
                      <span className="font-medium">{evento.tipo}</span>
                      <span className="truncate text-zinc-500">{evento.detalhe.split('\n').slice(-1)[0]}</span>
                    </li>
                  ))}
                </ol>
              ) : null}
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-stone-300 p-5 text-sm text-zinc-500">
              Escolha uma mutação para ver a hipótese, o diff, a medição e as decisões.
            </p>
          )}
        </div>
        ) : null}
      </div>
    </section>
  );
};
