import React from 'react';

interface SeverityCellProps {
  value: string | number;
  type?: string;
}

export const SeverityCell: React.FC<SeverityCellProps> = ({ value }) => {
  const strVal = String(value).trim();
  const numVal = parseFloat(strVal.replace(/[^\d.-]/g, ''));

  let severityClass = 'text-zinc-700 font-medium';

  if (!isNaN(numVal)) {
    // Se for NPS
    if (strVal.startsWith('-') || numVal < -10) {
      severityClass = 'text-red-600 bg-red-50 dark:bg-red-950/40 dark:text-red-400 px-2 py-0.5 rounded border border-red-200 dark:border-red-900/50 font-semibold';
    } else if (numVal > 0 && numVal <= 100 && (strVal.includes('%') ? numVal >= 85 : numVal > 10)) {
      severityClass = 'text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 dark:text-emerald-400 px-2 py-0.5 rounded border border-emerald-200 dark:border-emerald-900/50 font-semibold';
    } else if (numVal >= -10 && numVal <= 10) {
      severityClass = 'text-gold-ink bg-gold-soft px-2 py-0.5 rounded border border-gold/45 font-semibold';
    }
  }

  return <span className={`inline-block text-xs ${severityClass}`}>{strVal}</span>;
};
