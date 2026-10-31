import { create } from 'zustand';
import { z } from 'zod';
import { SessionMetadata, SessionRuntimeStatus, Workspace } from '../contracts/domain/session';
import { adotarIdentidadeDaMaquina, authHeaders, getRuntimeConfig } from '../runtime/config';
import { apiClient } from '../transport/http-client';

const SessionListSchema = z.object({
  sessions: z.array(z.object({
    session_id: z.string(),
    title: z.string().optional(),
    created_at: z.union([z.number(), z.string()]).optional(),
    updated_at: z.union([z.number(), z.string()]).optional(),
    estado_do_turno: z.string().nullable().optional(),
  }).passthrough()),
});

// Como o último turno de cada conversa terminou, dito pelo servidor: o que
// espera a pessoa aparece na lista sem ela abrir conversa por conversa.
const DO_TURNO: Record<string, SessionRuntimeStatus> = {
  trabalhando: 'working',
  aguardando_aprovacao: 'awaiting_approval',
  aguardando_resposta: 'awaiting_user',
  interrompido: 'interrupted',
  falhou: 'error',
};

const INBOX_ID = 'inbox';

type SessionPreferences = Record<string, { pinned?: boolean; pasta?: string }>;

interface PastaSalva {
  id: string;
  nome: string;
  recolhida?: boolean;
}

interface PrefsInterface {
  pastas: PastaSalva[];
  sessoes: SessionPreferences;
  raizRecolhida?: boolean;
}

// Pastas, fixados e recolhidos vem do servidor: no `localStorage` sumiriam a
// cada troca de origem (porta, host, ou o `tauri://` de um app empacotado).
let prefsEmMemoria: PrefsInterface = { pastas: [], sessoes: {} };

function lerPastas(): PastaSalva[] {
  return prefsEmMemoria.pastas;
}

function readSessionPreferences(): SessionPreferences {
  return prefsEmMemoria.sessoes;
}

async function buscarPrefs(userId: string): Promise<PrefsInterface> {
  try {
    const bruto = await apiClient.get<PrefsInterface>(
      `/sentury/interface/preferencias?user_id=${encodeURIComponent(userId)}`,
      { headers: authHeaders() },
    );
    const cru = bruto as PrefsInterface & { raiz_recolhida?: boolean };
    prefsEmMemoria = {
      pastas: Array.isArray(cru?.pastas) ? cru.pastas.filter(p => p && p.id) : [],
      sessoes: (cru?.sessoes && typeof cru.sessoes === 'object') ? cru.sessoes : {},
      raizRecolhida: Boolean(cru?.raiz_recolhida),
    };
  } catch {
    // Servidor fora do ar: segue com o que estava em memoria.
  }
  return prefsEmMemoria;
}

function guardarPrefs(proximo: PrefsInterface): void {
  prefsEmMemoria = proximo;
  const { userId } = getRuntimeConfig();
  // Grava sem segurar a tela: falha de rede nao desfaz o que ja mudou aqui.
  void apiClient.put('/sentury/interface/preferencias', {
    user_id: userId,
    pastas: proximo.pastas,
    sessoes: proximo.sessoes,
    raiz_recolhida: Boolean(proximo.raizRecolhida),
  }, { headers: authHeaders() }).catch(() => undefined);
}

function salvarPastas(valor: PastaSalva[]): void {
  guardarPrefs({ ...prefsEmMemoria, pastas: valor });
}

function saveSessionPreferences(value: SessionPreferences): void {
  guardarPrefs({ ...prefsEmMemoria, sessoes: value });
}

function asIso(value: number | string | undefined): string {
  if (typeof value === 'number') return new Date(value * 1000).toISOString();
  if (typeof value === 'string' && value) {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.valueOf())) return parsed.toISOString();
  }
  return new Date(0).toISOString();
}

function workspaceFor(sessions: SessionMetadata[]): Workspace {
  return {
    id: INBOX_ID,
    name: 'Conversas',
    sessionCount: sessions.length,
    lastActivityAt: sessions[0]?.updatedAt || new Date(0).toISOString(),
    recolhida: Boolean(prefsEmMemoria.raizRecolhida),
  } as Workspace;
}

function montarWorkspaces(sessions: SessionMetadata[], pastas: PastaSalva[]): Workspace[] {
  const soltas = sessions.filter(item => item.workspaceId === INBOX_ID);
  return [
    workspaceFor(soltas),
    ...pastas.map(pasta => {
      const dentro = sessions.filter(item => item.workspaceId === pasta.id);
      return {
        id: pasta.id,
        name: pasta.nome,
        sessionCount: dentro.length,
        lastActivityAt: dentro[0]?.updatedAt || new Date(0).toISOString(),
        recolhida: Boolean(pasta.recolhida),
      } as Workspace;
    }),
  ];
}

interface SessionState {
  workspaces: Workspace[];
  sessions: SessionMetadata[];
  activeSessionId: string | null;
  activeWorkspaceId: string;
  isLoading: boolean;
  loadError: string | null;
  setActiveSession: (id: string) => void;
  setActiveWorkspace: (id: string) => void;
  createSession: (workspaceId?: string, title?: string) => SessionMetadata;
  updateSessionStatus: (sessionId: string, status: SessionRuntimeStatus) => void;
  renameSession: (sessionId: string, title: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  toggleSessionPinned: (sessionId: string) => void;
  createFolder: (nome: string) => void;
  renameFolder: (id: string, nome: string) => void;
  deleteFolder: (id: string) => void;
  toggleFolder: (id: string) => void;
  moveSessionToFolder: (sessionId: string, folderId: string) => void;
  loadSessions: () => Promise<void>;
}

export const useSessionStore = create<SessionState>((set, get) => ({
  workspaces: [workspaceFor([])],
  sessions: [],
  activeSessionId: null,
  activeWorkspaceId: INBOX_ID,
  isLoading: false,
  loadError: null,

  setActiveSession: (id) => {
    const session = get().sessions.find(item => item.id === id);
    if (session) set({ activeSessionId: id, activeWorkspaceId: session.workspaceId });
  },

  setActiveWorkspace: (id) => set({ activeWorkspaceId: id }),

  createFolder: (nome) => {
    const limpo = nome.trim();
    if (!limpo) return;
    const pastas = [...lerPastas(), { id: `pasta-${Date.now().toString(36)}`, nome: limpo }];
    salvarPastas(pastas);
    set(state => ({ workspaces: montarWorkspaces(state.sessions, pastas) }));
  },

  renameFolder: (id, nome) => {
    const limpo = nome.trim();
    if (!limpo) return;
    const pastas = lerPastas().map(pasta => (pasta.id === id ? { ...pasta, nome: limpo } : pasta));
    salvarPastas(pastas);
    set(state => ({ workspaces: montarWorkspaces(state.sessions, pastas) }));
  },

  deleteFolder: (id) => {
    const pastas = lerPastas().filter(pasta => pasta.id !== id);
    salvarPastas(pastas);
    // A pasta some, as conversas nao: voltam para a raiz.
    const prefs = readSessionPreferences();
    Object.keys(prefs).forEach(chave => {
      if (prefs[chave]?.pasta === id) prefs[chave] = { ...prefs[chave], pasta: undefined };
    });
    saveSessionPreferences(prefs);
    set(state => {
      const sessions = state.sessions.map(item => (item.workspaceId === id ? { ...item, workspaceId: INBOX_ID } : item));
      return { sessions, workspaces: montarWorkspaces(sessions, pastas) };
    });
  },

  toggleFolder: (id) => {
    // A raiz recolhe como qualquer pasta, so que o estado dela nao esta na
    // lista de pastas — ela nao e uma.
    if (id === INBOX_ID) {
      guardarPrefs({ ...prefsEmMemoria, raizRecolhida: !prefsEmMemoria.raizRecolhida });
      set(state => ({ workspaces: montarWorkspaces(state.sessions, lerPastas()) }));
      return;
    }
    const pastas = lerPastas().map(pasta => (pasta.id === id ? { ...pasta, recolhida: !pasta.recolhida } : pasta));
    salvarPastas(pastas);
    set(state => ({ workspaces: montarWorkspaces(state.sessions, pastas) }));
  },

  moveSessionToFolder: (sessionId, folderId) => {
    const prefs = readSessionPreferences();
    prefs[sessionId] = { ...prefs[sessionId], pasta: folderId === INBOX_ID ? undefined : folderId };
    saveSessionPreferences(prefs);
    set(state => {
      const sessions = state.sessions.map(item => (item.id === sessionId ? { ...item, workspaceId: folderId } : item));
      return { sessions, workspaces: montarWorkspaces(sessions, lerPastas()) };
    });
  },

  createSession: (workspaceId = INBOX_ID, title = 'Nova conversa') => {
    const now = new Date().toISOString();
    const session: SessionMetadata = {
      id: `sess-${crypto.randomUUID()}`,
      workspaceId,
      title,
      createdAt: now,
      updatedAt: now,
      runtimeStatus: 'idle',
      tokensUsed: 0,
      tags: [],
      pinned: false,
      archived: false,
    };
    set(state => {
      const sessions = [session, ...state.sessions];
      return { sessions, activeSessionId: session.id, workspaces: montarWorkspaces(sessions, lerPastas()) };
    });
    return session;
  },

  updateSessionStatus: (sessionId, runtimeStatus) => {
    set(state => ({
      sessions: state.sessions.map(session => session.id === sessionId
        ? { ...session, runtimeStatus, updatedAt: new Date().toISOString() }
        : session),
    }));
  },

  renameSession: async (sessionId, title) => {
    const normalized = title.trim().slice(0, 120);
    if (!normalized) return;
    set(state => ({ sessions: state.sessions.map(session => session.id === sessionId ? { ...session, title: normalized } : session) }));
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    try {
      await apiClient.post(
        `/sentury/sessions/${encodeURIComponent(sessionId)}/title`,
        { user_id: config.userId, title: normalized },
        { headers: authHeaders() },
      );
    } catch {
      // Sessões novas só passam a existir no servidor após a primeira mensagem.
    }
  },

  deleteSession: async (sessionId) => {
    const restantes = get().sessions.filter(session => session.id !== sessionId);
    set(state => ({
      sessions: restantes,
      // Apagar a conversa aberta nao pode deixar o canvas apontando pro vazio.
      activeSessionId: state.activeSessionId === sessionId ? (restantes[0]?.id ?? null) : state.activeSessionId,
    }));
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    try {
      await apiClient.delete(
        `/sentury/sessions/${encodeURIComponent(sessionId)}?user_id=${encodeURIComponent(config.userId)}`,
        { headers: authHeaders() },
      );
    } catch {
      // Sessao que nunca chegou ao servidor some so daqui mesmo.
    }
  },

  toggleSessionPinned: (sessionId) => {
    set(state => {
      const sessions = state.sessions.map(session => session.id === sessionId ? { ...session, pinned: !session.pinned } : session);
      const pinned = sessions.find(session => session.id === sessionId)?.pinned;
      const preferences = readSessionPreferences();
      preferences[sessionId] = { ...preferences[sessionId], pinned };
      saveSessionPreferences(preferences);
      return { sessions };
    });
  },

  loadSessions: async () => {
    apiClient.setBaseUrl(getRuntimeConfig().apiUrl);
    set({ isLoading: true, loadError: null });
    try {
      // Identidade vem da maquina: em outra porta a lista abriria vazia.
      const userId = await adotarIdentidadeDaMaquina();
      const [raw, preferences] = await Promise.all([
        apiClient.get<unknown>(
          `/sentury/sessions?user_id=${encodeURIComponent(userId)}&limit=100`,
          { headers: authHeaders() },
        ),
        buscarPrefs(userId).then(prefs => prefs.sessoes),
      ]);
      const data = SessionListSchema.parse(raw);
      const remote = data.sessions.map((session): SessionMetadata => ({
        id: session.session_id,
        workspaceId: preferences[session.session_id]?.pasta || INBOX_ID,
        title: session.title || 'Nova conversa',
        createdAt: asIso(session.created_at),
        updatedAt: asIso(session.updated_at),
        runtimeStatus: DO_TURNO[session.estado_do_turno || ''] || 'finished',
        tokensUsed: 0,
        tags: [],
        pinned: Boolean(preferences[session.session_id]?.pinned),
        archived: false,
      }));
      const localDrafts = get().sessions.filter(session =>
        session.runtimeStatus === 'idle' && !remote.some(item => item.id === session.id)
      );
      const sessions = [...localDrafts, ...remote];
      const current = get().activeSessionId;
      let nextSessionId = current && sessions.some(item => item.id === current) ? current : null;
      
      if (!nextSessionId) {
        const now = new Date().toISOString();
        const novaSessao: SessionMetadata = {
          id: `sess-${crypto.randomUUID()}`,
          workspaceId: INBOX_ID,
          title: 'Nova conversa',
          createdAt: now,
          updatedAt: now,
          runtimeStatus: 'idle',
          tokensUsed: 0,
          tags: [],
          pinned: false,
          archived: false,
        };
        sessions.unshift(novaSessao);
        nextSessionId = novaSessao.id;
      }

      set({
        sessions,
        workspaces: montarWorkspaces(sessions, lerPastas()),
        activeSessionId: nextSessionId,
        isLoading: false,
      });
    } catch (error) {
      set({
        isLoading: false,
        loadError: error instanceof Error ? error.message : String(error),
      });
    }
  },
}));
