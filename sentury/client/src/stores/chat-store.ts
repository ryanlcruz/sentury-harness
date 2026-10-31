import { create } from 'zustand';
import { z } from 'zod';
import { ChatMessage, ClarificationPayload, CommandRun, ExecutionStage, ImagemAnexada, PlanoPayload } from '../contracts/domain/session';
import { PermissaoPayload, PlanEntry } from '../contracts/events/session-events';
import { authHeaders, getRuntimeConfig } from '../runtime/config';
import { funcoesCitadas, funcoesDoEnvio } from '../runtime/funcoes-nativas';
import { StreamClient } from '../transport/stream-client';
import { apiClient } from '../transport/http-client';
import { useHarnessStore } from './harness-store';
import { useSessionStore } from './session-store';
import { useWorkbenchStore } from './workbench-store';
import { CartaoNavegador, aplicarEventoNavegador, paraGuardar } from '../features/chat/navegador';
import { CartaoComputador, aplicarEventoComputador, paraGuardarComputador } from '../features/chat/computador';
import { FaseOrientacao, ItemDaFila, avancar, pendente } from '../features/chat/orientacao';

interface SessionStream {
  text: string;
  /** Ultimo fragmento SSE, animado sem refazer o texto inteiro. */
  lastToken: string;
  stages: ExecutionStage[];
  reasoning: string;
  plan: PlanEntry[];
  clarification: ClarificationPayload | null;
  permissao: PermissaoPayload | null;
  /** Qual bloco pediu. Ver harness/bloco.py. */
  permissaoId: string | null;
  /** O cartao do navegador ao vivo, quando o turno usa o navegador. */
  navegador: CartaoNavegador | null;
  /** O cartao do computer use ao vivo (so ao vivo: os passos ficam no processo). */
  computador: CartaoComputador | null;
  running: boolean;
  controller: AbortController | null;
  /** Parar pedido: null nao; '' parando; nome = esperando essa ferramenta acabar. */
  parando: string | null;
  /** "Parar e enviar": sai quando o turno terminar de parar. */
  enviarAoParar: ItemDaFila | null;
  /** A conexao caiu e a tela esta tentando voltar. Ver transport/stream-client.ts. */
  reconectando: { tentativa: number; total: number } | null;
}

const EMPTY_STREAM: SessionStream = {
  text: '',
  lastToken: '',
  stages: [],
  reasoning: '',
  plan: [],
  clarification: null,
  permissao: null,
  permissaoId: null,
  navegador: null,
  computador: null,
  running: false,
  controller: null,
  parando: null,
  enviarAoParar: null,
  reconectando: null,
};

const SessionDetailSchema = z.object({
  state: z.object({
    history: z.array(z.object({
      role: z.enum(['user', 'assistant', 'system']),
      content: z.string(),
      attachment: z.unknown().nullable().optional(),
      attachments: z.array(z.unknown()).nullable().optional(),
      imagens_enviadas: z.array(z.string()).optional(),
      processo: z.array(z.object({
        id: z.string().nullable().optional(),
        titulo: z.string().nullable().optional(),
        kind: z.string().nullable().optional(),
        comando: z.string().nullable().optional(),
        status: z.string().default('ok'),
        duracao_ms: z.number().nullable().optional(),
      }).passthrough()).optional(),
      attachment_validation: z.object({
        status: z.string().optional(),
        preview_available: z.boolean().optional(),
        downloadable_artifact: z.boolean().optional(),
        errors: z.array(z.string()).optional(),
        warnings: z.array(z.string()).optional(),
      }).passthrough().nullable().optional(),
    }).passthrough()).default([]),
    filtros: z.record(z.string(), z.unknown()).default({}),
  }).passthrough(),
});

// O cartao recolhe bem antes disso; o teto segura um build barulhento.
const MAX_LINHAS_AO_VIVO = 400;

interface ChatState {
  transcripts: Record<string, ChatMessage[]>;
  streams: Record<string, SessionStream>;
  scopes: Record<string, Record<string, unknown>>;
  /** Mensagens na fila: saem sozinhas quando o turno termina bem. */
  filas: Record<string, ItemDaFila[]>;
  filaFor: (sessionId: string | null) => ItemDaFila[];
  /** Com o turno rodando, manda para ele (ponto seguro); sem turno, envia. */
  orientar: (sessionId: string, texto: string) => Promise<void>;
  enfileirar: (sessionId: string, item: Omit<ItemDaFila, 'id'>) => void;
  removerDaFila: (sessionId: string, id: string) => void;
  enviarProximoDaFila: (sessionId: string) => void;
  marcarOrientacao: (sessionId: string, idCliente: string, fase: FaseOrientacao) => void;
  /** Tira da conversa a orientacao que nao entrou no turno e poe na fila.
   * Sem `idCliente`, todas as pendentes (o turno acabou). */
  devolverParaFila: (sessionId: string, idCliente?: string) => void;
  sendMessage: (
    sessionId: string, content: string, imagens?: ImagemAnexada[], funcoes?: string[],
    arquivos?: ImagemAnexada[], opcoes?: { retomar?: boolean; regenerate?: boolean },
  ) => Promise<void>;
  /** O Parar cooperativo: pede ao servidor e espera o `parado`. Clicar de
   * novo, ou o servidor nao responder, corta a conexao como antes. */
  abortStreaming: (sessionId: string) => void;
  pararEEnviar: (sessionId: string, item: Omit<ItemDaFila, 'id'>) => void;
  /** Fecha o turno parado na tela: o que rodou fica, o que estava no meio
   * fica cancelado, a orientacao pendente vai para a fila. */
  encerrarInterrompido: (sessionId: string) => void;
  loadSession: (sessionId: string) => Promise<void>;
  messagesFor: (sessionId: string | null) => ChatMessage[];
  streamFor: (sessionId: string | null) => SessionStream;
  appendLocalMessages: (sessionId: string, messages: Array<{ role: 'user' | 'assistant'; content: string }>) => void;
  clearSession: (sessionId: string) => void;
  dispensarInterativo: (sessionId: string, messageId: string, qual: 'clarification' | 'permissao') => void;
  retryLastMessage: (sessionId: string) => Promise<void>;
}

/** O marco na conversa quando um Sentury.md, CLAUDE.md ou AGENTS.md passa a valer. */
function textoDasInstrucoes(arquivo: string): string {
  return `Seguindo as instruções do projeto em ${arquivo}`;
}

function clock(): string {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function mesaDaMensagem(bruto: unknown): ChatMessage['mesa'] {
  if (!bruto || typeof bruto !== 'object') return undefined;
  const { id, titulo, resumo } = bruto as { id?: unknown; titulo?: unknown; resumo?: unknown };
  return typeof id === 'string' && typeof titulo === 'string' ? { id, titulo, resumo: resumo === true || undefined } : undefined;
}

export const useChatStore = create<ChatState>((set, get) => ({
  transcripts: {},
  streams: {},
  scopes: {},
  filas: {},

  filaFor: (sessionId) => sessionId ? get().filas[sessionId] || [] : [],

  orientar: async (sessionId, texto) => {
    if (!get().streams[sessionId]?.running) {
      await get().sendMessage(sessionId, texto);
      return;
    }
    const idCliente = crypto.randomUUID();
    const mensagem: ChatMessage = {
      id: `msg-orientar-${idCliente}`,
      sessionId,
      role: 'user',
      content: texto,
      timestamp: clock(),
      status: 'complete',
      orientacao: { idCliente, fase: 'enviando' },
    };
    set(state => ({ transcripts: { ...state.transcripts, [sessionId]: [...(state.transcripts[sessionId] || []), mensagem] } }));
    const config = getRuntimeConfig();
    let status = 0;
    try {
      const res = await fetch(`${config.apiUrl}/chat/orientar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ session_id: sessionId, texto, id_cliente: idCliente }),
      });
      status = res.status;
    } catch {
      status = 0;
    }
    if (status === 202) {
      get().marcarOrientacao(sessionId, idCliente, 'recebida');
      return;
    }
    // 409: o turno acabou enquanto ela ia. Ou a rede falhou. Nos dois casos
    // vira fila, e sai ja se nada estiver rodando.
    get().devolverParaFila(sessionId, idCliente);
    get().enviarProximoDaFila(sessionId);
  },

  pararEEnviar: (sessionId, item) => {
    const stream = get().streams[sessionId];
    if (!stream?.running) {
      void get().sendMessage(sessionId, item.texto, item.imagens, item.funcoes, item.arquivos);
      return;
    }
    set(state => ({ streams: { ...state.streams, [sessionId]: { ...stream, enviarAoParar: { ...item, id: crypto.randomUUID() } } } }));
    get().abortStreaming(sessionId);
  },

  enfileirar: (sessionId, item) => set(state => ({
    filas: { ...state.filas, [sessionId]: [...(state.filas[sessionId] || []), { ...item, id: crypto.randomUUID() }] },
  })),

  removerDaFila: (sessionId, id) => set(state => ({
    filas: { ...state.filas, [sessionId]: (state.filas[sessionId] || []).filter(item => item.id !== id) },
  })),

  enviarProximoDaFila: (sessionId) => {
    const [proximo, ...resto] = get().filas[sessionId] || [];
    if (!proximo || get().streams[sessionId]?.running) return;
    set(state => ({ filas: { ...state.filas, [sessionId]: resto } }));
    void get().sendMessage(sessionId, proximo.texto, proximo.imagens, proximo.funcoes, proximo.arquivos);
  },

  marcarOrientacao: (sessionId, idCliente, fase) => set(state => ({
    transcripts: {
      ...state.transcripts,
      [sessionId]: (state.transcripts[sessionId] || []).map(msg => msg.orientacao?.idCliente === idCliente
        ? { ...msg, orientacao: { idCliente, fase: avancar(msg.orientacao.fase, fase) } }
        : msg),
    },
  })),

  devolverParaFila: (sessionId, idCliente) => {
    const transcript = get().transcripts[sessionId] || [];
    const voltam = transcript.filter(msg => msg.orientacao && (idCliente
      ? msg.orientacao.idCliente === idCliente
      : pendente(msg.orientacao.fase)));
    if (!voltam.length) return;
    set(state => ({
      transcripts: { ...state.transcripts, [sessionId]: transcript.filter(msg => !voltam.includes(msg)) },
      filas: {
        ...state.filas,
        [sessionId]: [...voltam.map(msg => ({ id: msg.id, texto: msg.content })), ...(state.filas[sessionId] || [])],
      },
    }));
  },

  messagesFor: (sessionId) => sessionId ? get().transcripts[sessionId] || [] : [],
  streamFor: (sessionId) => sessionId ? get().streams[sessionId] || EMPTY_STREAM : EMPTY_STREAM,

  retryLastMessage: async (sessionId) => {
    const transcript = get().transcripts[sessionId] || [];
    let lastUserIndex = -1;
    for (let index = transcript.length - 1; index >= 0; index -= 1) {
      if (transcript[index].role === 'user') { lastUserIndex = index; break; }
    }
    if (lastUserIndex < 0 || get().streams[sessionId]?.running) return;
    const content = transcript[lastUserIndex].content;
    set(state => ({ transcripts: { ...state.transcripts, [sessionId]: transcript.slice(0, lastUserIndex) } }));
    await get().sendMessage(sessionId, content, [], funcoesDoEnvio(sessionId, content), [], { regenerate: true });
  },

  loadSession: async (sessionId) => {
    if (get().streams[sessionId]?.running) return;
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    try {
      const raw = await apiClient.get<unknown>(
        `/sentury/sessions/${encodeURIComponent(sessionId)}?user_id=${encodeURIComponent(config.userId)}`,
        { headers: authHeaders() },
      );
      const detail = SessionDetailSchema.parse(raw);
      // `system` e andaime interno (resultado bruto de tool, texto de skill).
      // Ao recarregar, isso aparecia na tela como se fosse resposta da Sentury.
      // A orientacao mandada no meio do turno fica no servidor como instrucao
      // de sistema (o planner so le assim); na tela ela e da pessoa.
      const messages = detail.state.history
        .map(message => {
          const orientacao = (message as { orientacao?: unknown }).orientacao;
          const instrucoes = (message as { instrucoes_do_projeto?: unknown }).instrucoes_do_projeto;
          if (typeof instrucoes === 'string' && message.role === 'system') {
            return { ...message, content: textoDasInstrucoes(instrucoes), orientada: false, marco: true };
          }
          return typeof orientacao === 'string' && message.role === 'system'
            ? { ...message, role: 'user' as const, content: orientacao, orientada: true, marco: false }
            : { ...message, orientada: false, marco: false };
        })
        .filter(message => message.role !== 'system' || message.marco)
        .map((message, index): ChatMessage => ({
        id: `${sessionId}-history-${index}`,
        sessionId,
        role: message.role,
        content: message.content,
        orientacao: message.orientada ? { idCliente: '', fase: 'aplicada' } : undefined,
        timestamp: '',
        status: 'complete',
        automatico: (message as { origem?: unknown }).origem === 'goal' || undefined,
        residente: typeof (message as { residente?: unknown }).residente === 'string' ? String((message as { residente?: unknown }).residente) : undefined,
        mencao: typeof (message as { mencao?: unknown }).mencao === 'string' ? String((message as { mencao?: unknown }).mencao) : undefined,
        mencoes: Array.isArray((message as { mencoes?: unknown }).mencoes)
          ? ((message as unknown as { mencoes: unknown[] }).mencoes).filter((nome): nome is string => typeof nome === 'string') : undefined,
        mesa: mesaDaMensagem((message as { mesa?: unknown }).mesa),
        navegador: ((message as { navegador?: CartaoNavegador }).navegador) || undefined,
        computador: ((message as { computador?: CartaoComputador }).computador) || undefined,
        anexos: Array.isArray(message.attachments) ? message.attachments : undefined,
        signals: message.attachment ? {
          attachment: message.attachment,
          attachmentValidation: message.attachment_validation ? {
            status: message.attachment_validation.status,
            previewAvailable: message.attachment_validation.preview_available,
            downloadableArtifact: message.attachment_validation.downloadable_artifact,
            errors: message.attachment_validation.errors,
            warnings: message.attachment_validation.warnings,
          } : undefined,
        } : undefined,
        traces: (message.processo || []).map(passo => ({
          stage: passo.titulo || '',
          durationMs: passo.duracao_ms ?? undefined,
          status: passo.status === 'error' ? ('failed' as const) : ('completed' as const),
        })),
        commands: (message.processo || [])
          .filter(passo => passo.comando || passo.diff || passo.saida)
          .map((passo, i) => ({
            id: passo.id || `${sessionId}-cmd-${index}-${i}`,
            title: passo.titulo || 'Comando',
            tool: typeof passo.ferramenta === 'string' ? passo.ferramenta : undefined,
            kind: passo.kind || undefined,
            command: passo.comando || null,
            diff: (passo.diff as CommandRun['diff']) || undefined,
            saida: (passo.saida as CommandRun['saida']) || undefined,
            status: (passo.status === 'error' || passo.status === 'skipped' || passo.status === 'pending'
              ? passo.status : 'ok') as 'ok' | 'error' | 'skipped' | 'pending',
            durationMs: passo.duracao_ms ?? undefined,
          })),
        imagens: (message.imagens_enviadas || []).length
          ? (message.imagens_enviadas || []).map(nome => ({ nome, dataUrl: '' }))
          : undefined,
      }));
      set(state => ({ transcripts: { ...state.transcripts, [sessionId]: messages }, scopes: { ...state.scopes, [sessionId]: detail.state.filtros } }));
    } catch (error) {
      // A locally-created session has no server record until its first message.
      if (!get().transcripts[sessionId]) {
        set(state => ({ transcripts: { ...state.transcripts, [sessionId]: [] } }));
      }
    }
  },

  sendMessage: async (sessionId, content, imagens = [], funcoes = [], arquivos = [], opcoes = {}) => {
    const existing = get().streams[sessionId];
    if (existing?.running) return;
    // Envio sem funções (a aprovação do cartão, as respostas da folha) leva as
    // liberadas na conversa: sem isto o turno retomado perdia o @computador.
    if (!funcoes.length) funcoes = funcoesDoEnvio(sessionId, content);

    const config = getRuntimeConfig();
    const controller = new AbortController();
    const userMessage: ChatMessage = {
      id: `msg-user-${crypto.randomUUID()}`,
      sessionId,
      role: 'user',
      content,
      timestamp: clock(),
      status: 'complete',
      imagens: imagens.length ? imagens : undefined,
    };

    set(state => ({
      transcripts: {
        ...state.transcripts,
        [sessionId]: opcoes.retomar && (state.transcripts[sessionId] || []).at(-1)?.role === 'user'
          && (state.transcripts[sessionId] || []).at(-1)?.content === content
          ? state.transcripts[sessionId]
          : [...(state.transcripts[sessionId] || []), userMessage],
      },
      streams: {
        ...state.streams,
        [sessionId]: {
          text: '',
          lastToken: '',
          stages: [],
          reasoning: '',
                  plan: [],
                  clarification: null,
          permissao: null,
          permissaoId: null,
          navegador: null,
          computador: null,
          running: true,
          controller,
          parando: null,
          enviarAoParar: null,
          reconectando: null,
        },
      },
    }));
    useSessionStore.getState().updateSessionStatus(sessionId, 'working');
    useHarnessStore.getState().updateHarnessState({ status: 'busy' });

    const streamClient = new StreamClient();
    await streamClient.streamChat(
      config.apiUrl,
      {
        message: content,
        session_id: sessionId,
        user_id: config.userId,
        mode: config.mode,
        effort: config.effort,
        imagens: imagens.map(item => ({ nome: item.nome, data_url: item.dataUrl })),
        arquivos: arquivos.map(item => ({ nome: item.nome, data_url: item.dataUrl })),
        funcoes,
        regenerate: Boolean(opcoes.retomar || opcoes.regenerate),
      },
      {
        onStage: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            return {
              streams: {
                ...state.streams,
                [sessionId]: {
                  ...stream,
                  stages: [...stream.stages, { stage: event.text, status: 'completed' }],
                },
              },
            };
          });
        },
        onPlanUpdate: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            return { streams: { ...state.streams, [sessionId]: { ...stream, plan: event.entries } } };
          });
        },
        onToolStart: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            const exists = stream.plan.some(entry => entry.id === event.id);
            // A fala do plan_update nao e sobrescrita por um tool_start sem
            // fala: o passo ja tinha dito a que veio, e apagar seria perder.
            const dados = { title: event.title, tool: event.tool, kind: event.kind, intent: event.intent, command: event.command, status: 'running' as const };
            const plan = exists
              ? stream.plan.map(entry => entry.id === event.id ? { ...entry, ...dados, fala: event.fala ?? entry.fala } : entry)
              : [...stream.plan, { id: event.id, ...dados, fala: event.fala }];
            return { streams: { ...state.streams, [sessionId]: { ...stream, plan } } };
          });
        },
        onToolComplete: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            const atualizado = stream.plan.map(entry => entry.id === event.id
              ? {
                ...entry,
                status: event.status,
                durationMs: event.duration_ms ?? entry.durationMs,
                resumo: event.resumo ?? entry.resumo,
              }
              : entry);
            // Uma falha seguida por uma acao bem-sucedida nao derrubou o
            // turno: foi observada e contornada pelo agente. O bloco anterior
            // precisa contar essa historia em vez de continuar vermelho como
            // se toda a execucao tivesse quebrado.
            const indiceRecuperacao = event.status === 'ok'
              ? atualizado.findIndex(entry => entry.id === event.id)
              : -1;
            const plan = indiceRecuperacao > 0
              ? atualizado.map((entry, index) => (
                index < indiceRecuperacao && entry.status === 'error'
                  ? { ...entry, status: 'handledError' as const }
                  : entry
              ))
              : atualizado;
            return { streams: { ...state.streams, [sessionId]: { ...stream, plan } } };
          });
        },
        // Compatibilidade com servidores antigos: nunca persista nem mostre
        // O think e opcional: chega sempre e a interface decide se mostra,
        // dentro do Processo Analitico. Nunca vira mensagem.
        onReasoning: event => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            const anterior = stream.reasoning;
            const texto = event.text || '';
            const junto = !anterior
              ? texto
              : anterior.includes(texto) ? anterior : `${anterior}\n\n${texto}`;
            return { streams: { ...state.streams, [sessionId]: { ...stream, reasoning: junto } } };
          });
        },
        // O marco de compactação informa uma mudança persistida no contexto.
        onCompacted: (event) => {
          set(state => ({
            transcripts: {
              ...state.transcripts,
              [sessionId]: [
                ...(state.transcripts[sessionId] || []),
                {
                  id: `compact-${Date.now()}`,
                  sessionId,
                  role: 'system' as const,
                  content: `Compactei a conversa para caber no contexto: ${event.mensagens_antes} mensagens viraram ${event.mensagens_depois}.`,
                  timestamp: clock(),
                  status: 'complete' as const,
                },
              ],
            },
          }));
        },
        onPermissao: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            return { streams: { ...state.streams, [sessionId]: { ...stream, permissao: event.permissao, permissaoId: event.id ?? null } } };
          });
          useSessionStore.getState().updateSessionStatus(sessionId, 'awaiting_approval');
        },
        onNavegador: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            return { streams: { ...state.streams, [sessionId]: { ...stream, navegador: aplicarEventoNavegador(stream.navegador, event) } } };
          });
        },
        onComputador: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            return { streams: { ...state.streams, [sessionId]: { ...stream, computador: aplicarEventoComputador(stream.computador, event) } } };
          });
        },
        onReconectando: (tentativa, total) => {
          set(state => {
            const stream = state.streams[sessionId];
            if (stream?.controller !== controller) return {};
            return { streams: { ...state.streams, [sessionId]: { ...stream, reconectando: { tentativa, total } } } };
          });
        },
        onReconectado: () => {
          set(state => {
            const stream = state.streams[sessionId];
            if (stream?.controller !== controller) return {};
            return { streams: { ...state.streams, [sessionId]: { ...stream, reconectando: null } } };
          });
        },
        onPerdido: () => {
          // O histórico persistido recupera um turno encerrado fora da tela.
          if (get().streams[sessionId]?.controller !== controller) return;
          set(state => ({ streams: { ...state.streams, [sessionId]: { ...EMPTY_STREAM } } }));
          get().devolverParaFila(sessionId);
          void get().loadSession(sessionId);
        },
        onDiff: (event) => {
          // O passo que escreveu: o ultimo daquela ferramenta ainda rodando.
          const { type: _t, ferramenta, ...diff } = event;
          set(state => {
            const stream = state.streams[sessionId];
            if (!stream) return {};
            const plan = [...stream.plan];
            for (let i = plan.length - 1; i >= 0; i -= 1) {
              if (plan[i].tool === ferramenta && plan[i].status === 'running') {
                plan[i] = { ...plan[i], diff };
                break;
              }
            }
            return { streams: { ...state.streams, [sessionId]: { ...stream, plan } } };
          });
        },
        onSaidaParcial: (event) => {
          // Linhas chegando enquanto o comando roda. Depois da saida final,
          // um lote atrasado nao entra: a final ja tem tudo.
          set(state => {
            const stream = state.streams[sessionId];
            if (!stream) return {};
            const plan = [...stream.plan];
            for (let i = plan.length - 1; i >= 0; i -= 1) {
              if (plan[i].tool === event.ferramenta && plan[i].status === 'running') {
                const anterior = plan[i].saida;
                if (anterior && !anterior.aoVivo) break;
                const linhas = [...(anterior?.linhas || []), ...event.linhas];
                const excesso = Math.max(0, linhas.length - MAX_LINHAS_AO_VIVO);
                plan[i] = {
                  ...plan[i],
                  saida: {
                    linhas: excesso ? linhas.slice(excesso) : linhas,
                    cortadas: (anterior?.cortadas || 0) + excesso,
                    codigo: null,
                    aoVivo: true,
                  },
                };
                break;
              }
            }
            return { streams: { ...state.streams, [sessionId]: { ...stream, plan } } };
          });
        },
        onSaida: (event) => {
          const { type: _t, ferramenta, ...saida } = event;
          set(state => {
            const stream = state.streams[sessionId];
            if (!stream) return {};
            const plan = [...stream.plan];
            for (let i = plan.length - 1; i >= 0; i -= 1) {
              if (plan[i].tool === ferramenta && plan[i].status === 'running') {
                plan[i] = { ...plan[i], saida: { ...saida, aoVivo: false } };
                break;
              }
            }
            return { streams: { ...state.streams, [sessionId]: { ...stream, plan } } };
          });
        },
        onInstrucoesDoProjeto: (event) => {
          set(state => ({
            transcripts: {
              ...state.transcripts,
              [sessionId]: [
                ...(state.transcripts[sessionId] || []),
                ...event.arquivos.map(arquivo => ({
                  id: `instrucoes-${arquivo}-${Date.now()}`,
                  sessionId,
                  role: 'system' as const,
                  content: textoDasInstrucoes(arquivo),
                  timestamp: clock(),
                  status: 'complete' as const,
                })),
              ],
            },
          }));
        },
        onMensagemNoTurno: (event) => {
          if (event.fase === 'proximo_turno') get().devolverParaFila(sessionId, event.id_cliente);
          else get().marcarOrientacao(sessionId, event.id_cliente, event.fase);
        },
        onClarification: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            return { streams: { ...state.streams, [sessionId]: { ...stream, clarification: event.clarification } } };
          });
          useSessionStore.getState().updateSessionStatus(sessionId, 'awaiting_user');
        },
        onToken: (event) => {
          set(state => {
            const stream = state.streams[sessionId] || EMPTY_STREAM;
            return {
              streams: {
                ...state.streams,
                [sessionId]: { ...stream, text: stream.text + event.text, lastToken: event.text },
              },
            };
          });
        },
        onDone: (event) => {
          const stream = get().streams[sessionId] || EMPTY_STREAM;
          // O parser deixa passar um `done` que divergiu do schema, porque
          // descarta-lo prendia o turno em "Redigindo" com o backend ja
          // respondido. Aqui o preco disso: `result` pode vir incompleto, e o
          // que ja chegou por streaming vira a rede de seguranca.
          const result = (event.result || {}) as typeof event.result;
          const finalContent = result.message || stream.text;
          const assistantMessage: ChatMessage = {
            id: `msg-assistant-${crypto.randomUUID()}`,
            sessionId,
            role: 'assistant',
            content: finalContent,
            timestamp: clock(),
            traces: stream.stages,
            commands: stream.plan.filter(entry => entry.command || entry.diff),
            custo: result.telemetry ? {
              ms: result.telemetry.total_ms,
              modelo: result.telemetry.model,
              // O numero visivel e o de SAIDA. O total era dominado pela
              // entrada — historico reenviado — e assustava sem dizer nada
              // sobre o que este turno produziu.
              tokens: result.telemetry.tokens?.saida,
              tokensEntrada: result.telemetry.tokens?.entrada,
              tokensCacheados: result.telemetry.tokens?.cacheado,
              usd: result.telemetry.custo_usd ?? undefined,
              recusas: result.telemetry.recusas?.map(r => r.modelo || r.provedor),
            } : undefined,
            reasoning: stream.reasoning || undefined,
            status: 'complete',
            anexos: Array.isArray(result.attachments) ? result.attachments : undefined,
            clarification: result.clarification || stream.clarification || undefined,
            permissao: result.permissao || stream.permissao || undefined,
            permissaoId: stream.permissaoId,
            navegador: paraGuardar(stream.navegador),
            computador: paraGuardarComputador(stream.computador),
            // O esquema valida a forma; o card le os campos declarados em
            // `PlanoPayload`. Sao a mesma coisa vinda do mesmo backend.
            plano: (result.plano as PlanoPayload | undefined) || undefined,
            signals: {
              learned: result.learned || undefined,
              aprendizados: result.aprendizados || undefined,
              skillActivated: result.skill_activated || undefined,
              // O que a mensagem citou com `@`; o acesso que já estava ligado não se repete aqui.
              funcoesCitadas: funcoesCitadas(content).map(funcao => funcao.rotulo),
              proactiveInsight: result.proactive_insight || undefined,
              council: result.council ? {
                perspectives: result.council.perspectives,
                tradeOffs: result.council.trade_offs,
                consensus: result.council.consensus_recommendation,
              } : undefined,
              subagents: result.subagents_beta ? {
                requested: result.subagents_beta.requested,
                results: result.subagents_beta.results,
              } : undefined,
              deliberation: result.deliberation ? {
                objective: result.deliberation.objective,
                steps: result.deliberation.steps,
                stopReason: result.deliberation.stop_reason,
              } : undefined,
              planQuestion: result.plan_question || undefined,
              attachment: result.attachment,
              attachmentValidation: result.harness?.artifact_validation ? {
                status: result.harness.artifact_validation.status,
                previewAvailable: result.harness.artifact_validation.preview_available,
                downloadableArtifact: result.harness.artifact_validation.downloadable_artifact,
                errors: result.harness.artifact_validation.errors,
                warnings: result.harness.artifact_validation.warnings,
              } : undefined,
            },
          };
          if (result.harness) {
            useHarnessStore.getState().updateHarnessState({
              status: 'online',
              model: result.telemetry?.provider,
              proposed_tool: result.harness.proposed_tool || undefined,
              harness_allowed: result.harness.harness_allowed ?? undefined,
              harness_reason: result.harness.harness_reason || undefined,
              events: result.harness.events || [],
              telemetry: result.telemetry,
              rawState: result.state,
              compacted: result.compacted,
              compaction: result.compactacao,
            });
          } else {
            useHarnessStore.getState().updateHarnessState({ status: 'online' });
          }
          // O que atravessa o turno vai para o painel da direita; a conversa
          // fica com o que você precisa ler ou decidir agora. Ver o contrato
          // em domain/artifact.ts.
          if (assistantMessage.plano) {
            useWorkbenchStore.getState().addArtifact({
              id: `workflow-${assistantMessage.plano.plano}`,
              type: 'workflow',
              title: assistantMessage.plano.plano,
              sessionId,
              createdAt: new Date().toISOString(),
              plano: assistantMessage.plano,
            });
          }
          // A trilha NAO vai para o painel. Ela e "o que voce le agora" e ja
          // esta na conversa, em bloco; manda-la para la duplicava a mesma
          // coisa e enchia a biblioteca de comando e codigo, que nao e saida
          // reutilizavel. A regua: se nao faz sentido abrir isso de novo daqui
          // a tres dias, nao e artefato.
          set(state => ({
            transcripts: {
              ...state.transcripts,
              [sessionId]: [...(state.transcripts[sessionId] || []), assistantMessage],
            },
            streams: {
              ...state.streams,
              [sessionId]: { ...EMPTY_STREAM },
            },
            scopes: {
              ...state.scopes,
              [sessionId]: result.state && typeof result.state.filtros === 'object' && result.state.filtros && !Array.isArray(result.state.filtros)
                ? result.state.filtros as Record<string, unknown>
                : state.scopes[sessionId] || {},
            },
          }));
          // O turno que parou pedindo aprovação ou com pergunta continua
          // esperando a pessoa: "concluído" tiraria o aviso da lista.
          useSessionStore.getState().updateSessionStatus(sessionId,
            assistantMessage.permissao ? 'awaiting_approval'
              : assistantMessage.clarification ? 'awaiting_user' : 'finished');
          // Terminou bem: a orientacao que nao entrou e a fila seguem, uma por vez.
          get().devolverParaFila(sessionId);
          setTimeout(() => get().enviarProximoDaFila(sessionId), 0);
        },
        onAborted: () => {
          // O `parado` do servidor, ou a conexao cortada. So fecha ESTE
          // turno: com "Parar e enviar", o seguinte ja pode estar rodando.
          if (get().streams[sessionId]?.controller !== controller) return;
          get().encerrarInterrompido(sessionId);
        },
        onError: (event) => {
          const detail = event instanceof Error ? event.message : event.detail;
          const errorMessage: ChatMessage = {
            id: `msg-error-${crypto.randomUUID()}`,
            sessionId,
            role: 'assistant',
            content: `Erro na execução: ${detail}`,
            timestamp: clock(),
            status: 'error',
          };
          set(state => ({
            transcripts: {
              ...state.transcripts,
              [sessionId]: [...(state.transcripts[sessionId] || []), errorMessage],
            },
            streams: { ...state.streams, [sessionId]: { ...EMPTY_STREAM } },
          }));
          useSessionStore.getState().updateSessionStatus(sessionId, 'error');
          useHarnessStore.getState().updateHarnessState({ status: 'error' });
          get().devolverParaFila(sessionId);
        },
      },
      controller.signal,
      authHeaders(),
    );
  },

  abortStreaming: (sessionId) => {
    const stream = get().streams[sessionId];
    if (!stream?.controller) return;
    const controller = stream.controller;
    const cortar = () => {
      if (get().streams[sessionId]?.controller !== controller) return;
      controller.abort();
      get().encerrarInterrompido(sessionId);
    };
    if (stream.parando !== null) {
      cortar(); // segundo clique: parar ja, mesmo no meio
      return;
    }
    set(state => ({ streams: { ...state.streams, [sessionId]: { ...stream, parando: '' } } }));
    const config = getRuntimeConfig();
    void fetch(`${config.apiUrl}/chat/parar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ session_id: sessionId }),
    })
      .then(res => (res.ok ? res.json() : null))
      .catch(() => null)
      .then((resposta: { havia?: boolean; esperando?: string | null } | null) => {
        const atual = get().streams[sessionId];
        if (atual?.controller !== controller) return;
        if (!resposta?.havia) {
          cortar();
          return;
        }
        if (resposta.esperando) {
          set(state => ({ streams: { ...state.streams, [sessionId]: { ...atual, parando: resposta.esperando || '' } } }));
        }
        // O servidor corta sozinho depois de 30 s; isto e a rede de seguranca.
        setTimeout(cortar, 35000);
      });
  },

  encerrarInterrompido: (sessionId) => {
    const stream = get().streams[sessionId];
    if (!stream?.running) return;
    const enviar = stream.enviarAoParar;
    const interruptedMessage: ChatMessage = {
      id: `msg-interrupted-${crypto.randomUUID()}`,
      sessionId,
      role: 'assistant',
      content: stream.text.trim(),
      timestamp: clock(),
      traces: stream.stages,
      // Preserva os passos concluídos e marca como cancelados os interrompidos.
      commands: stream.plan.map(entry => (
        entry.status === 'running' || entry.status === 'pending'
          ? { ...entry, status: 'canceled' as const }
          : entry
      )),
      status: 'interrupted',
    };
    set(state => ({
      transcripts: {
        ...state.transcripts,
        [sessionId]: [...(state.transcripts[sessionId] || []), interruptedMessage],
      },
      streams: { ...state.streams, [sessionId]: { ...EMPTY_STREAM } },
    }));
    useSessionStore.getState().updateSessionStatus(sessionId, 'interrupted');
    useHarnessStore.getState().updateHarnessState({ status: 'online' });
    get().devolverParaFila(sessionId);
    if (enviar) setTimeout(() => void get().sendMessage(sessionId, enviar.texto, enviar.imagens, enviar.funcoes, enviar.arquivos), 0);
  },

  // Transcricao de ligacao: entra no historico local sem passar pelo turno.
  // A dispensa fica no histórico para não reaparecer ao remontar a tela.
  dispensarInterativo: (sessionId, messageId, qual) => {
    set(state => ({
      transcripts: {
        ...state.transcripts,
        [sessionId]: (state.transcripts[sessionId] || []).map(msg =>
          msg.id === messageId ? { ...msg, [qual]: undefined } : msg),
      },
      streams: state.streams[sessionId]
        ? { ...state.streams, [sessionId]: { ...state.streams[sessionId], [qual]: null } }
        : state.streams,
    }));
    // Fechar o cartão tira a conversa do "precisa de você", aqui e no servidor.
    const sessao = useSessionStore.getState().sessions.find(item => item.id === sessionId);
    if (sessao?.runtimeStatus === 'awaiting_approval' || sessao?.runtimeStatus === 'awaiting_user') {
      useSessionStore.getState().updateSessionStatus(sessionId, 'finished');
      void apiClient.post(`/sentury/sessions/${encodeURIComponent(sessionId)}/turno/dispensar`, {},
        { headers: authHeaders() }).catch(() => undefined);
    }
  },

  appendLocalMessages: (sessionId, messages) => set(state => ({
    transcripts: {
      ...state.transcripts,
      [sessionId]: [
        ...(state.transcripts[sessionId] || []),
        ...messages.map((item, index) => ({
          id: `${Date.now()}-voz-${index}`,
          sessionId,
          role: item.role,
          content: item.content,
          timestamp: clock(),
          status: 'complete' as const,
        })),
      ],
    },
  })),

  clearSession: (sessionId) => set(state => ({
    transcripts: { ...state.transcripts, [sessionId]: [] },
    streams: { ...state.streams, [sessionId]: { ...EMPTY_STREAM } },
  })),
}));
