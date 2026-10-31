import React, { useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import type { SaidaDoTerminal } from '../../contracts/events/session-events';
import { copiar } from '../../runtime/clipboard';

/** As ferramentas cuja saída aparece como terminal (tools/saida_da_tela.py). */
export const TERMINAIS = new Set(['executar_comando', 'executar_script', 'executar_python', 'command_status', 'processos']);

/** Acima disso o terminal recolhe e oferece "mostrar tudo". */
export const LIMITE_RECOLHIDO = 12;
/** Recolhido, o fim que fica à vista. */
const FIM_RECOLHIDO = 8;

type Linha = SaidaDoTerminal['linhas'][number];
export type LinhaVisivel = { origem: 'out' | 'err'; texto: string; indice: number } | { escondidas: number };

/**
 * O que aparece com o terminal recolhido: o fim, que é onde mora o resultado
 * de quase todo comando, e as linhas de erro que ficariam escondidas antes
 * dele. No pytest a falha sai antes do resumo; ela não pode sumir no corte.
 */
export function linhasVisiveis(linhas: Linha[], expandido: boolean): LinhaVisivel[] {
  const todas = linhas.map(([origem, texto], indice) => ({ origem, texto, indice }));
  if (expandido || todas.length <= LIMITE_RECOLHIDO) return todas;
  const fim = todas.slice(-FIM_RECOLHIDO);
  const errosAntes = todas.slice(0, -FIM_RECOLHIDO).filter(linha => linha.origem === 'err');
  const escondidas = todas.length - fim.length - errosAntes.length;
  return [...errosAntes, ...(escondidas > 0 ? [{ escondidas }] : []), ...fim];
}

interface Props {
  saida?: SaidaDoTerminal;
  rodando: boolean;
}

export const SaidaDoTerminalView: React.FC<Props> = ({ saida, rodando }) => {
  const [expandido, setExpandido] = useState(false);
  const [copiado, setCopiado] = useState(false);
  const fundo = useRef<HTMLPreElement>(null);
  const linhas = saida?.linhas || [];
  const visiveis = linhasVisiveis(linhas, expandido);
  const recolhe = linhas.length > LIMITE_RECOLHIDO;
  const codigo = saida?.codigo;

  // Ao vivo, acompanha a última linha, como um terminal. Ao abrir tudo, a
  // altura não muda: a saída inteira rola dentro dela, a partir do fim.
  useEffect(() => {
    if ((rodando || expandido) && fundo.current) fundo.current.scrollTop = fundo.current.scrollHeight;
  }, [rodando, expandido, linhas.length]);

  const copiarSaida = async () => {
    if (await copiar(linhas.map(([, texto]) => texto).join('\n'))) {
      setCopiado(true);
      window.setTimeout(() => setCopiado(false), 1600);
    }
  };

  return (
    <div data-testid="saida-do-terminal">
      <pre
        ref={fundo}
        className="sentury-terminal-scroll max-h-72 overflow-auto border-t border-zinc-800 bg-zinc-950 px-3 py-2 text-[11px] leading-5 text-zinc-100"
      >
        <code>
          {visiveis.map((linha, i) => ('escondidas' in linha ? (
            <span key={`e${i}`} className="block select-none text-zinc-500">··· {linha.escondidas} linha{linha.escondidas === 1 ? '' : 's'}</span>
          ) : (
            <span key={linha.indice} data-origem={linha.origem} className={`block whitespace-pre-wrap break-words ${linha.origem === 'err' ? 'text-red-400' : ''}`}>
              {linha.texto || ' '}
            </span>
          )))}
          {rodando ? <span className="sentury-cursor inline-block h-3 w-[7px] translate-y-0.5 bg-zinc-300" aria-hidden /> : null}
          {!rodando && !linhas.length ? <span className="text-zinc-500">sem saída</span> : null}
        </code>
      </pre>
      <div className="flex flex-wrap items-center gap-2 border-t border-stone-200 bg-stone-50/80 px-3 py-1.5 text-[11px] text-zinc-500">
        {rodando ? (
          <span className="rounded-full bg-gold-soft px-2 py-px font-mono text-[10px] font-medium text-gold-ink">rodando</span>
        ) : codigo != null ? (
          <span className={`rounded-full px-2 py-px font-mono text-[10px] font-medium ${codigo === 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
            exit {codigo}
          </span>
        ) : null}
        {saida?.resumo ? <span className="text-zinc-600">{saida.resumo}</span> : null}
        {saida?.cortadas ? <span>{saida.cortadas} linhas antes não vieram</span> : null}
        <span className="flex-1" />
        {recolhe ? (
          <button type="button" onClick={() => setExpandido(valor => !valor)} className="font-medium text-gold-ink underline-offset-2 hover:underline">
            {expandido ? 'recolher' : `mostrar tudo (${linhas.length} linhas)`}
          </button>
        ) : null}
        {linhas.length ? (
          <button type="button" onClick={() => void copiarSaida()} className="rounded p-1 text-zinc-400 hover:bg-stone-200 hover:text-zinc-700" title="Copiar saída" aria-label="Copiar saída">
            {copiado ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
          </button>
        ) : null}
      </div>
    </div>
  );
};
