import { DiffDoArquivo } from '../../contracts/events/session-events';

/**
 * O que mudou num arquivo que a Sentury criou ou editou. Vem do evento `diff`
 * (sentury/tools/diff_de_arquivo.py) e mora no cartão do passo: fechado mostra
 * "+N −M"; aberto, os trechos com o número da linha dos dois lados.
 */

export function ContagemDoDiff({ diff }: { diff: DiffDoArquivo }) {
  return (
    <span className="inline-flex shrink-0 overflow-hidden rounded font-mono text-[10px] font-semibold tabular-nums">
      <span className="bg-emerald-50 px-1.5 py-px text-emerald-700">+{diff.adicionadas}</span>
      <span className="bg-red-50 px-1.5 py-px text-red-600">−{diff.removidas}</span>
    </span>
  );
}

function numero(n: number | null): string {
  return n == null ? '' : String(n);
}

export function DiffDoArquivoView({ diff }: { diff: DiffDoArquivo }) {
  const largura = Math.max(2, ...diff.trechos.flatMap(t => t.linhas.map(l => numero(l[3] ?? l[2]).length)));
  return (
    <div className="border-t border-stone-200 bg-zinc-950">
      <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900 px-3 py-1.5">
        <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-zinc-400" title={diff.arquivo}>{diff.arquivo}</span>
        <span className="shrink-0 text-[10px] text-zinc-500">{diff.criado ? 'arquivo novo' : 'editado'}</span>
      </div>
      <div className="sentury-scroll max-h-80 overflow-auto bg-zinc-950 font-mono text-[11px] leading-5">
        {diff.trechos.map((trecho, t) => (
          <div key={t}>
            {!diff.criado ? (
              <div className="select-none bg-sky-500/10 px-3 text-sky-300/80">{trecho.cabecalho}</div>
            ) : null}
            {trecho.linhas.map(([tipo, texto, antes, depois], i) => (
              <div
                key={i}
                className={`flex whitespace-pre ${tipo === '+' ? 'bg-emerald-500/15 text-emerald-200' : tipo === '-' ? 'bg-red-500/15 text-red-200' : 'text-zinc-300'}`}
              >
                {!diff.criado ? (
                  <span className="shrink-0 select-none px-1.5 text-right text-zinc-600" style={{ width: `${largura + 2}ch` }}>{numero(antes)}</span>
                ) : null}
                <span className="shrink-0 select-none px-1.5 text-right text-zinc-600" style={{ width: `${largura + 2}ch` }}>{numero(depois)}</span>
                <span className={`w-4 shrink-0 select-none text-center ${tipo === '+' ? 'text-emerald-400' : tipo === '-' ? 'text-red-400' : 'text-transparent'}`}>{tipo === ' ' ? '·' : tipo}</span>
                <span className="pr-3">{texto || ' '}</span>
              </div>
            ))}
          </div>
        ))}
        {diff.cortado ? (
          <div className="border-t border-zinc-800 px-3 py-1.5 font-sans text-[11px] text-zinc-400">
            O diff é maior que isto; o resto está no arquivo.
          </div>
        ) : null}
      </div>
    </div>
  );
}
