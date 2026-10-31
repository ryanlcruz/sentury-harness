import { StreamParser } from './stream-parser';
import {
  ClarificationEvent,
  DoneEvent,
  ErrorEvent,
  NavegadorEvent,
  ComputadorEvent,
  MensagemNoTurnoEvent,
  InstrucoesDoProjetoEvent,
  DiffEvent,
  SaidaEvent,
  SaidaParcialEvent,
  PermissaoEvent,
  PlanUpdateEvent,
  CompactedEvent,
  ReasoningEvent,
  StageEvent,
  TokenEvent,
  ToolCompleteEvent,
  ToolStartEvent,
} from '../contracts/events/session-events';

export interface StreamCallbacks {
  onStage?: (event: StageEvent) => void;
  onPlanUpdate?: (event: PlanUpdateEvent) => void;
  onToolStart?: (event: ToolStartEvent) => void;
  onToolComplete?: (event: ToolCompleteEvent) => void;
  onReasoning?: (event: ReasoningEvent) => void;
  onCompacted?: (event: CompactedEvent) => void;
  onClarification?: (event: ClarificationEvent) => void;
  onPermissao?: (event: PermissaoEvent) => void;
  onNavegador?: (event: NavegadorEvent) => void;
  onComputador?: (event: ComputadorEvent) => void;
  onMensagemNoTurno?: (event: MensagemNoTurnoEvent) => void;
  onInstrucoesDoProjeto?: (event: InstrucoesDoProjetoEvent) => void;
  onDiff?: (event: DiffEvent) => void;
  onSaida?: (event: SaidaEvent) => void;
  onSaidaParcial?: (event: SaidaParcialEvent) => void;
  onToken?: (event: TokenEvent) => void;
  onDone?: (event: DoneEvent) => void;
  onError?: (event: ErrorEvent | Error) => void;
  /** Cancelamento. Separado de `onError` porque interromper nao e falhar. */
  onAborted?: () => void;
  /** A conexao caiu no meio do turno; tentando voltar (1 de 5, 2 de 5…). */
  onReconectando?: (tentativa: number, total: number) => void;
  onReconectado?: () => void;
  /** O turno nao existe mais para voltar (acabou ha tempo ou outro comecou):
   * o resultado, se houve, esta no historico da conversa. */
  onPerdido?: () => void;
}

/** Esperas entre as tentativas de reconectar. Somam 31 s; o servidor espera 45. */
export const ESPERAS_DE_RECONEXAO = [1000, 2000, 4000, 8000, 16000];

function dormir(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('abort', 'AbortError')); }, { once: true });
  });
}

export class StreamClient {
  private parser = new StreamParser();

  /**
   * Envia mensagem para o endpoint de streaming e processa eventos em tempo real
   */
  public async streamChat(
    apiUrl: string,
    payload: {
      message: string;
      session_id: string;
      user_id: string;
      mode: 'router' | 'ultra' | 'ultra_max';
      effort: 'auto' | 'low' | 'medium' | 'high';
      imagens?: Array<{ nome: string; data_url: string }>;
      arquivos?: Array<{ nome: string; data_url: string }>;
      funcoes?: string[];
      regenerate?: boolean;
    },
    callbacks: StreamCallbacks,
    signal?: AbortSignal,
    headers: Record<string, string> = {},
  ): Promise<void> {
    this.parser.reset();
    let transmissao = '';

    try {
      const response = await fetch(`${apiUrl}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          ...headers,
        },
        body: JSON.stringify(payload),
        signal,
      });

      if (!response.ok) {
        throw new Error(`Erro HTTP ${response.status}: ${response.statusText}`);
      }
      transmissao = response.headers.get('X-Sentury-Transmissao') || '';
      if (await this.ler(response, callbacks)) return;
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        // Voltar em silencio deixava o turno preso em "Redigindo" quando o
        // abort vinha de outro caminho que nao o botao de parar.
        callbacks.onAborted?.();
        return;
      }
      // Nem comecou (erro HTTP, servidor fora): nao ha turno para voltar.
      if (!transmissao) {
        callbacks.onError?.(err instanceof Error ? err : new Error(String(err)));
        return;
      }
    }
    if (signal?.aborted) {
      callbacks.onAborted?.();
      return;
    }

    // A conexao caiu no meio do turno. O servidor segura o turno por 45 s
    // (harness/transmissao.py): volta de onde parou, sem perder nem repetir.
    const url = (desde: number) => `${apiUrl}/chat/stream/${encodeURIComponent(payload.session_id)}/retomar`
      + `?desde=${desde}&transmissao_id=${encodeURIComponent(transmissao)}`;
    for (let tentativa = 0; tentativa < ESPERAS_DE_RECONEXAO.length; tentativa += 1) {
      callbacks.onReconectando?.(tentativa + 1, ESPERAS_DE_RECONEXAO.length);
      try {
        await dormir(ESPERAS_DE_RECONEXAO[tentativa], signal);
        const antes = this.parser.ultimoId;
        const res = await fetch(url(antes), { headers: { Accept: 'text/event-stream', ...headers }, signal });
        if (res.status === 404) {
          callbacks.onPerdido?.();
          return;
        }
        if (!res.ok || !res.body) continue;
        callbacks.onReconectado?.();
        this.parser.novaConexao();
        if (await this.ler(res, callbacks)) return;
        // Voltou, andou e caiu de novo: as tentativas recomecam.
        if (this.parser.ultimoId > antes) tentativa = -1;
      } catch (err: any) {
        if (err?.name === 'AbortError' || signal?.aborted) {
          callbacks.onAborted?.();
          return;
        }
      }
    }
    callbacks.onError?.(new Error(
      `Perdi a conexao com o servidor e nao consegui voltar depois de ${ESPERAS_DE_RECONEXAO.length} tentativas.`));
  }

  /** Le os eventos de uma resposta ate ela acabar. Devolve se chegou evento
   * terminal (done, error, parado). */
  private async ler(response: Response, callbacks: StreamCallbacks): Promise<boolean> {
    let receivedTerminalEvent = false;
    if (!response.body) throw new Error('A resposta do servidor não possui corpo de stream.');
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const text = decoder.decode(value, { stream: true });
      const events = this.parser.feed(text);

      for (const evt of events) {
        switch (evt.type) {
          case 'stage':
            callbacks.onStage?.(evt);
            break;
          case 'plan_update':
            callbacks.onPlanUpdate?.(evt);
            break;
          case 'tool_start':
            callbacks.onToolStart?.(evt);
            break;
          case 'tool_complete':
            callbacks.onToolComplete?.(evt);
            break;
          case 'reasoning':
            callbacks.onReasoning?.(evt);
            break;
          case 'compacted':
            callbacks.onCompacted?.(evt);
            break;
          case 'clarification':
            callbacks.onClarification?.(evt);
            break;
          case 'permissao':
            callbacks.onPermissao?.(evt);
            break;
          case 'navegador':
            callbacks.onNavegador?.(evt);
            break;
          case 'computador':
            callbacks.onComputador?.(evt);
            break;
          case 'diff':
            callbacks.onDiff?.(evt);
            break;
          case 'saida':
            callbacks.onSaida?.(evt);
            break;
          case 'saida_parcial':
            callbacks.onSaidaParcial?.(evt);
            break;
          case 'instrucoes_do_projeto':
            callbacks.onInstrucoesDoProjeto?.(evt);
            break;
          case 'mensagem_no_turno':
            callbacks.onMensagemNoTurno?.(evt);
            break;
          case 'token':
            callbacks.onToken?.(evt);
            break;
          case 'done':
            receivedTerminalEvent = true;
            callbacks.onDone?.(evt);
            break;
          case 'error':
            receivedTerminalEvent = true;
            callbacks.onError?.(evt);
            break;
          case 'parado':
            // O servidor parou o turno a pedido (o atalho do computer use):
            // mesmo caminho do botao de parar, nao "conexao encerrada".
            receivedTerminalEvent = true;
            callbacks.onAborted?.();
            break;
        }
      }
    }

    return receivedTerminalEvent;
  }
}
