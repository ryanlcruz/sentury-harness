import React, { useCallback } from 'react';

interface ResizeHandleProps {
  /** Largura atual em px. */
  width: number;
  onResize: (width: number) => void;
  min?: number;
  /** Fracao da janela que o painel pode ocupar no maximo. */
  maxFraction?: number;
  side?: 'left' | 'right';
}

// A captura do ponteiro mantém o redimensionamento mesmo fora do punho.
export const ResizeHandle: React.FC<ResizeHandleProps> = ({
  width,
  onResize,
  min = 380,
  maxFraction = 0.78,
  side = 'right',
}) => {
  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (window.matchMedia('(max-width: 760px)').matches) return;
      event.preventDefault();
      const punho = event.currentTarget;
      punho.setPointerCapture(event.pointerId);

      const mover = (e: PointerEvent) => {
        const bruto = side === 'right' ? window.innerWidth - e.clientX : e.clientX;
        onResize(Math.round(Math.max(min, Math.min(window.innerWidth * maxFraction, bruto))));
      };
      const soltar = () => {
        punho.removeEventListener('pointermove', mover);
        punho.removeEventListener('pointerup', soltar);
      };
      punho.addEventListener('pointermove', mover);
      punho.addEventListener('pointerup', soltar);
    },
    [min, maxFraction, onResize, side],
  );

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Redimensionar painel"
      onPointerDown={onPointerDown}
      title={`Arraste para redimensionar · ${width}px`}
      className={`absolute inset-y-0 ${side === 'right' ? 'left-0' : 'right-0'} z-20 w-1.5 cursor-ew-resize bg-transparent transition-colors hover:bg-gold/40`}
    />
  );
};
