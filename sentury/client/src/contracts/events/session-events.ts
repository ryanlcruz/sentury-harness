import { z } from 'zod';

// Vocabulario fechado do `kind`, espelhando `AnalysisOrchestrator.TOOL_KINDS`.
// A interface escolhe o visual pelo TIPO da acao, nao pelo nome da ferramenta —
// e por isso que toda ferramenta aparece consistente sem tratamento caso a caso.
// Como `z.string()` livre, um `kind` desconhecido chegava na tela e nao tinha
// desenho; como enum, ele falha na borda, que e onde da para consertar.
export const ToolKindSchema = z.enum([
  'read', 'execute', 'edit', 'delete', 'move', 'search', 'fetch', 'other',
]);

// O que a acao SIGNIFICA, espelhando `SenturyOrchestrator.ACTION_INTENTS`.
// `kind` responde "como desenho isto"; o intent responde "o que o agente estava
// tentando fazer". Sao perguntas diferentes: exportar em PDF e em XLSX tem o
// mesmo kind e a mesma intencao, enquanto rodar SQL e chamar uma analise
// executam de formas opostas com a mesma intencao de medir.
export const ActionIntentSchema = z.enum([
  'medir', 'investigar', 'recomendar', 'entregar', 'consultar',
  'alterar', 'executar', 'perguntar', 'pensar', 'outro',
]);

export const StageEventSchema = z.object({
  type: z.literal('stage'),
  text: z.string(),
});

// O que mudou num arquivo criado ou editado (sentury/tools/diff_de_arquivo.py).
// Cada linha: [tipo '+', '-' ou ' ', texto, linha antes, linha depois].
export const DiffDoArquivoSchema = z.object({
  arquivo: z.string(),
  criado: z.boolean().default(false),
  adicionadas: z.number(),
  removidas: z.number(),
  trechos: z.array(z.object({
    cabecalho: z.string(),
    linhas: z.array(z.tuple([z.string(), z.string(), z.number().nullable(), z.number().nullable()])),
  })),
  cortado: z.boolean().default(false),
});

// A saida de comando, script ou codigo, como terminal (tools/saida_da_tela.py):
// linhas na ordem em que sairam, cada uma com a origem (out = saida normal,
// err = stderr), o codigo de saida (null enquanto roda) e um resumo quando a
// saida e reconhecida. `aoVivo` e do cliente: ainda chegando pelo saida_parcial.
export const SaidaDoTerminalSchema = z.object({
  linhas: z.array(z.tuple([z.enum(['out', 'err']), z.string()])),
  cortadas: z.number().default(0),
  codigo: z.number().nullable().optional(),
  resumo: z.string().nullable().optional(),
  aoVivo: z.boolean().optional(),
});

export const PlanEntrySchema = z.object({
  id: z.string(),
  title: z.string(),
  // O nome da ferramenta chegava no evento e morria aqui: a tela dizia
  // "Executando ferramenta" sem nunca dizer qual.
  tool: z.string().optional(),
  /** O que a ferramenta devolveu, curto. Execucao sem resultado e meia execucao. */
  resumo: z.string().optional(),
  /** O que ele disse que ia fazer neste passo, antes de rodar. */
  fala: z.string().nullable().optional(),
  // `canceled` e do cliente, nao do servidor: quando o usuario para o turno,
  // o passo que estava rodando nao terminou nem falhou — e o unico estado que
  // o backend nunca vai mandar, porque ele foi interrompido antes.
  status: z.enum(['pending', 'running', 'ok', 'error', 'handledError', 'skipped', 'canceled', 'rejected']).default('pending'),
  kind: ToolKindSchema.optional(),
  intent: ActionIntentSchema.optional(),
  // O que roda de fato (codigo, SQL, comando). Execucao nao pode ser invisivel.
  command: z.string().nullable().optional(),
  durationMs: z.number().optional(),
  /** Arquivo criado ou editado neste passo: o que mudou. */
  diff: DiffDoArquivoSchema.optional(),
  /** Comando, script ou codigo: o que ele devolveu, como terminal. */
  saida: SaidaDoTerminalSchema.optional(),
});

export const PlanUpdateEventSchema = z.object({
  type: z.literal('plan_update'),
  entries: z.array(PlanEntrySchema),
});

export const ToolStartEventSchema = z.object({
  type: z.literal('tool_start'),
  id: z.string(),
  tool: z.string(),
  title: z.string(),
  kind: ToolKindSchema.optional(),
  intent: ActionIntentSchema.optional(),
  command: z.string().nullable().optional(),
  fala: z.string().nullable().optional(),
});

export const ToolCompleteEventSchema = z.object({
  type: z.literal('tool_complete'),
  id: z.string(),
  // `rejected` nao e `error`: "o agente errou" e "a politica barrou" pedem
  // reacoes diferentes de quem le, e o triangulo vermelho dizia a primeira nos
  // dois casos. `pending` é o passo que parou no cartão de permissão.
  status: z.enum(['ok', 'error', 'handledError', 'skipped', 'rejected', 'pending']),
  duration_ms: z.number().optional(),
  resumo: z.string().optional(),
});

export const CompactedEventSchema = z.object({
  type: z.literal('compacted'),
  mensagens_antes: z.number(),
  mensagens_depois: z.number(),
  uso_antes_pct: z.number().optional(),
  uso_depois_pct: z.number().optional(),
}).passthrough();

export const ReasoningEventSchema = z.object({
  type: z.literal('reasoning'),
  text: z.string(),
});

export const ClarificationSchema = z.object({
  intro: z.string(),
  questions: z.array(z.object({
    header: z.string(),
    question: z.string(),
    multiSelect: z.boolean().default(false),
    options: z.array(z.object({
      label: z.string(),
      description: z.string().default(''),
    })),
  })).min(1).max(4),
});

export const ClarificationEventSchema = z.object({
  type: z.literal('clarification'),
  clarification: ClarificationSchema,
});

// Comando que altera alguma coisa para o turno e pergunta. Chega como evento
// ao vivo e tambem no `done`, pelo mesmo motivo do clarification: a folha
// aparece no instante em que a decisao e necessaria, sem esperar o fim.
export const PermissaoSchema = z.object({
  chave: z.string(),
  comando: z.string(),
  motivo: z.string().default(''),
  /** Candidatura, envio de dado: so "so desta vez" libera, entao so ela aparece. */
  so_desta_vez: z.boolean().optional(),
  /** `scripts`: "nesta conversa" vale para os próximos scripts na pasta de trabalho. */
  nesta_conversa: z.string().optional(),
  /** Quem pediu e com o quê: o `criar_agente` vira o cartão da fábrica. */
  ferramenta: z.string().optional(),
  argumentos: z.record(z.string(), z.unknown()).optional(),
  /** Mais de um `criar_agente` no mesmo plano: o cartão da equipe. */
  equipe: z.array(z.record(z.string(), z.unknown())).optional(),
});

export const PermissaoEventSchema = z.object({
  type: z.literal('permissao'),
  permissao: PermissaoSchema,
  /** O passo que pediu. Sem ele a caixa vive fora do bloco que a originou. */
  id: z.string().nullable().optional(),
});

const CouncilSchema = z.object({
  perspectives: z.record(z.string(), z.string()).default({}),
  trade_offs: z.array(z.string()).default([]),
  consensus_recommendation: z.string().default(''),
}).passthrough();

const SubagentsSchema = z.object({
  requested: z.boolean().default(false),
  results: z.array(z.object({
    role: z.string(),
    status: z.string(),
    summary: z.string().optional(),
  }).passthrough()).default([]),
}).passthrough();

const DeliberationSchema = z.object({
  objective: z.string().optional(),
  steps: z.array(z.object({
    tool: z.string().optional(),
    observation: z.string().optional(),
  }).passthrough()).default([]),
  reasoning_summary: z.string().optional(),
  stop_reason: z.string().optional(),
}).passthrough();

const ArtifactValidationSchema = z.object({
  status: z.string().optional(),
  preview_available: z.boolean().optional(),
  downloadable_artifact: z.boolean().optional(),
  errors: z.array(z.string()).optional(),
  warnings: z.array(z.string()).optional(),
}).passthrough();

export const TokenEventSchema = z.object({
  type: z.literal('token'),
  text: z.string(),
});

export const HarnessDoneResultSchema = z.object({
  message: z.string(),
  attachment: z.unknown().nullable().optional(),
  harness: z.object({
    proposed_tool: z.string().nullable().optional(),
    harness_allowed: z.boolean().nullable().optional(),
    harness_reason: z.string().nullable().optional(),
    events: z.array(z.record(z.string(), z.unknown())).nullable().optional(),
    artifact_validation: ArtifactValidationSchema.optional(),
  }).passthrough().optional(),
  telemetry: z.object({
    execution_ms: z.number().optional(),
    tokens_used: z.number().optional(),
    provider: z.string().optional(),
    total_ms: z.number().optional(),
    context_messages: z.number().optional(),
    context_chars: z.number().optional(),
    context_status: z.string().optional(),
    limit_messages: z.number().optional(),
    limit_chars: z.number().optional(),
    model: z.string().optional(),
    tokens: z.object({
      entrada: z.number().default(0),
      saida: z.number().default(0),
      cacheado: z.number().optional(),
      total: z.number().default(0),
      chamadas: z.number().default(0),
    }).nullable().optional(),
    custo_usd: z.number().nullable().optional(),
    recusas: z.array(z.object({ provedor: z.string(), modelo: z.string().nullable().optional() }).passthrough())
      .nullable().optional(),
  }).passthrough().optional(),
  state: z.record(z.string(), z.unknown()).nullable().optional(),
  clarification: ClarificationSchema.optional(),
  permissao: PermissaoSchema.nullable().optional(),
  learned: z.string().nullable().optional(),
  aprendizados: z.array(z.object({
    tipo: z.enum(['memoria', 'skill']),
    texto: z.string().optional(),
    nome: z.string().optional(),
    acao: z.string().optional(),
  })).nullable().optional(),
  council: CouncilSchema.nullable().optional(),
  // O plano vem do disco, entao o formato e do backend: `passthrough` deixa o
  // card ler campo novo (agenda, opcoes) sem o contrato virar gargalo.
  plano: z.object({
    plano: z.string(),
    tarefas: z.array(z.record(z.string(), z.unknown())).default([]),
    faltam: z.number().default(0),
    estado: z.string().optional(),
    travado_por: z.record(z.string(), z.unknown()).nullable().optional(),
    telemetria: z.record(z.string(), z.unknown()).optional(),
  }).passthrough().nullable().optional(),
  subagents_beta: SubagentsSchema.nullable().optional(),
  proactive_insight: z.object({
    text: z.string(),
    action: z.string().optional(),
  }).passthrough().nullable().optional(),
  skill_activated: z.array(z.string()).nullable().optional(),
  deliberation: DeliberationSchema.nullable().optional(),
  plan_question: z.string().nullable().optional(),
  compacted: z.boolean().optional(),
  compactacao: z.unknown().nullable().optional(),
}).passthrough();

// Um passo do navegador: o cartao no chat acompanha por estes eventos.
// Ver features/chat/navegador.ts e harness/cartao_do_navegador.py.
export const NavegadorEventSchema = z.object({
  type: z.literal('navegador'),
  fase: z.string(),
  site: z.string().optional(),
  passos: z.array(z.object({ acao: z.string().optional(), rotulo: z.string().optional() })).optional(),
  indice: z.number().optional(),
  status: z.string().optional(),
  leitura: z.string().optional(),
  motivo: z.string().optional(),
  retomada: z.boolean().optional(),
}).passthrough();

// Um gesto do computer use (sentury/tools/computador.py): `rodando`, depois
// `ok`, `erro` ou `parado`. Ver features/chat/computador.ts.
export const ComputadorEventSchema = z.object({
  type: z.literal('computador'),
  fase: z.string(),
  acao: z.string().optional(),
  titulo: z.string().optional(),
  descricao: z.string().optional(),
  fala: z.string().optional(),
  status: z.string().optional(),
  tecla: z.string().optional(),
  prints: z.number().optional(),
  janela: z.string().optional(),
  objetivo: z.string().optional(),
  turno: z.number().optional(),
  limite: z.number().optional(),
  retomada: z.boolean().optional(),
}).passthrough();

export const DiffEventSchema = DiffDoArquivoSchema.extend({
  type: z.literal('diff'),
  ferramenta: z.string(),
});

export const SaidaEventSchema = SaidaDoTerminalSchema.extend({
  type: z.literal('saida'),
  ferramenta: z.string(),
});

export const SaidaParcialEventSchema = z.object({
  type: z.literal('saida_parcial'),
  ferramenta: z.string(),
  linhas: z.array(z.tuple([z.enum(['out', 'err']), z.string()])),
});

// Mensagem mandada com o turno rodando (harness/caixa_do_turno.py): entrou
// no historico num ponto seguro (`aplicada`), foi a um modelo que respondeu
// (`vista`), ou chegou tarde e vai no proximo turno (`proximo_turno`).
export const MensagemNoTurnoEventSchema = z.object({
  type: z.literal('mensagem_no_turno'),
  seq: z.number(),
  id_cliente: z.string().default(''),
  fase: z.enum(['aplicada', 'vista', 'proximo_turno']),
});

// Um Sentury.md, CLAUDE.md ou AGENTS.md passou a valer na conversa
// (harness/instrucoes_do_projeto.py).
export const InstrucoesDoProjetoEventSchema = z.object({
  type: z.literal('instrucoes_do_projeto'),
  arquivos: z.array(z.string()),
});

export const DoneEventSchema = z.object({
  type: z.literal('done'),
  result: HarnessDoneResultSchema,
});

export const ErrorEventSchema = z.object({
  type: z.literal('error'),
  detail: z.string(),
});

// O servidor parou o turno a pedido (o atalho do computer use). Terminal,
// como done e error: a tela trata como o botao de parar.
export const ParadoEventSchema = z.object({
  type: z.literal('parado'),
});

export const SseEventSchema = z.discriminatedUnion('type', [
  StageEventSchema,
  PlanUpdateEventSchema,
  ToolStartEventSchema,
  ToolCompleteEventSchema,
  ReasoningEventSchema,
  CompactedEventSchema,
  ClarificationEventSchema,
  PermissaoEventSchema,
  NavegadorEventSchema,
  ComputadorEventSchema,
  MensagemNoTurnoEventSchema,
  InstrucoesDoProjetoEventSchema,
  DiffEventSchema,
  SaidaEventSchema,
  SaidaParcialEventSchema,
  TokenEventSchema,
  DoneEventSchema,
  ErrorEventSchema,
  ParadoEventSchema,
]);

export type SseEvent = z.infer<typeof SseEventSchema>;
export type StageEvent = z.infer<typeof StageEventSchema>;
export type ActionIntent = z.infer<typeof ActionIntentSchema>;
export type PlanEntry = z.infer<typeof PlanEntrySchema>;
export type PlanUpdateEvent = z.infer<typeof PlanUpdateEventSchema>;
export type ToolStartEvent = z.infer<typeof ToolStartEventSchema>;
export type ToolCompleteEvent = z.infer<typeof ToolCompleteEventSchema>;
export type ReasoningEvent = z.infer<typeof ReasoningEventSchema>;
export type CompactedEvent = z.infer<typeof CompactedEventSchema>;
export type ClarificationEvent = z.infer<typeof ClarificationEventSchema>;
export type PermissaoEvent = z.infer<typeof PermissaoEventSchema>;
export type PermissaoPayload = z.infer<typeof PermissaoSchema>;
export type TokenEvent = z.infer<typeof TokenEventSchema>;
export type NavegadorEvent = z.infer<typeof NavegadorEventSchema>;
export type ComputadorEvent = z.infer<typeof ComputadorEventSchema>;
export type MensagemNoTurnoEvent = z.infer<typeof MensagemNoTurnoEventSchema>;
export type DiffDoArquivo = z.infer<typeof DiffDoArquivoSchema>;
export type DiffEvent = z.infer<typeof DiffEventSchema>;
export type SaidaDoTerminal = z.infer<typeof SaidaDoTerminalSchema>;
export type SaidaEvent = z.infer<typeof SaidaEventSchema>;
export type SaidaParcialEvent = z.infer<typeof SaidaParcialEventSchema>;
export type InstrucoesDoProjetoEvent = z.infer<typeof InstrucoesDoProjetoEventSchema>;
export type DoneEvent = z.infer<typeof DoneEventSchema>;
export type ErrorEvent = z.infer<typeof ErrorEventSchema>;
