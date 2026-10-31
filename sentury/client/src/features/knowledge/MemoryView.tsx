import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Brain, MessageSquare, Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

// O que o Sentury lembra da pessoa entre conversas (memory/user_memory.py).
const LembrancasSchema = z.object({
  memorias: z.array(z.object({
    id: z.number(),
    texto: z.string(),
    ts: z.number().nullable().optional(),
    idade: z.string().default(''),
    tipo: z.string().nullable().optional(),
    sessao: z.string().nullable().optional(),
    conversa: z.string().nullable().optional(),
  })).default([]),
});
type Lembranca = z.infer<typeof LembrancasSchema>['memorias'][number];

const TIPO_LEGIVEL: Record<string, string> = {
  pessoa: 'sobre você', decisao: 'decisão', projeto: 'projeto', referencia: 'referência',
};

function semAcento(texto: string): string {
  return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
}

/** De onde a lembrança veio. Sem isto a lista vira frases soltas, e a pessoa
 *  não sabe por que o Sentury guardou aquilo. */
function origem(m: Lembranca): React.ReactNode {
  if (!m.sessao) return <><Pencil className="h-3 w-3" />Ensinada aqui</>;
  return <><MessageSquare className="h-3 w-3" />{m.conversa ? `Da conversa «${m.conversa}»` : 'De uma conversa que não existe mais'}</>;
}

export const MemoryView: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState('');
  const [lembrancas, setLembrancas] = useState<Lembranca[]>([]);
  const [busca, setBusca] = useState('');
  const [nova, setNova] = useState('');
  const [aviso, setAviso] = useState('');
  const [confirmando, setConfirmando] = useState<number | null>(null);
  const usuario = getRuntimeConfig().userId;

  const load = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setLoading(true);
    setErro('');
    try {
      const lembradas = await apiClient.get(`/sentury/memory/usuario?user_id=${encodeURIComponent(config.userId)}`, { headers: authHeaders() });
      setLembrancas(LembrancasSchema.parse(lembradas).memorias);
    } catch (reason) {
      setErro(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const visiveis = useMemo(() => {
    const termo = semAcento(busca.trim());
    return termo ? lembrancas.filter(m => semAcento(m.texto).includes(termo)) : lembrancas;
  }, [busca, lembrancas]);

  const ensinar = async () => {
    const texto = nova.trim();
    if (!texto) return;
    setAviso('');
    try {
      const r = await apiClient.post<{ guardada: boolean }>('/sentury/memory/usuario', { user_id: usuario, texto }, { headers: authHeaders() });
      setNova('');
      setAviso(r.guardada ? '' : 'Ele já lembra de algo sobre esse assunto.');
      await load();
    } catch (reason) {
      setErro(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const apagar = async (id: number) => {
    if (confirmando !== id) {
      setConfirmando(id);
      window.setTimeout(() => setConfirmando(atual => (atual === id ? null : atual)), 3000);
      return;
    }
    setConfirmando(null);
    try {
      await apiClient.delete(`/sentury/memory/usuario/${id}?user_id=${encodeURIComponent(usuario)}`, { headers: authHeaders() });
      setLembrancas(atual => atual.filter(m => m.id !== id));
    } catch (reason) {
      setErro(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <section className="h-full overflow-y-auto px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <header className="flex items-start justify-between">
          <div>
            <h1 className="mt-2 text-2xl font-semibold">Memória</h1>
            <p className="mt-1 text-sm text-zinc-500">
              O que o Sentury lembra de você entre conversas. Ele usa como pano de fundo, não como ordem.
            </p>
          </div>
          <button onClick={() => void load()} className="rounded-lg border border-stone-300 bg-white p-2" title="Atualizar">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </header>

        {erro && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{erro}</p>}

        <section className="mt-6 overflow-hidden rounded-2xl border border-stone-200 bg-white/85">
          <header className="flex flex-wrap items-center gap-3 border-b border-stone-200 px-5 py-4">
            <Brain className="h-4 w-4 text-gold-hover" />
            <h2 className="text-sm font-semibold">O que ele lembra</h2>
            <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[10px] font-semibold text-zinc-500">{lembrancas.length}</span>
            <span className="flex-1" />
            <label className="flex w-64 items-center gap-2 rounded-lg border border-stone-300 bg-white px-2.5 py-1.5">
              <Search className="h-3.5 w-3.5 text-zinc-400" />
              <input value={busca} onChange={e => setBusca(e.target.value)} placeholder="Buscar na memória" className="w-full bg-transparent text-xs outline-none" />
            </label>
          </header>
          <form
            onSubmit={e => { e.preventDefault(); void ensinar(); }}
            className="flex items-center gap-2 border-b border-stone-100 bg-stone-50/60 px-5 py-3"
          >
            <input
              value={nova}
              onChange={e => { setNova(e.target.value); setAviso(''); }}
              maxLength={500}
              placeholder="Ensine algo: prefiro respostas curtas, trabalho com Python…"
              className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs outline-none focus:border-gold"
            />
            <button type="submit" disabled={!nova.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-35">
              <Plus className="h-3.5 w-3.5" />Ensinar
            </button>
          </form>
          {aviso ? <p className="border-b border-stone-100 px-5 py-2 text-[11px] text-amber-700">{aviso}</p> : null}
          <ul className="divide-y divide-stone-100">
            {visiveis.map(m => (
              <li key={m.id} className="flex items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-zinc-800">{m.texto}</p>
                  <p className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-zinc-400">{origem(m)}</p>
                </div>
                {m.tipo ? <span className="shrink-0 rounded-full border border-stone-200 px-2 py-0.5 text-[10px] text-zinc-500">{TIPO_LEGIVEL[m.tipo] ?? m.tipo}</span> : null}
                {m.idade ? <span className="shrink-0 text-[11px] text-zinc-400">{m.idade}</span> : null}
                <button
                  type="button"
                  onClick={() => void apagar(m.id)}
                  className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] ${confirmando === m.id ? 'bg-red-50 font-semibold text-red-700' : 'text-zinc-400 hover:bg-stone-100 hover:text-zinc-700'}`}
                  title="Esquecer"
                >
                  <Trash2 className="h-3.5 w-3.5" />{confirmando === m.id ? 'Esquecer?' : ''}
                </button>
              </li>
            ))}
          </ul>
          {!loading && !lembrancas.length ? (
            <p className="px-5 py-6 text-sm text-zinc-500">Ele ainda não guardou nada sobre você. Diga no chat "lembre que…" ou ensine aqui.</p>
          ) : null}
          {lembrancas.length > 0 && !visiveis.length ? (
            <p className="px-5 py-6 text-sm text-zinc-500">Nada na memória com esse termo.</p>
          ) : null}
        </section>

      </div>
    </section>
  );
};
