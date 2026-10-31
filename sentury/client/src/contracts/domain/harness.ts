export interface HarnessTelemetry {
  execution_ms?: number;
  tokens_used?: number;
  provider?: string;
  total_ms?: number;
  context_messages?: number;
  context_chars?: number;
  context_status?: string;
  limit_messages?: number;
  limit_chars?: number;
  /** Do que é feita a última chamada do planejador, em caracteres. */
  fatias?: { sistema: number; ferramentas: number; historico: number; pedido_e_contexto: number } | null;
  tokens?: { entrada?: number; cacheado?: number } | null;
  [key: string]: unknown;
}

export interface HarnessEvent {
  stage?: string;
  provider?: string;
  score?: number;
  tool?: string;
  duration_ms?: number;
  [key: string]: any;
}

export interface HarnessState {
  proposed_tool?: string;
  harness_allowed?: boolean;
  harness_reason?: string;
  events?: HarnessEvent[];
  telemetry?: HarnessTelemetry;
  status: 'online' | 'offline' | 'busy' | 'error';
  model?: string;
  rawState?: Record<string, unknown> | null;
  compacted?: boolean;
  compaction?: unknown;
}
