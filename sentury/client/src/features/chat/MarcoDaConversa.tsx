import React from 'react';
import { Layers, LoaderCircle } from 'lucide-react';

/** Linha discreta no meio da conversa para o que acontece com ela, não dentro
 * dela: a compactação em curso e a feita. Bolha ou bloco de processamento
 * diziam que alguém estava respondendo. */
export const MarcoDaConversa: React.FC<{ texto: string; emCurso?: boolean }> = ({ texto, emCurso = false }) => (
  <div className="mb-6 flex items-center gap-3 px-1 text-[11.5px] text-zinc-500" role={emCurso ? 'status' : undefined}>
    <span className="h-px flex-1 bg-stone-200" />
    <span className="inline-flex items-center gap-2 rounded-full border border-stone-200 bg-[#fffdf8] px-3 py-1.5 font-medium">
      <Layers className="h-3.5 w-3.5 text-gold-hover" />
      {texto}
      {emCurso ? <LoaderCircle className="h-3 w-3 animate-spin text-gold-hover" aria-hidden /> : null}
    </span>
    <span className="h-px flex-1 bg-stone-200" />
  </div>
);
