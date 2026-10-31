import React, { useCallback, useEffect, useState } from 'react';
import { ListChecks, X } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const ResumoSchema = z.object({
  missao: z.string(),
  total: z.number(),
  por_estado: z.record(z.string(), z.number()),
  faltam: z.number(),
  atualizada: z.number().optional(),
});

const UnidadeSchema = z.object({
  alvo: z.string(),
  item: z.string(),
  estado: z.string(),
  tentativas: z.number().default(0),
  evidencia: z.unknown().optional(),
  nota: z.string().nullable().optional(),
  updated_at: z.number().optional(),
}).passthrough();

type Resumo = z.infer<typeof ResumoSchema>;
type Unidade = z.infer<typeof UnidadeSchema>;

// A ordem é a do trabalho: o que precisa de você vem antes do resto.
const ESTADOS: Array<[string, string, string]> = [
  ['precisa_usuario', 'Precisa de você', 'bg-gold'],
  ['revisar', 'Revisar', 'bg-amber-500'],
  ['falhou', 'Falhou', 'bg-red-500'],
  ['fazendo', 'Fazendo', 'bg-sky-500'],
  ['pendente', 'Pendente', 'bg-stone-300'],
  ['feito', 'Feito', 'bg-emerald-500'],
  ['descartada', 'Descartada', 'bg-zinc-400'],
];
const ROTULO = Object.fromEntries(ESTADOS.map(([estado, rotulo]) => [estado, rotulo]));
const COR = Object.fromEntries(ESTADOS.map(([estado, , cor]) => [estado, cor]));

const nomeLegivel = (nome: string) => nome.replace(/[-_]+/g, ' ');

const Evidencia: React.FC<{ valor: unknown }> = ({ valor }) => {
  if (valor === null || valor === undefined || valor === '') return null;
  const texto = typeof valor === 'string' ? valor : JSON.stringify(valor);
  if (/^https?:\/\//.test(texto)) {
    return <a href={texto} target="_blank" rel="noreferrer" className="break-all text-sky-700 underline">{texto}</a>;
  }
  return <span className="break-words text-zinc-600">{texto.length > 240 ? `${texto.slice(0, 240)}…` : texto}</span>;
};

/** Barra com a fatia de cada estado, na mesma ordem da legenda. */
const Progresso: React.FC<{ resumo: Resumo }> = ({ resumo }) => (
  <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-stone-100">
    {ESTADOS.map(([estado]) => {
      const n = resumo.por_estado[estado] || 0;
      return n ? <span key={estado} className={COR[estado]} style={{ width: `${(n / Math.max(resumo.total, 1)) * 100}%` }} /> : null;
    })}
  </div>
);

/** As missões em curso: o trabalho repetido que o agente faz ao longo de vários turnos. */
export const Missoes: React.FC = () => {
  const [missoes, setMissoes] = useState<Resumo[]>([]);
  const [aberta, setAberta] = useState<{ resumo: Resumo; unidades: Unidade[] } | null>(null);
  const [erro, setErro] = useState('');

  const carregar = useCallback(async () => {
    apiClient.setBaseUrl(getRuntimeConfig().apiUrl);
    try {
      const dados = z.object({ missoes: z.array(ResumoSchema) })
        .parse(await apiClient.get('/sentury/missoes', { headers: authHeaders() }));
      setMissoes(dados.missoes);
    } catch {
      // Sem missões a faixa some; erro de rede aparece no quadro de tarefas logo abaixo.
      setMissoes([]);
    }
  }, []);

  useEffect(() => { void carregar(); }, [carregar]);

  const abrir = async (resumo: Resumo) => {
    setErro('');
    try {
      const dados = z.object({ missao: ResumoSchema, unidades: z.array(UnidadeSchema) })
        .parse(await apiClient.get(`/sentury/missoes/${encodeURIComponent(resumo.missao)}`, { headers: authHeaders() }));
      setAberta({ resumo: dados.missao, unidades: dados.unidades });
    } catch (motivo) {
      setErro(motivo instanceof Error ? motivo.message : String(motivo));
    }
  };

  if (!missoes.length) return null;

  return (
    <div className="mt-6 shrink-0">
      <div className="flex items-center gap-2 px-0.5">
        <ListChecks className="h-3.5 w-3.5 text-gold-hover" />
        <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Missões</span>
      </div>
      {erro && <p className="mt-2 rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">{erro}</p>}
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {missoes.map(m => {
          const prontas = m.total - m.faltam;
          return (
            <button
              key={m.missao}
              type="button"
              onClick={() => void abrir(m)}
              className="rounded-lg border border-stone-200 bg-white p-3 text-left shadow-sm transition-shadow hover:shadow-md"
            >
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="truncate text-xs font-semibold capitalize text-zinc-900">{nomeLegivel(m.missao)}</h2>
                <span className="shrink-0 text-[10px] font-semibold text-zinc-500">{prontas}/{m.total}</span>
              </div>
              <div className="mt-2"><Progresso resumo={m} /></div>
              <p className="mt-1.5 text-[10px] text-zinc-500">
                {m.faltam ? `faltam ${m.faltam}` : 'concluída'}
                {m.por_estado.precisa_usuario ? ` · ${m.por_estado.precisa_usuario} precisa de você` : ''}
              </p>
            </button>
          );
        })}
      </div>

      {aberta && (
        <div className="fixed inset-0 z-[80] flex justify-end bg-black/25" onClick={() => setAberta(null)}>
          <aside
            onClick={e => e.stopPropagation()}
            className="flex w-[min(560px,calc(100vw-3.5rem))] animate-[sentury-workbench-in_220ms_ease-out] flex-col border-l border-stone-200 bg-[#fffdf8] shadow-2xl"
          >
            <header className="flex items-start gap-3 border-b border-stone-200 px-5 py-4">
              <div className="min-w-0 flex-1">
                <p className="text-[10px] font-bold uppercase tracking-wider text-gold-ink">Missão</p>
                <h2 className="mt-1 text-sm font-semibold capitalize leading-5">{nomeLegivel(aberta.resumo.missao)}</h2>
                <div className="mt-2"><Progresso resumo={aberta.resumo} /></div>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-zinc-500">
                  {ESTADOS.filter(([estado]) => aberta.resumo.por_estado[estado]).map(([estado, rotulo, cor]) => (
                    <span key={estado} className="inline-flex items-center gap-1">
                      <span className={`h-1.5 w-1.5 rounded-full ${cor}`} />{rotulo} {aberta.resumo.por_estado[estado]}
                    </span>
                  ))}
                </div>
              </div>
              <button onClick={() => setAberta(null)} className="rounded-md p-1.5 text-zinc-400 hover:bg-stone-100" aria-label="Fechar">
                <X className="h-4 w-4" />
              </button>
            </header>
            <div className="sentury-scroll flex-1 space-y-2 overflow-y-auto p-5">
              {[...aberta.unidades]
                .sort((a, b) => ESTADOS.findIndex(([e]) => e === a.estado) - ESTADOS.findIndex(([e]) => e === b.estado))
                .map(u => (
                  <article key={`${u.alvo}|${u.item}`} className="rounded-lg border border-stone-200 bg-white p-3 text-xs">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-semibold text-zinc-900">{u.alvo}</p>
                        <p className="text-zinc-500">{u.item}</p>
                      </div>
                      <span className="inline-flex shrink-0 items-center gap-1 text-[10px] font-semibold text-zinc-600">
                        <span className={`h-1.5 w-1.5 rounded-full ${COR[u.estado] || 'bg-stone-300'}`} />
                        {ROTULO[u.estado] || u.estado}
                      </span>
                    </div>
                    {u.nota ? <p className="mt-1.5 text-zinc-600">{u.nota}</p> : null}
                    {u.evidencia ? <p className="mt-1.5 text-[11px]"><Evidencia valor={u.evidencia} /></p> : null}
                    {u.tentativas > 1 ? <p className="mt-1 text-[10px] text-zinc-400">{u.tentativas} tentativas</p> : null}
                  </article>
                ))}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
};
