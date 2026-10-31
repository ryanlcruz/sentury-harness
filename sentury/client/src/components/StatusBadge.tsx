import React from 'react';
import { Check, Loader2, AlertCircle, Pause, Clock, Circle } from 'lucide-react';
import { SessionRuntimeStatus } from '../contracts/domain/session';

interface StatusBadgeProps {
  status: SessionRuntimeStatus;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, className = '' }) => {
  switch (status) {
    case 'working':
      return (
        <span className={`inline-flex items-center ${className}`} title="Executando">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-500" />
        </span>
      );
    case 'awaiting_approval':
      return (
        <span className={`inline-flex items-center ${className}`} title="Aguardando aprovação">
          <Clock className="h-3.5 w-3.5 text-gold-ink" />
        </span>
      );
    case 'awaiting_user':
      return (
        <span className={`inline-flex items-center ${className}`} title="Aguardando você">
          <Pause className="h-3.5 w-3.5 text-violet-500" />
        </span>
      );
    case 'finished':
      return (
        <span className={`inline-flex items-center ${className}`} title="Concluído">
          <Check className="h-3.5 w-3.5 text-emerald-500" />
        </span>
      );
    case 'error':
      return (
        <span className={`inline-flex items-center ${className}`} title="Falhou">
          <AlertCircle className="h-3.5 w-3.5 text-red-500" />
        </span>
      );
    case 'interrupted':
      return (
        <span className={`inline-flex items-center ${className}`} title="Interrompido">
          <Circle className="h-3.5 w-3.5 text-zinc-400" />
        </span>
      );
    case 'idle':
    default:
      return null;
  }
};
