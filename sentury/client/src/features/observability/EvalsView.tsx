import React, { useCallback, useEffect, useState } from 'react';
import { Check, FlaskConical, Play, RefreshCw, TriangleAlert } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const ExecucaoSchema = z.object({
  quando: z.number().optional(),
  ms: z.number().default(0),
  total: z.number().default(0),
  passaram: z.number().default(0),
  resultados: z.array(z.object({
    nome: z.string(),
    funcao: z.string().default(''),
    ok: z.boolean(),
    detalhe: z.string().default(''),
  })).default([]),
});

const CatalogoSchema = z.object({
  casos: z.array(z.object({
    nome: z.string(),
    funcao: z.string(),
    descricao: z.string().default(''),
  })).default([]),
  setor: z.string().optional(),
  ultima_execucao: ExecucaoSchema.nullable().optional(),
});

function primeiraMaiuscula(texto: string): string {
  return texto ? texto.charAt(0).toLocaleUpperCase('pt-BR') + texto.slice(1) : texto;
}

export const EvalsView: React.FC = () => {
  const [catalogo, setCatalogo] = useState<z.infer<typeof CatalogoSchema> | null>(null);
  const [execucao, setExecucao] = useState<z.infer<typeof ExecucaoSchema> | null>(null);
  const [rodando, setRodando] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState('');

  const load = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setCarregando(true);
    setErro('');
    try {
      const dados = CatalogoSchema.parse(await apiClient.get('/sentury/evals', { headers: authHeaders() }));
      setCatalogo(dados);
      if (dados.ultima_execucao) setExecucao(dados.ultima_execucao);
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : String(causa));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const rodar = async () => {
    setRodando(true);
    setErro('');
    try {
      setExecucao(ExecucaoSchema.parse(
        await apiClient.post('/sentury/evals/run', {}, { headers: authHeaders() }),
      ));
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : String(causa));
    } finally {
      setRodando(false);
    }
  };

  const porFuncao = new Map((execucao?.resultados || []).map(item => [item.funcao, item]));
  const falhas = (execucao?.resultados || []).filter(item => !item.ok);

  return (
    <section className="h-full overflow-y-auto px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Regressão</p>
            <h1 className="mt-2 text-2xl font-semibold">Evals</h1>
            <p className="mt-1 max-w-2xl text-sm text-zinc-500">
              Cenários ponta a ponta que afirmam as garantias visíveis. Rodam o orquestrador inteiro sem
              chamar nenhum modelo real, então o resultado é o mesmo toda vez.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={rodando || !(catalogo?.casos || []).length}
              onClick={() => void rodar()}
              className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white disabled:opacity-40"
            >
              <Play className="h-3.5 w-3.5" />{rodando ? 'Rodando…' : 'Rodar suíte'}
            </button>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-lg border border-stone-300 bg-white p-2"
              aria-label="Atualizar"
            >
              <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </header>

        {erro ? <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{erro}</p> : null}

        {execucao ? (
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <article className={`rounded-xl border p-4 ${falhas.length ? 'border-amber-200 bg-amber-50' : 'border-emerald-200 bg-emerald-50'}`}>
              <p className="text-[10px] uppercase tracking-wider text-zinc-500">Resultado</p>
              <p className="mt-1.5 text-2xl font-semibold tabular-nums">{execucao.passaram}/{execucao.total}</p>
              <p className="text-xs text-zinc-600">{falhas.length ? `${falhas.length} falhando` : 'tudo passando'}</p>
            </article>
            <article className="rounded-xl border border-stone-200 bg-white/80 p-4">
              <p className="text-[10px] uppercase tracking-wider text-zinc-400">Duração</p>
              <p className="mt-1.5 text-2xl font-semibold tabular-nums">{(execucao.ms / 1000).toFixed(1)}s</p>
            </article>
            <article className="rounded-xl border border-stone-200 bg-white/80 p-4">
              <p className="text-[10px] uppercase tracking-wider text-zinc-400">Última execução</p>
              <p className="mt-1.5 text-sm font-medium">
                {execucao.quando ? new Date(execucao.quando * 1000).toLocaleString('pt-BR') : '—'}
              </p>
            </article>
          </div>
        ) : null}

        <div className="mt-7 space-y-2">
          {(catalogo?.casos || []).map(caso => {
            const resultado = porFuncao.get(caso.funcao);
            return (
              <article
                key={caso.funcao}
                className={`flex items-start gap-3 rounded-xl border p-4 ${
                  resultado ? (resultado.ok ? 'border-stone-200 bg-white/85' : 'border-red-200 bg-red-50') : 'border-stone-200 bg-white/60'
                }`}
              >
                <span className="mt-0.5">
                  {!resultado
                    ? <FlaskConical className="h-4 w-4 text-zinc-400" />
                    : resultado.ok
                      ? <Check className="h-4 w-4 text-emerald-600" />
                      : <TriangleAlert className="h-4 w-4 text-red-600" />}
                </span>
                <div className="min-w-0 flex-1">
                  <strong className="block text-sm">{primeiraMaiuscula(caso.descricao || resultado?.nome || caso.nome)}</strong>
                  <span className="mt-0.5 block font-mono text-[10px] text-zinc-400">{caso.funcao}</span>
                  {resultado && !resultado.ok && resultado.detalhe ? (
                    <p className="mt-2 whitespace-pre-wrap break-words rounded-lg border border-red-200 bg-white/70 p-2.5 font-mono text-[11px] leading-5 text-red-800">
                      {resultado.detalhe}
                    </p>
                  ) : null}
                </div>
              </article>
            );
          })}
          {!carregando && !(catalogo?.casos || []).length ? (
            <p className="rounded-xl border border-dashed border-stone-300 p-6 text-sm text-zinc-500">
              {catalogo?.setor
                ? `Nenhuma eval para o setor ativo (${catalogo.setor}). As evals de um setor aparecem quando ele está ligado.`
                : 'Nenhum caso registrado na suíte.'}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
};
