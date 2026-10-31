import { SseEvent, SseEventSchema } from '../contracts/events/session-events';

// Um turno que terminou no servidor precisa terminar na tela.
const TERMINAIS = new Set(['done', 'error', 'parado']);

export interface StreamParserOptions {
  /** Chamado quando um evento chega divergindo do schema, terminal ou não. */
  onDivergencia?: (tipo: string, erro: unknown, bruto: unknown) => void;
}

export class StreamParser {
  private buffer = '';
  /** O `id:` do ultimo evento: e dele que a reconexao continua. */
  public ultimoId = 0;

  constructor(private readonly options: StreamParserOptions = {}) {}

  /**
   * Evento comum que nao valida e descartado. Terminal passa assim mesmo:
   * descarta-lo prendia o turno em "Redigindo" com o backend ja respondido.
   */
  public feed(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const events: SseEvent[] = [];

    // Linhas SSE são separadas por \n\n
    const parts = this.buffer.split('\n\n');
    this.buffer = parts.pop() ?? ''; // Mantém a última parte incompleta no buffer

    for (const part of parts) {
      // O id recebido permite retomar o stream sem repetir eventos.
      const linhas = part.trim().split('\n');
      const comId = linhas.find(l => l.startsWith('id: '));
      if (comId) this.ultimoId = Number(comId.slice(4)) || this.ultimoId;
      const line = (linhas.find(l => l.startsWith('data: ')) || '').trim();
      if (!line) continue;

      if (line.startsWith('data: ')) {
        const jsonStr = line.slice(6).trim();
        if (jsonStr === '[DONE]') continue;

        try {
          const raw = JSON.parse(jsonStr);
          const parsed = SseEventSchema.safeParse(raw);
          if (parsed.success) {
            events.push(parsed.data);
            continue;
          }

          const tipo = String((raw as { type?: unknown })?.type ?? '');
          this.options.onDivergencia?.(tipo, parsed.error, raw);

          if (TERMINAIS.has(tipo)) {
            console.warn(
              `[StreamParser] Evento "${tipo}" divergiu do schema e foi aproveitado mesmo assim:`,
              parsed.error,
            );
            events.push(raw as SseEvent);
          } else {
            console.warn('[StreamParser] Evento descartado por violação de schema:', parsed.error, raw);
          }
        } catch (e) {
          console.error('[StreamParser] Erro de JSON parse em linha SSE:', e, jsonStr);
        }
      }
    }

    return events;
  }

  public reset(): void {
    this.buffer = '';
    this.ultimoId = 0;
  }

  /** Conexao nova do mesmo turno: descarta o pedaco pela metade, guarda o id. */
  public novaConexao(): void {
    this.buffer = '';
  }
}
