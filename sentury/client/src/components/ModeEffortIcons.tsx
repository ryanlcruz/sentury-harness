import React from 'react';

// Modo e esforço usam formas diferentes para não parecer a mesma escolha.
// Misturar as duas fazia o usuário confundir escolha de modelo com esforço.

type Props = { className?: string };

const base = 'h-3.5 w-3.5 shrink-0';

export const IconeModo: React.FC<Props & { mode: string }> = ({ mode, className = base }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinejoin="round" aria-hidden="true">
    <rect x="5" y="5" width="14" height="14" rx="4" fill={mode === 'ultra_max' ? 'currentColor' : 'none'} />
    {mode === 'ultra' && <rect x="9" y="9" width="6" height="6" rx="2" fill="currentColor" stroke="none" />}
  </svg>
);

const BARRAS: Record<string, string> = {
  low: 'M4 18h3V9H4zM10.5 18h3V5h-3z',
  medium: 'M4 18h3V9H4zM10.5 18h3V5h-3zM17 18h3v-8h-3z',
  high: 'M4 18h3V9H4zM10.5 18h3V5h-3zM17 18h3V2h-3z',
};

export const IconeEsforco: React.FC<Props & { effort: string }> = ({ effort, className = base }) => {
  if (effort === 'auto') {
    return (
      <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" aria-hidden="true">
        <path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d={BARRAS[effort] || BARRAS.medium} />
    </svg>
  );
};
