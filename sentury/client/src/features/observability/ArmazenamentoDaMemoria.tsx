import React, { useEffect, useState } from 'react';
import { Database, HardDrive } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const MemoriaSchema = z.object({
  disponivel: z.boolean(),
  backend: z.string().default('desconhecido'),
  motivo: z.string().optional(),
  home: z.string().optional(),
  journal_bytes: z.number().optional(),
  projection_bytes: z.number().optional(),
  total_eventos: z.number().optional(),
  por_tipo: z.record(z.string(), z.number()).optional(),
  recentes: z.array(z.object({
    type: z.string(),
    key: z.string(),
    ts: z.union([z.number(), z.string()]).nullable().optional(),
  })).default([]),
}).passthrough();

const bytes = (n?: number) => {
  if (!n) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
};

const quando = (ts?: number | string | null) => {
  if (ts == null) return '';
  const n = typeof ts === 'string' ? Number(ts) : ts;
  if (!Number.isFinite(n)) return String(ts);
  return new Date(n > 1e12 ? n : n * 1000).toLocaleString('pt-BR');
};

/** Onde a memória durável vive e o que entrou nela por último. É diagnóstico,
 *  não o que o Sentury lembra da pessoa: isso fica na tela de Memória. */
export const ArmazenamentoDaMemoria: React.FC<{ recarregar: number }> = ({ recarregar }) => {
  const [dados, setDados] = useState<z.infer<typeof MemoriaSchema> | null>(null);
  const [erro, setErro] = useState('');

  useEffect(() => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setErro('');
    apiClient.get('/sentury/memory', { headers: authHeaders() })
      .then(r => setDados(MemoriaSchema.parse(r)))
      .catch(reason => setErro(reason instanceof Error ? reason.message : String(reason)));
  }, [recarregar]);

  return (
    <section className="mt-7">
      <h2 className="text-sm font-semibold">Armazenamento da memória</h2>
      <p className="mt-1 text-xs text-zinc-500">O journal é a fonte; o SQLite é projeção reconstruível a partir dele.</p>

      {erro && <p className="mt-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{erro}</p>}

      {dados && !dados.disponivel && (
        <p className="mt-3 rounded-xl border border-stone-300 bg-white/70 p-5 text-sm text-zinc-600">
          Backend <strong>{dados.backend}</strong>. {dados.motivo}
        </p>
      )}

      {dados?.disponivel && (
        <>
          <div className="mt-3 grid gap-3 sm:grid-cols-4">
            {([
              ['Eventos no journal', String(dados.total_eventos ?? 0)],
              ['Journal', bytes(dados.journal_bytes)],
              ['Projeção SQLite', bytes(dados.projection_bytes)],
              ['Backend', dados.backend],
            ] as const).map(([rotulo, valor]) => (
              <div key={rotulo} className="rounded-xl border border-stone-200 bg-white/85 p-4">
                <p className="text-[10px] uppercase tracking-wider text-zinc-400">{rotulo}</p>
                <p className="mt-1.5 text-lg font-semibold text-zinc-900">{valor}</p>
              </div>
            ))}
          </div>

          <p className="mt-3 inline-flex items-center gap-1.5 text-[11px] text-zinc-500">
            <HardDrive className="h-3 w-3" />{dados.home}
          </p>

          {dados.por_tipo && Object.keys(dados.por_tipo).length > 0 && (
            <div className="mt-5 flex flex-wrap gap-2">
              {Object.entries(dados.por_tipo).map(([tipo, n]) => (
                <span key={tipo} className="rounded-full border border-stone-200 bg-white px-3 py-1.5 text-xs">
                  <span className="font-mono text-[11px] text-zinc-600">{tipo}</span>
                  <span className="ml-2 font-semibold text-gold-ink">{n}</span>
                </span>
              ))}
            </div>
          )}

          <h3 className="mt-6 flex items-center gap-2 text-xs font-semibold">
            <Database className="h-4 w-4 text-gold-hover" />Últimos eventos
          </h3>
          <div className="mt-3 overflow-hidden rounded-xl border border-stone-200 bg-white/80">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-stone-200 bg-stone-100/70 text-zinc-500">
                <tr><th className="px-4 py-2.5">Tipo</th><th>Chave</th><th className="pr-4 text-right">Quando</th></tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {dados.recentes.map((e, i) => (
                  <tr key={`${e.key}-${i}`}>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-zinc-600">{e.type}</td>
                    <td className="truncate font-mono text-[11px] text-zinc-500">{e.key}</td>
                    <td className="pr-4 text-right text-[11px] text-zinc-400">{quando(e.ts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!dados.recentes.length && <p className="p-5 text-sm text-zinc-500">Nenhum evento registrado ainda.</p>}
          </div>
        </>
      )}
    </section>
  );
};
