import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { CalendarDays, ClipboardList, MapPin, RefreshCw, User2, X } from 'lucide-react';
import { ResizeHandle } from '../../components/ResizeHandle';
import { proximaMarca, renderMarkdown } from '../../domain/markdown';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { Missoes } from './Missoes';

const ActionSchema = z.object({
  id: z.union([z.string(), z.number()]),
  titulo: z.string(),
  descricao: z.string().nullable().optional(),
  regiao: z.string().nullable().optional(),
  filial: z.string().nullable().optional(),
  prioridade: z.string().nullable().optional(),
  responsavel: z.string().nullable().optional(),
  prazo: z.string().nullable().optional(),
  status: z.string().default('Aberta'),
  origem: z.string().nullable().optional(),
  criado_em: z.string().nullable().optional(),
}).passthrough();

type Acao = z.infer<typeof ActionSchema>;

// As colunas sao o proprio contrato de status do backend.
const COLUNAS = ['Aberta', 'Em andamento', 'Concluída', 'Cancelada'] as const;

const CORES: Record<string, string> = {
  'Aberta': 'border-t-gold',
  'Em andamento': 'border-t-sky-500',
  'Concluída': 'border-t-emerald-500',
  'Cancelada': 'border-t-stone-400',
};

const PRIORIDADE: Record<string, string> = {
  alta: 'bg-red-50 text-red-700',
  média: 'bg-amber-50 text-amber-800',
  media: 'bg-amber-50 text-amber-800',
  baixa: 'bg-stone-100 text-zinc-600',
};

const colunaDe = (status: string): string => {
  const s = (status || '').toLowerCase();
  if (/conclu|feito|done/.test(s)) return 'Concluída';
  if (/cancel/.test(s)) return 'Cancelada';
  if (/andamento|progress|execu/.test(s)) return 'Em andamento';
  return 'Aberta';
};

export const TasksView: React.FC = () => {
  const [actions, setActions] = useState<Acao[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [aberta, setAberta] = useState<Acao | null>(null);
  // O botão de atualizar também relê as missões.
  const [recarga, setRecarga] = useState(0);
  const [arrastando, setArrastando] = useState<string | null>(null);
  const [alvo, setAlvo] = useState<string | null>(null);
  const [largura, setLarguraBruta] = useState<number>(() => {
    const salvo = Number(localStorage.getItem('sentury_task_w'));
    return Number.isFinite(salvo) && salvo >= 380 ? salvo : 544;
  });
  const setLargura = (valor: number) => {
    setLarguraBruta(valor);
    try { localStorage.setItem('sentury_task_w', String(valor)); } catch { /* modo privado */ }
  };

  const load = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setLoading(true);
    setError('');
    setRecarga(n => n + 1);
    try {
      const dados = z.object({ acoes: z.array(ActionSchema) })
        .parse(await apiClient.get('/sentury/acoes', { headers: authHeaders() }));
      setActions(dados.acoes);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const mover = async (id: string | number, status: string) => {
    const antes = actions;
    // Otimista: o cartao muda de coluna na hora e volta se o servidor recusar.
    setActions(current => current.map(a => a.id === id ? { ...a, status } : a));
    try {
      const r = z.object({ acao: ActionSchema })
        .parse(await apiClient.patch(`/sentury/acoes/${encodeURIComponent(String(id))}`, { status }, { headers: authHeaders() }));
      setActions(current => current.map(a => a.id === id ? r.acao : a));
    } catch (reason) {
      setActions(antes);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const salvarDescricao = async (id: string | number, descricao: string) => {
    const antes = actions;
    setActions(atual => atual.map(a => a.id === id ? { ...a, descricao } : a));
    setAberta(atual => atual && atual.id === id ? { ...atual, descricao } : atual);
    try {
      const r = z.object({ acao: ActionSchema })
        .parse(await apiClient.patch(`/sentury/acoes/${encodeURIComponent(String(id))}`, { descricao }, { headers: authHeaders() }));
      setActions(atual => atual.map(a => a.id === id ? r.acao : a));
    } catch (reason) {
      setActions(antes);
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  // Marcar a caixinha reescreve o proprio markdown: o texto continua sendo a fonte.
  const alternarItem = (acao: Acao, indice: number) => {
    let visto = -1;
    const novo = (acao.descricao || '').split('\n').map(linha => {
      const m = linha.match(/^(\s*[-*+]\s+\[)([ xX-])(\]\s*)/);
      if (!m) return linha;
      visto += 1;
      if (visto !== indice) return linha;
      return linha.replace(/^(\s*[-*+]\s+\[)([ xX-])(\]\s*)/, `$1${proximaMarca(m[2])}$3`);
    }).join('\n');
    void salvarDescricao(acao.id, novo);
  };

  const porColuna = useMemo(() => {
    const mapa: Record<string, Acao[]> = { 'Aberta': [], 'Em andamento': [], 'Concluída': [], 'Cancelada': [] };
    actions.forEach(a => mapa[colunaDe(a.status)].push(a));
    return mapa;
  }, [actions]);

  return (
    <section className="flex h-full flex-col overflow-hidden px-7 py-7">
      <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col">
      <header className="flex shrink-0 items-start justify-between">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Execução</p>
          <h1 className="mt-2 text-2xl font-semibold">Tarefas e planos de ação</h1>
          <p className="mt-1 text-sm text-zinc-500">Arraste entre as colunas para mudar o status. Clique para ler o plano inteiro.</p>
        </div>
        <button onClick={() => void load()} className="rounded-lg border border-stone-300 bg-white p-2" title="Atualizar">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </header>

      {error && <p className="mt-5 shrink-0 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p>}

      <Missoes key={recarga} />

      {!loading && !actions.length && !error ? (
        // Sem tarefa, quatro colunas vazias ocupando a tela nao dizem nada.
        <div className="mt-8 shrink-0 rounded-2xl border border-dashed border-stone-300 p-8 text-center">
          <ClipboardList className="mx-auto h-8 w-8 text-gold-hover" />
          <h2 className="mt-3 text-sm font-semibold">Nenhuma tarefa ainda</h2>
          <p className="mt-1 text-xs text-zinc-500">Peça um plano de ação no chat. As tarefas dele aparecem aqui, em colunas por status.</p>
        </div>
      ) : (
      <div className="mt-6 grid min-h-0 flex-1 gap-4 md:grid-cols-4">
        {COLUNAS.map(coluna => (
          <div
            key={coluna}
            onDragOver={e => { e.preventDefault(); setAlvo(coluna); }}
            onDragLeave={() => setAlvo(atual => atual === coluna ? null : atual)}
            onDrop={e => {
              e.preventDefault();
              const id = e.dataTransfer.getData('text/plain') || arrastando;
              setAlvo(null);
              setArrastando(null);
              if (id) void mover(id, coluna);
            }}
            className={`flex min-h-0 flex-col rounded-xl border p-2 transition-colors ${alvo === coluna ? 'border-gold bg-gold/5' : 'border-stone-200 bg-stone-50/50'}`}
          >
            <div className="flex shrink-0 items-center justify-between px-1.5 pb-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">{coluna}</span>
              <span className="rounded-full bg-white px-1.5 text-[10px] font-semibold text-zinc-500">{porColuna[coluna].length}</span>
            </div>

            <div className="sentury-scroll min-h-0 flex-1 space-y-2 overflow-y-auto">
              {porColuna[coluna].map(acao => (
                <article
                  key={String(acao.id)}
                  draggable
                  onDragStart={e => { setArrastando(String(acao.id)); e.dataTransfer.setData('text/plain', String(acao.id)); }}
                  onDragEnd={() => { setArrastando(null); setAlvo(null); }}
                  onClick={() => setAberta(acao)}
                  className={`cursor-grab rounded-lg border border-stone-200 border-t-2 bg-white p-3 shadow-sm transition-shadow hover:shadow-md ${CORES[coluna]} ${arrastando === String(acao.id) ? 'opacity-40' : ''}`}
                >
                  <h2 className="text-xs font-semibold leading-4 text-zinc-900">{acao.titulo}</h2>
                  {acao.descricao && <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-zinc-500">{acao.descricao}</p>}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[9px] text-zinc-500">
                    {acao.prioridade && <span className={`rounded px-1.5 py-0.5 font-semibold uppercase ${PRIORIDADE[acao.prioridade.toLowerCase()] || 'bg-stone-100'}`}>{acao.prioridade}</span>}
                    {acao.regiao && <span className="inline-flex items-center gap-0.5"><MapPin className="h-2.5 w-2.5" />{acao.regiao}</span>}
                    {acao.prazo && <span className="inline-flex items-center gap-0.5"><CalendarDays className="h-2.5 w-2.5" />{acao.prazo}</span>}
                  </div>
                </article>
              ))}
              {!porColuna[coluna].length && (
                <p className="rounded-lg border border-dashed border-stone-300 p-3 text-center text-[10px] text-zinc-400">vazio</p>
              )}
            </div>
          </div>
        ))}
      </div>
      )}
      </div>

      {aberta && (
        <div className="fixed inset-0 z-[80] flex justify-end bg-black/25" onClick={() => setAberta(null)}>
          <aside
            onClick={e => e.stopPropagation()}
            style={{ width: `min(${largura}px, calc(100vw - 3.5rem))` }}
            className="relative flex animate-[sentury-workbench-in_220ms_ease-out] flex-col border-l border-stone-200 bg-[#fffdf8] shadow-2xl"
          >
            <ResizeHandle width={largura} onResize={setLargura} min={380} />
            <header className="flex items-start gap-3 border-b border-stone-200 px-5 py-4">
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-bold uppercase tracking-wider text-gold-ink">{colunaDe(aberta.status)}</p>
                <h2 className="mt-1 text-sm font-semibold leading-5">{aberta.titulo}</h2>
              </div>
              <button onClick={() => setAberta(null)} className="rounded-md p-1.5 text-zinc-400 hover:bg-stone-100" aria-label="Fechar">
                <X className="h-4 w-4" />
              </button>
            </header>

            <div className="sentury-scroll flex-1 overflow-y-auto p-5">
              {aberta.descricao ? (
                <div
                  className="bubble__md prose prose-sm max-w-none"
                  onClick={event => {
                    const alvo = (event.target as HTMLElement).closest('[data-check]');
                    if (!alvo) return;
                    event.preventDefault();
                    alternarItem(aberta, Number(alvo.getAttribute('data-check')));
                  }}
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(aberta.descricao, { tarefasEditaveis: true }) }}
                />
              ) : (
                <p className="text-sm text-zinc-500">Esta ação não tem descrição registrada.</p>
              )}

              <dl className="mt-6 grid grid-cols-2 gap-3 text-xs">
                {([
                  ['Prioridade', aberta.prioridade],
                  ['Responsável', aberta.responsavel],
                  ['Região', aberta.regiao],
                  ['Filial', aberta.filial],
                  ['Prazo', aberta.prazo],
                  ['Origem', aberta.origem],
                  ['Criada em', aberta.criado_em],
                ] as const).filter(([, v]) => v).map(([rotulo, valor]) => (
                  <div key={rotulo} className="rounded-lg border border-stone-200 bg-white p-2.5">
                    <dt className="text-[10px] uppercase tracking-wider text-zinc-400">{rotulo}</dt>
                    <dd className="mt-0.5 font-medium text-zinc-700">{valor}</dd>
                  </div>
                ))}
              </dl>
            </div>

            <footer className="flex flex-wrap gap-2 border-t border-stone-200 p-4">
              {COLUNAS.filter(c => c !== colunaDe(aberta.status)).map(c => (
                <button
                  key={c}
                  type="button"
                  onClick={() => { void mover(aberta.id, c); setAberta({ ...aberta, status: c }); }}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-medium hover:border-gold"
                >
                  <User2 className="h-3 w-3" />Mover para {c}
                </button>
              ))}
            </footer>
          </aside>
        </div>
      )}

    </section>
  );
};
