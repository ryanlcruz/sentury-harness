import { create } from 'zustand';
import { Artifact } from '../contracts/domain/artifact';

interface WorkbenchState {
  isOpen: boolean;
  artifacts: Artifact[];
  /**
   * Abas abertas separadas dos artefatos: fechar uma aba não apaga a entrega.
   */
  abertas: string[];
  activeArtifactId: string | null;
  unseenArtifactIds: string[];
  autoOpenConsumed: boolean;

  openWorkbench: (artifactId?: string) => void;
  closeWorkbench: () => void;
  toggleWorkbench: () => void;
  addArtifact: (artifact: Artifact) => void;
  /** Tira da tela do painel. O artefato CONTINUA na biblioteca. */
  fecharAba: (id: string) => void;
  /** Descarta de vez. Só por pedido explícito — o painel não é dono. */
  descartarArtifact: (id: string) => void;
  setActiveArtifact: (id: string) => void;
  markArtifactsSeen: () => void;
}

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  isOpen: false,
  artifacts: [],
  abertas: [],
  activeArtifactId: null,
  unseenArtifactIds: [],
  autoOpenConsumed: false,

  openWorkbench: (artifactId?: string) =>
    set(state => {
      const activeArtifactId = artifactId ?? state.activeArtifactId ?? state.artifacts[0]?.id ?? null;
      return {
        isOpen: true,
        // Abrir da biblioteca reabre a aba que foi fechada.
        abertas: activeArtifactId && !state.abertas.includes(activeArtifactId)
          ? [...state.abertas, activeArtifactId] : state.abertas,
        activeArtifactId,
        autoOpenConsumed: true,
        unseenArtifactIds: activeArtifactId
          ? state.unseenArtifactIds.filter(id => id !== activeArtifactId)
          : state.unseenArtifactIds,
      };
    }),

  closeWorkbench: () => set({ isOpen: false, autoOpenConsumed: true }),

  // Fechar a ultima aba fecha o painel: um workbench vazio nao mostra nada.
  // Mas o artefato FICA — ele volta pela biblioteca de Artefatos.
  fecharAba: (id: string) =>
    set(state => {
      const abertas = state.abertas.filter(item => item !== id);
      const ativo = state.activeArtifactId === id
        ? abertas[abertas.length - 1] ?? null
        : state.activeArtifactId;
      return {
        abertas,
        activeArtifactId: ativo,
        unseenArtifactIds: state.unseenArtifactIds.filter(artifactId => artifactId !== id),
        isOpen: abertas.length > 0,
      };
    }),

  descartarArtifact: (id: string) =>
    set(state => {
      const restantes = state.artifacts.filter(item => item.id !== id);
      const abertas = state.abertas.filter(item => item !== id);
      return {
        artifacts: restantes,
        abertas,
        activeArtifactId: state.activeArtifactId === id
          ? abertas[abertas.length - 1] ?? null
          : state.activeArtifactId,
        unseenArtifactIds: state.unseenArtifactIds.filter(artifactId => artifactId !== id),
        isOpen: abertas.length > 0,
      };
    }),

  toggleWorkbench: () => set(state => {
    if (state.isOpen) return { isOpen: false, autoOpenConsumed: true };
    const activeArtifactId = state.activeArtifactId ?? state.artifacts[0]?.id ?? null;
    return {
      isOpen: true,
      activeArtifactId,
      autoOpenConsumed: true,
      unseenArtifactIds: activeArtifactId
        ? state.unseenArtifactIds.filter(id => id !== activeArtifactId)
        : state.unseenArtifactIds,
    };
  }),

  addArtifact: (artifact: Artifact) =>
    set(state => {
      const exists = state.artifacts.some(a => a.id === artifact.id);
      const newArtifacts = exists
        ? state.artifacts.map(a => (a.id === artifact.id ? artifact : a))
        : [...state.artifacts, artifact];
      // O painel se apresenta uma vez, no primeiro artefato. Depois que o
      // usuario o fecha, novos turnos apenas avisam pela barra lateral.
      const shouldAutoOpen = !exists && !state.autoOpenConsumed;

      return {
        artifacts: newArtifacts,
        abertas: state.abertas.includes(artifact.id)
          ? state.abertas : [...state.abertas, artifact.id],
        activeArtifactId: state.activeArtifactId ?? artifact.id,
        unseenArtifactIds: exists
          ? state.unseenArtifactIds
          : [...state.unseenArtifactIds, artifact.id],
        isOpen: state.isOpen || shouldAutoOpen,
        autoOpenConsumed: state.autoOpenConsumed || shouldAutoOpen,
      };
    }),

  setActiveArtifact: (id: string) => set(state => ({
    activeArtifactId: id,
    isOpen: true,
    autoOpenConsumed: true,
    unseenArtifactIds: state.unseenArtifactIds.filter(artifactId => artifactId !== id),
  })),

  markArtifactsSeen: () => set({ unseenArtifactIds: [] }),
}));
