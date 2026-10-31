import React, { useState } from 'react';
import { Coruja, CORES_DO_SENTURY } from '../features/residentes/Coruja';

const TAMANHO = 110;

/** O logo da tela inicial. Um clique troca pela coruja do Escritório, outro volta. */
export const LogoQueViraCoruja: React.FC = () => {
  const [coruja, setCoruja] = useState(false);
  const visivel = 'opacity-100 scale-100';
  const escondido = 'pointer-events-none opacity-0 scale-75';
  return (
    <button
      type="button"
      onClick={() => setCoruja(atual => !atual)}
      aria-label={coruja ? 'Mostrar o logo do Sentury' : 'Mostrar a coruja do Sentury'}
      className="relative mx-auto block rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold"
      style={{ width: TAMANHO, height: TAMANHO }}
    >
      <img
        src="/sentury-logo.webp"
        alt=""
        aria-hidden={coruja}
        width={TAMANHO}
        height={TAMANHO}
        className={`absolute inset-0 h-full w-full object-contain transition duration-300 ease-out motion-reduce:transition-none ${coruja ? escondido : visivel}`}
      />
      <span
        aria-hidden={!coruja}
        className={`absolute inset-0 transition duration-300 ease-out motion-reduce:transition-none ${coruja ? visivel : escondido}`}
      >
        <Coruja cores={CORES_DO_SENTURY} tamanho={TAMANHO} rotulo="Sentury" />
      </span>
    </button>
  );
};
