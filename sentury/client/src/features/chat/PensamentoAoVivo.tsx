import React, { useEffect, useRef, useState } from 'react';
import { renderMarkdown } from '../../domain/markdown';

interface PensamentoAoVivoProps {
  texto: string;
}

// O provedor entrega o raciocínio de uma vez, no fim da geração — não há
// streaming real de token vindo dele. A revelação por palavra é local, igual
// ao "efeito digitando" que a resposta já usa: o texto que aparece é sempre o
// que o modelo escreveu, só que servido no ritmo da leitura.
const PALAVRAS_POR_PASSO = 3;
const INTERVALO_MS = 40;

export const PensamentoAoVivo: React.FC<PensamentoAoVivoProps> = ({ texto }) => {
  const [reveladas, setReveladas] = useState(0);
  const palavras = useRef<string[]>([]);

  useEffect(() => {
    palavras.current = (texto || '').split(/(\s+)/);
    setReveladas(atual => Math.min(atual, palavras.current.length));
  }, [texto]);

  useEffect(() => {
    if (reveladas >= palavras.current.length) return;
    const id = window.setTimeout(
      () => setReveladas(atual => Math.min(atual + PALAVRAS_POR_PASSO, palavras.current.length)),
      INTERVALO_MS,
    );
    return () => window.clearTimeout(id);
  }, [reveladas, texto]);

  const visivel = palavras.current.slice(0, reveladas).join('');
  if (!visivel.trim()) return null;

  return (
    <div
      className="sentury-pensamento mt-2 text-[11px] italic leading-5 text-zinc-400/90"
      dangerouslySetInnerHTML={{ __html: renderMarkdown(visivel) }}
    />
  );
};
