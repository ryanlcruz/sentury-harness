import { useId } from 'react';

// A mesma seta que aparece na tela e na página enquanto o agente está com o mouse.
export function SetaDoAgente({ tamanho = 18 }: { tamanho?: number }) {
  const degrade = `seta-${useId().replace(/:/g, '')}`;
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 24 24" aria-hidden="true">
      <defs>
        <linearGradient id={degrade} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#2cd4f5" />
          <stop offset=".35" stopColor="#1f6bff" />
          <stop offset=".55" stopColor="#2a3cf0" />
          <stop offset=".8" stopColor="#8b3dff" />
          <stop offset="1" stopColor="#e04be8" />
        </linearGradient>
      </defs>
      <path
        d="M4.8 4.3L20.6 14.2L11.8 14.6L8.8 20.6z"
        fill={`url(#${degrade})`}
        stroke={`url(#${degrade})`}
        strokeWidth="3.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}
