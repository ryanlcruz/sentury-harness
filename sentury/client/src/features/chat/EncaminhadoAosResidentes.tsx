import React from 'react';
import { Send, Users } from 'lucide-react';
import { PilulaDoResidente } from '../residentes/NaConversa';
import { abrirAssuntoDaMesa, abrirConversaDoResidente } from '../residentes/abrirConversa';
import { nomeVisivel } from '../residentes/api';

/** O pedido saiu para os residentes: uma linha, não um balão de resposta. Cada
 * nome abre o chat dele, onde fica a troca completa. O que o servidor escreveu
 * depois do "Mandei para…" (aviso, recusa) continua visível. */
export const EncaminhadoAosResidentes: React.FC<{ nomes: string[]; texto: string }> = ({ nomes, texto }) => {
  const resto = texto.replace(/^Mandei para [^.]*\.\s*/, '');
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-1.5 gap-y-1 px-1 text-[12.5px] text-zinc-500" data-encaminhado>
      <Send className="h-3.5 w-3.5 text-gold-hover" aria-hidden />
      <span>Enviado para</span>
      {nomes.map(nome => (
        <button key={nome} type="button" onClick={() => abrirConversaDoResidente(nome)}
                title={`Abrir a conversa com ${nomeVisivel(nome)}`} className="rounded-full hover:opacity-80">
          <PilulaDoResidente nome={nome} />
        </button>
      ))}
      {resto ? <span>{resto}</span> : null}
    </div>
  );
};

/** A fala foi para a Mesa: o assunto e o caminho até ele. */
export const EncaminhadoAMesa: React.FC<{ id: string; titulo: string; texto: string }> = ({ id, titulo, texto }) => {
  const resto = texto.replace(/^(Abri|Falei) na Mesa: .*?\.\s+(?=A conversa segue)/, '');
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-1.5 gap-y-1 px-1 text-[12.5px] text-zinc-500" data-encaminhado>
      <Users className="h-3.5 w-3.5 text-gold-hover" aria-hidden />
      <span>Na Mesa:</span>
      <button type="button" onClick={() => abrirAssuntoDaMesa(id)} title="Abrir o assunto na Mesa"
              className="rounded-full border border-[#e3ddcd] bg-[#f3efe4] px-2 py-px text-[13px] font-semibold text-zinc-800 hover:border-gold">
        {titulo}
      </button>
      <span>{resto}</span>
    </div>
  );
};
