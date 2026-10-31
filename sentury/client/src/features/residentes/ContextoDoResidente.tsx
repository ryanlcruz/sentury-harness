import React, { useEffect, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { renderMarkdown } from '../../domain/markdown';
import { residentes, type BlocoDeContexto } from './api';

const PROSA = 'prose prose-sm max-w-none text-[13px] leading-relaxed text-zinc-700 prose-headings:text-zinc-900 prose-headings:font-semibold prose-h2:mb-1 prose-h2:mt-4 prose-h2:text-sm prose-li:my-0.5';

const Bloco: React.FC<{ bloco: BlocoDeContexto; abertoDeInicio: boolean }> = ({ bloco, abertoDeInicio }) => {
  const [aberto, setAberto] = useState(abertoDeInicio);
  return (
    <section className="overflow-hidden rounded-2xl border border-[#e3ddcd] bg-[#fffdf8]">
      <button type="button" onClick={() => setAberto(valor => !valor)} aria-expanded={aberto}
        className="flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-[#faf6ea]">
        <span className="flex-1 text-[13px] font-semibold">{bloco.titulo}</span>
        <span className="text-xs tabular-nums text-zinc-500">{bloco.texto.length.toLocaleString('pt-BR')} caracteres</span>
        <ChevronDown className={`h-4 w-4 text-zinc-400 transition-transform ${aberto ? 'rotate-180' : ''}`} />
      </button>
      {aberto ? <div className={`${PROSA} border-t border-[#ebe5d8] px-5 py-4`} dangerouslySetInnerHTML={{ __html: renderMarkdown(bloco.texto) }} /> : null}
    </section>
  );
};

/** O contexto que o turno do residente monta, do jeito que vai ao modelo. */
export const ContextoDoResidente: React.FC<{ nome: string }> = ({ nome }) => {
  const [blocos, setBlocos] = useState<BlocoDeContexto[] | null>(null);
  const [erro, setErro] = useState('');

  useEffect(() => {
    let vivo = true;
    residentes.contexto(nome)
      .then(lidos => { if (vivo) setBlocos(lidos); })
      .catch(() => { if (vivo) setErro('Não consegui ler o contexto agora.'); });
    return () => { vivo = false; };
  }, [nome]);

  if (erro) return <p className="text-sm text-red-600">{erro}</p>;
  if (!blocos) return <p className="text-sm text-zinc-500">Lendo o contexto…</p>;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs leading-relaxed text-zinc-500">
        É isto que entra no turno, além das regras gerais do Sentury (Context Engine). Skills citadas no pedido e
        decisões parecidas com ele só entram no turno, porque dependem do pedido. Editar muda a identidade.
      </p>
      {blocos.map((bloco, indice) => <Bloco key={`${bloco.titulo}-${indice}`} bloco={bloco} abertoDeInicio={indice === 0} />)}
    </div>
  );
};
