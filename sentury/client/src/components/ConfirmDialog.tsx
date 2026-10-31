import React from 'react';
import { AlertTriangle } from 'lucide-react';

// `window.confirm` some quando o client vira programa empacotado e nao tem a
// cara do produto. Confirmacao passa a ser componente da propria interface.
interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  title,
  description,
  confirmLabel = 'Confirmar',
  cancelLabel = 'Cancelar',
  destructive = false,
  onConfirm,
  onCancel,
}) => {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/30 p-6 animate-[sentury-modal-in_140ms_ease-out]" role="dialog" aria-modal="true">
      <button type="button" className="absolute inset-0 cursor-default bg-transparent" onClick={onCancel} aria-label={cancelLabel} />
      <div className="relative w-full max-w-md rounded-2xl border border-stone-300 bg-[#fffdf8] p-5 shadow-2xl">
        <div className="flex items-start gap-3">
          <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${destructive ? 'bg-red-50 text-red-600' : 'bg-gold-soft text-gold-ink'}`}>
            <AlertTriangle className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
            {description && <p className="mt-1 text-xs leading-5 text-zinc-600">{description}</p>}
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-lg border border-stone-300 px-3 py-2 text-xs font-medium text-zinc-700 hover:bg-stone-100">
            {cancelLabel}
          </button>
          <button
            type="button"
            autoFocus
            onClick={onConfirm}
            className={`rounded-lg px-3 py-2 text-xs font-semibold ${destructive ? 'bg-red-600 text-white hover:bg-red-700' : 'bg-zinc-900 text-gold hover:bg-black'}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};
