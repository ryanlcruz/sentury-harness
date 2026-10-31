import React, { useCallback, useEffect, useState } from 'react';
import { Check, ChevronDown, CircleAlert, Download, Play, RefreshCw, Search, Square } from 'lucide-react';
import { z } from 'zod';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const EstadoSchema = z.object({
  lmstudio: z.boolean(),
  pasta: z.string(),
  memoria: z.object({ total: z.number(), livre: z.number() }),
  baixados: z.array(z.object({ chave: z.string(), nome: z.string(), repositorio: z.string(), tamanho: z.number(), cabe: z.string() })),
  servidor: z.object({ ligado: z.boolean(), carregados: z.array(z.string()) }).passthrough(),
  escolhido: z.object({ base_url: z.string(), modelo: z.string() }),
  baixando: z.array(z.object({ url: z.string(), estado: z.string(), ultima_linha: z.string() })),
});
type Estado = z.infer<typeof EstadoSchema>;
type Teste = { ok: boolean; resposta?: string; segundos?: number; tokens_por_segundo?: number | null; erro?: string };
type Arquivo = { arquivo: string; tamanho: number; cabe: string };

const opcoes = () => ({ headers: authHeaders() });
const gb = (bytes: number) => `${(bytes / 2 ** 30).toFixed(1).replace('.', ',')} GB`;
const motivo = (erro: unknown) => (erro instanceof Error ? erro.message : 'Não consegui falar com a API.');
const CABE: Record<string, { rotulo: string; classe: string }> = {
  folgado: { rotulo: 'cabe com folga', classe: 'bg-emerald-100 text-emerald-800' },
  apertado: { rotulo: 'cabe apertado', classe: 'bg-amber-100 text-amber-800' },
  pesado: { rotulo: 'pesado para esta máquina', classe: 'bg-red-100 text-red-800' },
  desconhecido: { rotulo: 'tamanho sem comparação', classe: 'bg-stone-100 text-zinc-600' },
};
const Selo: React.FC<{ cabe: string }> = ({ cabe }) => {
  const info = CABE[cabe] || CABE.desconhecido;
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${info.classe}`}>{info.rotulo}</span>;
};
const BOTAO = 'flex items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-xs font-semibold text-zinc-700 hover:border-gold disabled:opacity-50';

/** Os modelos desta máquina: o que já foi baixado, pôr para rodar, testar, usar e achar outros. */
export const ModelosLocaisSection: React.FC = () => {
  const [estado, setEstado] = useState<Estado | null>(null);
  const [ocupado, setOcupado] = useState('');
  const [erro, setErro] = useState('');
  const [saida, setSaida] = useState('');
  const [testes, setTestes] = useState<Record<string, Teste>>({});
  const [termo, setTermo] = useState('');
  const [resultados, setResultados] = useState<Array<{ repositorio: string; downloads: number }> | null>(null);
  const [aberto, setAberto] = useState('');
  const [arquivos, setArquivos] = useState<Record<string, Arquivo[]>>({});

  const carregar = useCallback(async () => {
    try { setEstado(EstadoSchema.parse(await apiClient.get('/sentury/ajustes/modelos-locais', opcoes()))); }
    catch (e) { setErro(motivo(e)); }
  }, []);
  useEffect(() => { void carregar(); }, [carregar]);

  // Enquanto algo baixa, a lista se atualiza sozinha.
  const baixandoAlgo = Boolean(estado?.baixando.some(item => item.estado === 'baixando'));
  useEffect(() => {
    if (!baixandoAlgo) return undefined;
    const vez = window.setInterval(() => void carregar(), 3000);
    return () => window.clearInterval(vez);
  }, [baixandoAlgo, carregar]);

  const agir = async (rotulo: string, acao: () => Promise<unknown>) => {
    setOcupado(rotulo);
    setErro('');
    setSaida('');
    try { await acao(); } catch (e) { setErro(motivo(e)); } finally { setOcupado(''); }
  };

  const rodar = (chave: string) => agir(`rodar:${chave}`, async () => {
    const r = await apiClient.post<{ ok: boolean; saida: string; estado: unknown }>('/sentury/ajustes/modelos-locais/rodar', { modelo: chave }, opcoes());
    setEstado(EstadoSchema.parse(r.estado));
    if (!r.ok) setSaida(r.saida);
  });
  const descarregar = (id: string) => agir(`parar:${id}`, async () => {
    const r = await apiClient.post<{ estado: unknown }>('/sentury/ajustes/modelos-locais/descarregar', { modelo: id }, opcoes());
    setEstado(EstadoSchema.parse(r.estado));
  });
  const testar = (id: string) => agir(`testar:${id}`, async () => {
    const r = await apiClient.post<Teste>('/sentury/ajustes/modelos-locais/testar', { modelo: id }, opcoes());
    setTestes(atual => ({ ...atual, [id]: r }));
  });
  const usar = (id: string) => agir(`usar:${id}`, async () => {
    setEstado(EstadoSchema.parse(await apiClient.put('/sentury/ajustes/modelos-locais/usar', { modelo: id }, opcoes())));
  });
  const buscar = () => agir('buscar', async () => {
    const r = await apiClient.get<{ resultados: Array<{ repositorio: string; downloads: number }> }>(
      `/sentury/ajustes/modelos-locais/procurar?termo=${encodeURIComponent(termo)}`, opcoes());
    setResultados(r.resultados);
    setAberto('');
  });
  const abrir = (repositorio: string) => {
    if (aberto === repositorio) { setAberto(''); return; }
    setAberto(repositorio);
    if (!arquivos[repositorio]) void agir(`arquivos:${repositorio}`, async () => {
      const r = await apiClient.get<{ arquivos: Arquivo[] }>(
        `/sentury/ajustes/modelos-locais/procurar/arquivos?repositorio=${encodeURIComponent(repositorio)}`, opcoes());
      setArquivos(atual => ({ ...atual, [repositorio]: r.arquivos }));
    });
  };
  const baixar = (repositorio: string, arquivo: string) => agir(`baixar:${arquivo}`, async () => {
    const r = await apiClient.post<{ ok: boolean; saida?: string }>('/sentury/ajustes/modelos-locais/baixar', { repositorio, arquivo }, opcoes());
    if (!r.ok) setSaida(r.saida || '');
    await carregar();
  });

  if (!estado) return erro ? <p className="text-sm text-red-700">{erro}</p> : <p className="text-sm text-zinc-500">Lendo os modelos…</p>;
  const emUso = estado.escolhido.modelo;

  return (
    <section>
      <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Modelos locais</p>
      <h2 className="mt-1 text-3xl font-semibold tracking-tight">Rodar um modelo nesta máquina</h2>
      <p className="mt-2 text-sm text-zinc-500">
        O LM Studio roda o modelo; o Sentury mostra o que já foi baixado, põe para rodar, testa e procura outros para baixar.
        Um modelo em uso entra no roteador como "LM Studio (local)" e aparece para escolher no modo Dedicado e no cérebro dos residentes.
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-stone-200 bg-white/80 p-4 text-xs text-zinc-600">
        <span className="flex items-center gap-1.5">{estado.lmstudio ? <Check className="h-4 w-4 text-emerald-700" /> : <CircleAlert className="h-4 w-4 text-amber-700" />}
          {estado.lmstudio ? 'LM Studio instalado' : 'LM Studio não encontrado: instale pelo site lmstudio.ai'}</span>
        <span>Servidor {estado.servidor.ligado ? 'ligado' : 'desligado'}</span>
        <span>Memória {gb(estado.memoria.total)} ({gb(estado.memoria.livre)} livres agora)</span>
        <span className="flex-1" />
        <button type="button" onClick={() => void carregar()} className={BOTAO}><RefreshCw className="h-3.5 w-3.5" />Atualizar</button>
      </div>

      {erro ? <p role="alert" className="mt-3 text-xs text-red-700">{erro}</p> : null}
      {saida ? <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-stone-100 p-3 text-[11px] text-zinc-700">{saida}</pre> : null}

      <h3 className="mt-8 text-sm font-semibold">Em uso no Sentury</h3>
      <div className="mt-2 flex items-center gap-3 rounded-xl border border-stone-200 bg-white/80 p-4 text-sm">
        <span className="flex-1">{emUso ? <><strong>{emUso}</strong> <span className="text-xs text-zinc-500">pelo LM Studio</span></> : <span className="text-zinc-500">Nenhum modelo local em uso.</span>}</span>
        {emUso ? <button type="button" disabled={ocupado !== ''} onClick={() => void usar('')} className={BOTAO}>Parar de usar</button> : null}
      </div>

      <h3 className="mt-8 text-sm font-semibold">Rodando agora</h3>
      {estado.servidor.carregados.length ? (
        <div className="mt-2 overflow-hidden rounded-xl border border-stone-200 bg-white/80">
          {estado.servidor.carregados.map(id => {
            const teste = testes[id];
            return (
              <div key={id} className="border-b border-stone-200 p-4 last:border-b-0">
                <div className="flex flex-wrap items-center gap-2">
                  <strong className="flex-1 text-sm">{id}</strong>
                  <button type="button" disabled={ocupado !== ''} onClick={() => void testar(id)} className={BOTAO}>{ocupado === `testar:${id}` ? 'Testando…' : 'Testar'}</button>
                  {emUso === id ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700">EM USO</span>
                    : <button type="button" disabled={ocupado !== ''} onClick={() => void usar(id)} className="rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">Usar no Sentury</button>}
                  <button type="button" disabled={ocupado !== ''} onClick={() => void descarregar(id)} className={BOTAO} aria-label={`Descarregar ${id}`}><Square className="h-3.5 w-3.5" />Descarregar</button>
                </div>
                {teste ? (teste.ok
                  ? <p className="mt-2 text-xs text-zinc-700">"{teste.resposta}" <span className="text-zinc-500">· {teste.segundos} s{teste.tokens_por_segundo ? ` · ${teste.tokens_por_segundo} tokens/s` : ''}</span></p>
                  : <p className="mt-2 text-xs text-red-700">{teste.erro}</p>) : null}
              </div>
            );
          })}
        </div>
      ) : <p className="mt-2 text-xs text-zinc-500">Nenhum modelo carregado. Escolha um baixado e clique em Rodar.</p>}

      <h3 className="mt-8 text-sm font-semibold">Baixados</h3>
      <p className="mt-1 text-xs text-zinc-500">Na pasta {estado.pasta}.</p>
      {estado.baixados.length ? (
        <div className="mt-2 overflow-hidden rounded-xl border border-stone-200 bg-white/80">
          {estado.baixados.map(modelo => (
            <div key={modelo.chave} className="flex flex-wrap items-center gap-3 border-b border-stone-200 p-4 last:border-b-0">
              <span className="min-w-0 flex-1">
                <strong className="block truncate text-sm">{modelo.nome}</strong>
                <span className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-zinc-500">{modelo.repositorio} · {gb(modelo.tamanho)} <Selo cabe={modelo.cabe} /></span>
              </span>
              <button type="button" disabled={ocupado !== '' || !estado.lmstudio} onClick={() => void rodar(modelo.chave)}
                className="flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">
                <Play className="h-3.5 w-3.5" />{ocupado === `rodar:${modelo.chave}` ? 'Carregando… pode levar um minuto' : 'Rodar'}
              </button>
            </div>
          ))}
        </div>
      ) : <p className="mt-2 text-xs text-zinc-500">Nenhum modelo baixado ainda. Procure um abaixo.</p>}

      <h3 className="mt-8 text-sm font-semibold">Procurar modelos para baixar</h3>
      <p className="mt-1 text-xs text-zinc-500">Modelos abertos, do mais baixado para o menos. Cada arquivo diz se cabe nesta máquina.</p>
      <form className="mt-2 flex gap-2" onSubmit={event => { event.preventDefault(); if (termo.trim()) void buscar(); }}>
        <input value={termo} onChange={event => setTermo(event.target.value)} placeholder="qwen3 4b, gemma, llama…"
          className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-gold" />
        <button type="submit" disabled={!termo.trim() || ocupado !== ''} className={BOTAO}><Search className="h-3.5 w-3.5" />{ocupado === 'buscar' ? 'Buscando…' : 'Buscar'}</button>
      </form>
      {estado.baixando.length ? (
        <div className="mt-3 flex flex-col gap-1.5">
          {estado.baixando.map(item => (
            <p key={item.url} className="text-xs text-zinc-600">
              <strong className="capitalize">{item.estado}</strong> · {item.url.split('/').pop()} {item.ultima_linha ? <span className="text-zinc-400">· {item.ultima_linha}</span> : null}
            </p>
          ))}
        </div>
      ) : null}
      {resultados ? (
        <div className="mt-3 overflow-hidden rounded-xl border border-stone-200 bg-white/80">
          {resultados.length ? resultados.map(item => (
            <div key={item.repositorio} className="border-b border-stone-200 last:border-b-0">
              <button type="button" onClick={() => abrir(item.repositorio)} aria-expanded={aberto === item.repositorio}
                className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-stone-50">
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.repositorio}</span>
                <span className="text-xs tabular-nums text-zinc-500">{item.downloads.toLocaleString('pt-BR')} downloads</span>
                <ChevronDown className={`h-4 w-4 text-zinc-400 transition-transform ${aberto === item.repositorio ? 'rotate-180' : ''}`} />
              </button>
              {aberto === item.repositorio ? (
                <div className="px-4 pb-3">
                  {ocupado === `arquivos:${item.repositorio}` ? <p className="text-xs text-zinc-500">Lendo os arquivos…</p> : null}
                  {(arquivos[item.repositorio] || []).map(arquivo => (
                    <div key={arquivo.arquivo} className="flex flex-wrap items-center gap-2 py-1.5 text-xs">
                      <span className="min-w-0 flex-1 truncate font-mono">{arquivo.arquivo}</span>
                      <span className="tabular-nums text-zinc-500">{gb(arquivo.tamanho)}</span>
                      <Selo cabe={arquivo.cabe} />
                      <button type="button" disabled={ocupado !== '' || !estado.lmstudio} onClick={() => void baixar(item.repositorio, arquivo.arquivo)} className={BOTAO}>
                        <Download className="h-3.5 w-3.5" />Baixar
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          )) : <p className="p-4 text-xs text-zinc-500">Nada encontrado com esse nome.</p>}
        </div>
      ) : null}
    </section>
  );
};
