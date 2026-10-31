import { PermissaoPayload } from '../events/session-events';
export type SessionRuntimeStatus =
  | 'idle'
  | 'working'
  | 'awaiting_user'
  | 'awaiting_approval'
  | 'finished'
  | 'error'
  | 'interrupted';

export interface Workspace {
  id: string;
  name: string;
  path?: string;
  repository?: string;
  sessionCount: number;
  lastActivityAt: string;
  /** Pasta fechada na lista. Arrumacao do usuario, guardada nesta maquina. */
  recolhida?: boolean;
}

export interface SessionMetadata {
  id: string;
  workspaceId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  runtimeStatus: SessionRuntimeStatus;
  activeProvider?: string;
  tokensUsed: number;
  tags: string[];
  pinned: boolean;
  archived: boolean;
}

export interface ImagemAnexada {
  nome: string;
  /** data URL; vive no turno, nao no estado persistido. */
  dataUrl: string;
}

export interface ChatMessage {
  id: string;
  sessionId: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  traces?: ExecutionStage[];
  imagens?: ImagemAnexada[];
  /** Passos que rodaram algo (codigo, SQL, comando) com o texto do comando. */
  commands?: CommandRun[];
  /** Custo real do turno; so aparece quando o provedor informa. */
  custo?: { ms?: number; modelo?: string; tokens?: number; tokensEntrada?: number; tokensCacheados?: number; usd?: number;
    /** Modelos que recusaram o pedido por política de conteúdo e foram trocados. */
    recusas?: string[] };
  /** <think> do modelo, mostrado so dentro do Processo Analitico. */
  reasoning?: string;
  status?: 'streaming' | 'complete' | 'error' | 'interrupted';
  clarification?: ClarificationPayload;
  permissao?: PermissaoPayload;
  /** O bloco que pediu a permissao (`p1s0`). Sem ele a caixa fica solta. */
  permissaoId?: string | null;
  /** O workflow tocado neste turno, quando houve um. */
  plano?: PlanoPayload;
  signals?: ResponseSignals;
  /** Mais de um arquivo no mesmo turno. Com um so, o preview cheio continua. */
  anexos?: unknown[];
  /** Mensagem que o executor do goal mandou, nao a pessoa. */
  automatico?: boolean;
  /** Fala de um residente que voltou para a conversa. */
  residente?: string;
  /** A pessoa chamou este residente com `@nome`. */
  mencao?: string;
  /** Todos os residentes chamados na mesma fala (`@alfa @nina`). */
  mencoes?: string[];
  /** A fala foi para a Mesa, ou é o resumo de um assunto que nasceu aqui. */
  mesa?: { id: string; titulo: string; resumo?: boolean };
  /** O que o navegador fez neste turno (cartao compacto). */
  navegador?: import('../../features/chat/navegador').CartaoNavegador;
  /** O que o computer use fez; a sessão pode continuar no turno seguinte. */
  computador?: import('../../features/chat/computador').CartaoComputador;
  /** Mandada com o turno rodando, para orientar. Ver features/chat/orientacao.ts. */
  orientacao?: import('../../features/chat/orientacao').OrientacaoDaMensagem;
}

export interface ArtifactValidation {
  status?: 'ok' | 'warning' | 'error' | string;
  previewAvailable?: boolean;
  downloadableArtifact?: boolean;
  errors?: string[];
  warnings?: string[];
}

export interface AttachmentPayload {
  /** Onde o arquivo ficou na pasta de entregas; a conversa guarda só isto. */
  caminho?: string;
  /** A pessoa moveu ou apagou o arquivo. */
  ausente?: boolean;
  artifactId?: string;
  type?: string;
  filename?: string;
  title?: string;
  mimeType?: string;
  contentBase64?: string;
  content?: string;
  chartData?: Record<string, unknown>;
  verifiedPreviewBase64?: string;
  verifiedPreviewMimeType?: string;
  verifiedPreviewFilename?: string;
}

export interface CouncilPayload {
  perspectives: Record<string, string>;
  tradeOffs: string[];
  consensus: string;
}

export interface SubagentResult {
  role: string;
  status: string;
  summary?: string;
}

export interface DeliberationPayload {
  objective?: string;
  steps: Array<{ tool?: string; observation?: string }>;
  stopReason?: string;
}

/** Uma coisa que o turno guardou: lembrança (`texto`) ou escrita numa skill (`nome`, `acao`). */
export interface Aprendizado {
  tipo: 'memoria' | 'skill';
  texto?: string;
  nome?: string;
  acao?: string;
}

export interface ResponseSignals {
  learned?: string;
  aprendizados?: Aprendizado[];
  skillActivated?: string[];
  funcoesCitadas?: string[];
  proactiveInsight?: { text: string; action?: string };
  council?: CouncilPayload;
  subagents?: { requested: boolean; results: SubagentResult[] };
  deliberation?: DeliberationPayload;
  planQuestion?: string;
  attachment?: unknown;
  attachmentValidation?: ArtifactValidation;
}

export interface ClarificationOption {
  label: string;
  description: string;
}

export interface ClarificationQuestion {
  header: string;
  question: string;
  multiSelect: boolean;
  options: ClarificationOption[];
}

export interface ClarificationPayload {
  intro: string;
  questions: ClarificationQuestion[];
}

export interface CommandRun {
  id: string;
  title: string;
  /** Qual ferramenta rodou. Sem isto a tela so sabe dizer "ferramenta". */
  tool?: string;
  kind?: string;
  /** O verbo da acao: medir, alterar, entregar. Vem de `selos.py`. */
  intent?: string;
  command?: string | null;
  /** O que voltou, curto. Some com a resposta; fica no Processo Analitico. */
  resumo?: string;
  /** A decisao fica no bloco que a originou; ausente depois de aprovar/negar. */
  permissao?: PermissaoPayload;
  /** O bloco que pediu a permissao (`p1s0`). Sem ele a caixa fica solta. */
  permissaoId?: string | null;
  /** `canceled` e do cliente: o passo que o stop pegou no meio. */
  /** `handledError`: falhou, mas uma acao posterior recuperou o turno. */
  status: 'pending' | 'running' | 'ok' | 'error' | 'handledError' | 'skipped' | 'canceled' | 'rejected';
  durationMs?: number;
  /** Arquivo criado ou editado: o que mudou, para abrir no cartao. */
  diff?: import('../events/session-events').DiffDoArquivo;
  /** Comando, script ou codigo: o que ele devolveu, como terminal. */
  saida?: import('../events/session-events').SaidaDoTerminal;
}

export interface ExecutionStage {
  stage: string;
  text?: string;
  durationMs?: number;
  status?: 'pending' | 'running' | 'completed' | 'failed';
}


/** Uma tarefa do checklist, como o backend a publica (`memory/plano.py`). */
export interface TarefaDoPlano {
  id: string;
  titulo: string;
  feito: boolean;
  opcional: boolean;
  /** Portão: trava o que vem depois até ser resolvido. */
  gate: boolean;
  estado: string;
  requisitos?: string;
  tentativas?: number;
  /** Só em portão. */
  opcoes?: string[];
  /** Cron, quando o passo se repete sozinho. */
  agenda?: string;
}

export interface PlanoPayload {
  plano: string;
  tipo?: 'plano' | 'workflow';
  gatilho?: string;
  agendamento_id?: string | null;
  aprovado?: boolean;
  tarefas: TarefaDoPlano[];
  faltam: number;
  proxima?: TarefaDoPlano | null;
  /** aberto | travado | fechado | reaberto — derivado do checklist. */
  estado?: string;
  travado_por?: TarefaDoPlano | null;
  contexto?: string;
  telemetria?: {
    sessoes: number;
    tentativas: number;
    aberto_ha_s: number;
    /** Tarefa que queima tentativa sem sair do lugar. */
    emperradas: { id: string; titulo: string; falhas: number }[];
  };
}
