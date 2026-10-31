import { CAPABILITIES } from '../../components/CapabilityMark';

/**
 * A conexão com o servidor caiu no meio do turno e a tela está tentando voltar
 * (transport/stream-client.ts). Não afirma que o turno segue: se o servidor
 * caiu junto, não há turno, e a volta dá 404 (a conversa então recarrega do
 * servidor e, depois de reinício, o cartão de Continuar aparece).
 * Cor e ícone do Router: é a camada de conexão, não um erro.
 */
export function ReconectandoAviso({ tentativa, total }: { tentativa: number; total: number }) {
  const { Icon, texto, fundo, borda } = CAPABILITIES.router;
  return (
    <div role="status" className={`mb-5 flex max-w-3xl items-center gap-2.5 rounded-lg border px-3 py-2 ${fundo} ${borda}`}>
      <Icon className={`h-4 w-4 shrink-0 animate-pulse ${texto}`} aria-hidden />
      <span className="min-w-0 flex-1 text-xs text-zinc-700">
        <span className="font-semibold text-zinc-900">A conexão caiu.</span> Tentando voltar ao turno…
      </span>
      <span className={`shrink-0 font-mono text-[11px] tabular-nums ${texto}`}>{tentativa} de {total}</span>
    </div>
  );
}
