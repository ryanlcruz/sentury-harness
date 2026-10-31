import React, { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronRight, CircleDashed, CircleMinus, CircleSlash, Copy, LoaderCircle, RefreshCw, ShieldAlert, TriangleAlert } from 'lucide-react';
import { CommandRun } from '../../contracts/domain/session';
import { copiar } from '../../runtime/clipboard';
import { markOfKind } from '../../components/CapabilityMark';
import { verboDaAcao } from '../../components/acoes';
import { ContagemDoDiff, DiffDoArquivoView } from './DiffDoArquivo';
import { SaidaDoTerminalView, TERMINAIS } from './SaidaDoTerminal';

interface CommandCardProps {
  run: CommandRun;
  defaultOpen?: boolean;
  /** A caixa de decisão deste bloco, quando ele está esperando resposta. */
  aprovacao?: React.ReactNode;
  /** Mantém o foco visual no bloco que aguarda aprovação. */
  pendente?: boolean;
}

const LINGUAGEM: Record<string, string> = {
  executar_python: 'python',
  consultar_sql: 'sql',
};

export function linguagemDoComando(run: Pick<CommandRun, 'tool' | 'kind'>): string {
  return LINGUAGEM[run.tool || ''] || run.kind || 'comando';
}

function duracao(ms?: number): string {
  if (ms == null) return '';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** Acima disso o codigo recolhe nas primeiras linhas. */
const LIMITE_DO_CODIGO = 8;

/**
 * O codigo que rodou. Comprido, recolhe nas primeiras linhas; "ver codigo
 * todo" abre dentro de uma altura fixa, rolando com a barra discreta do
 * terminal. Linha longa quebra em vez de rolar para o lado.
 */
function CodigoDoComando({ linhas }: { linhas: string[] }) {
  const [todo, setTodo] = useState(false);
  const longo = linhas.length > LIMITE_DO_CODIGO;
  const visiveis = longo && !todo ? linhas.slice(0, LIMITE_DO_CODIGO - 2) : linhas;
  const largura = String(linhas.length).length;
  return (
    <div className="bg-zinc-950">
      <pre className={`sentury-terminal-scroll overflow-y-auto px-3 py-2.5 text-[11px] leading-5 text-zinc-100 ${todo ? 'max-h-72' : ''}`}>
        <code>
          {visiveis.map((linha, index) => (
            <span key={index} className="flex">
              <span className="mr-3 shrink-0 select-none text-right text-zinc-600" style={{ width: `${largura}ch` }}>{index + 1}</span>
              <span className="min-w-0 whitespace-pre-wrap break-words">{linha || ' '}</span>
            </span>
          ))}
        </code>
      </pre>
      {longo ? (
        <button
          type="button"
          onClick={() => setTodo(valor => !valor)}
          className="block w-full border-t border-zinc-800 px-3 py-1 text-left font-mono text-[10px] text-zinc-500 hover:text-zinc-300"
        >
          {todo ? 'recolher código' : `··· ver código todo (${linhas.length} linhas)`}
        </button>
      ) : null}
    </div>
  );
}

export const CommandCard: React.FC<CommandCardProps> = ({ run, defaultOpen = true, aprovacao = null, pendente = false }) => {
  // Comando, script e codigo viram terminal: abre sozinho quando falha ou
  // enquanto roda; quando da certo, fica fechado com o resumo no cabecalho.
  // Falha contornada (o agente seguiu por outro caminho) continua sendo um
  // comando que falhou: abre tambem.
  const terminal = Boolean(run.saida) || (TERMINAIS.has(run.tool || '') && run.status === 'running');
  const abertoPeloEstado = run.status === 'error' || run.status === 'handledError' || run.status === 'running';
  // O diff abre no clique: fechado, o cartao diz "+12 −3" e basta.
  const [aberto, setAberto] = useState(
    terminal ? abertoPeloEstado : run.diff && !run.command ? false : defaultOpen,
  );
  // Quem abriu ou fechou na mao manda; senao o cartao segue o estado.
  const mexeu = useRef(false);
  useEffect(() => {
    if (terminal && !mexeu.current) setAberto(abertoPeloEstado);
  }, [terminal, abertoPeloEstado]);
  const [copiado, setCopiado] = useState(false);
  // O cabeçalho continua visível mesmo quando não há comando ou detalhe.
  const linhas = run.command ? run.command.split('\n') : [];
  const temDetalhe = Boolean(run.command || run.resumo || run.diff || run.saida);
  const marca = markOfKind(run.kind);
  const rodando = run.status === 'running';
  const aguardando = run.status === 'pending';
  const falhou = run.status === 'error';
  const recuperado = run.status === 'handledError';
  const cancelado = run.status === 'canceled';
  const barrado = run.status === 'rejected';
  const pulado = run.status === 'skipped';

  const copiarComando = async () => {
    if (await copiar(run.command || '')) {
      setCopiado(true);
      window.setTimeout(() => setCopiado(false), 1600);
    }
  };

  return (
    <div
      data-pendente={pendente ? 'true' : undefined}
      className={`my-2 overflow-hidden rounded-lg border bg-white/90 ${
        pendente ? 'border-gold ring-1 ring-gold-soft'
          : barrado ? 'border-amber-200'
          : recuperado ? 'border-amber-200 bg-amber-50/30'
          : falhou ? 'border-red-200'
          : cancelado ? 'border-stone-200 opacity-70'
          : 'border-stone-200'
      }`}
    >
      <div className="flex items-center gap-2 border-b border-stone-200 bg-stone-50/80 px-3 py-2">
        <marca.Icon className={`h-3.5 w-3.5 shrink-0 ${marca.texto}`} aria-hidden />
        <button
          type="button"
          onClick={() => { if (!temDetalhe) return; mexeu.current = true; setAberto(valor => !valor); }}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          aria-expanded={temDetalhe ? aberto : undefined}
        >
          {verboDaAcao(run.intent) ? (
            <span className="shrink-0 text-[11px] text-zinc-500">{verboDaAcao(run.intent)}</span>
          ) : null}
          <span className="truncate text-[11px] font-semibold text-zinc-700">{run.title}</span>
          <span className="shrink-0 rounded bg-stone-200/70 px-1.5 py-px font-mono text-[9px] uppercase text-zinc-500">
            {run.diff ? (run.diff.criado ? 'criado' : 'editado') : linguagemDoComando(run)}
          </span>
          {run.diff ? <ContagemDoDiff diff={run.diff} /> : null}
          {terminal && !aberto && run.saida?.resumo ? (
            <span className="truncate text-[11px] text-zinc-500">· {run.saida.resumo}</span>
          ) : null}
          {!temDetalhe
            ? null
            : aberto ? <ChevronDown className="h-3 w-3 shrink-0 text-zinc-400" /> : <ChevronRight className="h-3 w-3 shrink-0 text-zinc-400" />}
        </button>
        {recuperado ? <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-[9px] font-semibold text-amber-800">contornado</span> : null}
        {run.durationMs != null ? <span className="shrink-0 text-[10px] tabular-nums text-zinc-400">{duracao(run.durationMs)}</span> : null}
        {barrado
          ? <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-amber-600" aria-label="recusado pela politica" />
          : cancelado
          ? <CircleSlash className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="cancelado" />
          : recuperado
            ? <RefreshCw className="h-3.5 w-3.5 shrink-0 text-amber-600" aria-label="falhou, mas o agente seguiu por outro caminho" />
          : aguardando
            ? <CircleDashed className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="pendente" />
          : pulado
            ? <CircleMinus className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="dispensado" />
          : rodando
            ? <LoaderCircle className="sentury-working-indicator h-3.5 w-3.5 shrink-0 text-gold-hover" aria-label="trabalhando" />
            : falhou
              ? <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-red-500" />
              : <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />}
        {run.command ? (
        <button
          type="button"
          onClick={() => void copiarComando()}
          className="shrink-0 rounded p-1 text-zinc-400 hover:bg-stone-200 hover:text-zinc-700"
          title="Copiar comando"
          aria-label="Copiar comando"
        >
          {copiado ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
        </button>
        ) : null}
      </div>

      {aberto && temDetalhe ? (
        <>
          {run.command ? <CodigoDoComando linhas={linhas} /> : null}
          {run.diff ? <DiffDoArquivoView diff={run.diff} /> : null}
          {terminal ? (
            <SaidaDoTerminalView saida={run.saida} rodando={run.status === 'running'} />
          ) : null}
          {/* Ver o comando e nao ver o retorno e assistir meia execucao. */}
          {!terminal && run.resumo ? (
            <div className="border-t border-stone-200 bg-stone-50/60 px-3 py-2">
              <span className="mb-1 block font-mono text-[9px] uppercase tracking-wider text-zinc-400">resultado</span>
              <pre className="sentury-scroll max-h-40 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-5 text-zinc-600">{run.resumo}</pre>
            </div>
          ) : null}
        </>
      ) : null}
      {aprovacao ? (
        <div className="border-t border-stone-200 bg-[#fffdf8] px-3 py-2.5">{aprovacao}</div>
      ) : null}
    </div>
  );
};
