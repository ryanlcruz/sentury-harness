import { create } from 'zustand';
import { HarnessState } from '../contracts/domain/harness';

interface HarnessStoreState extends HarnessState {
  isDrawerOpen: boolean;
  activeTab: 'operations' | 'diagnostics';
  // De qual conversa e o turno mostrado. Sem isto o painel continuava exibindo
  // o turno da conversa anterior depois de trocar de sessao.
  sessionId: string | null;
  seguirSessao: (id: string | null) => void;

  setDrawerOpen: (open: boolean) => void;
  toggleDrawer: () => void;
  setActiveTab: (tab: 'operations' | 'diagnostics') => void;
  updateHarnessState: (partial: Partial<HarnessState>) => void;
}

export const useHarnessStore = create<HarnessStoreState>((set) => ({
  status: 'offline',
  model: undefined,
  rawState: null,
  compacted: false,
  compaction: null,
  proposed_tool: undefined,
  harness_allowed: undefined,
  harness_reason: undefined,
  events: [],
  telemetry: undefined,
  isDrawerOpen: false,
  activeTab: 'operations',
  sessionId: null,

  setDrawerOpen: (open: boolean) => set({ isDrawerOpen: open }),
  toggleDrawer: () => set(state => ({ isDrawerOpen: !state.isDrawerOpen })),
  setActiveTab: (tab: 'operations' | 'diagnostics') => set({ activeTab: tab }),
  seguirSessao: (id: string | null) => set(state => (state.sessionId === id ? state : {
    ...state,
    sessionId: id,
    // A conexão com a API não é da conversa: trocar de conversa não a derruba.
    // Só o "executando" era do turno da conversa anterior.
    status: state.status === 'busy' ? 'online' : state.status,
    model: undefined,
    rawState: null,
    compacted: false,
    compaction: null,
    proposed_tool: undefined,
    harness_allowed: undefined,
    harness_reason: undefined,
    events: [],
    telemetry: undefined,
  })),
  updateHarnessState: (partial: Partial<HarnessState>) => set(state => ({ ...state, ...partial })),
}));
