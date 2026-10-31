import { useEffect, useState } from 'react';
import { Coruja } from './Coruja';
import { coresDoAgente } from './useEsperando';
import { nomeVisivel, type Agente } from './api';

/** Segundos desde `desde` (epoch em segundos), contados a cada segundo enquanto a vez dura. */
function useSegundosDesde(desde?: number) {
  const [agora, setAgora] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!desde) return;
    const relogio = setInterval(() => setAgora(Date.now() / 1000), 1000);
    return () => clearInterval(relogio);
  }, [desde]);
  return desde ? Math.max(0, Math.floor(agora - desde)) : 0;
}

function duracao(segundos: number) {
  return segundos < 60 ? `${segundos} s` : `${Math.floor(segundos / 60)} min ${segundos % 60} s`;
}

/** A coruja de quem está pensando, com os três pontos de quem digita: mostra que
 * o pedido chegou e está sendo feito, do jeito que um colega mostraria. Com `desde`,
 * diz há quanto tempo, para uma espera longa não parecer travada. */
export function Digitando({ nome, agente, acao, desde }: { nome: string; agente?: Agente; acao?: string; desde?: number }) {
  const segundos = useSegundosDesde(desde);
  return <div role="status" aria-label={acao ? `${nomeVisivel(nome)} está ${acao}` : `${nomeVisivel(nome)} está escrevendo`} className="flex items-center gap-3">
    <Coruja tamanho={32} rotulo={nome} cores={coresDoAgente(agente)} acessorios={agente?.aparencia.acessorios} estado="trabalhando" />
    <div>
      <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-stone-200 bg-white px-3.5 py-2.5">
        <span className="text-xs text-zinc-500">{nomeVisivel(nome)}{acao ? ` · ${acao}` : ''}{segundos >= 10 ? ` · há ${duracao(segundos)}` : ''}</span>
        <span className="flex items-end gap-1" aria-hidden="true">
          {[0, 160, 320].map(atraso => (
            <span key={atraso} className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-400 motion-reduce:animate-none"
              style={{ animationDelay: `${atraso}ms`, animationDuration: '1s' }} />
          ))}
        </span>
      </div>
      {segundos >= 60 ? <p className="mt-1 text-[11px] text-zinc-500">O modelo está demorando mais que o normal para responder. A vez continua aberta.</p> : null}
    </div>
  </div>;
}
