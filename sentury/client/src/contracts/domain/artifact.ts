export type ArtifactType = 'table' | 'chart' | 'code' | 'markdown' | 'file' | 'workflow' | 'trilha';

export interface BaseArtifact {
  id: string;
  type: ArtifactType;
  title: string;
  sessionId: string;
  createdAt: string;
}

export interface TableArtifact extends BaseArtifact {
  type: 'table';
  columns: { key: string; label: string; type?: 'string' | 'number' | 'severity' }[];
  rows: Record<string, any>[];
}

export interface ChartArtifact extends BaseArtifact {
  type: 'chart';
  chartType: 'bar' | 'line' | 'pie';
  labels: string[];
  datasets: { label: string; data: number[]; color?: string }[];
}

export interface CodeArtifact extends BaseArtifact {
  type: 'code';
  language: string;
  code: string;
}

export interface MarkdownArtifact extends BaseArtifact {
  type: 'markdown';
  content: string;
}

export interface FileArtifact extends BaseArtifact {
  type: 'file';
  formato: string;
  attachment: unknown;
}

/**
 * O que atravessa o turno, no painel da direita.
 *
 * O desenho aprovado separa por papel: na conversa fica o que você precisa ler
 * ou decidir AGORA; no painel fica o que **sobrevive ao turno**. Estava tudo no
 * meio do chat, que é o lugar do primeiro e não do segundo, e por isso pesava.
 *
 * São dois, e a diferença é a mesma que separa `@plano` de `@workflow` no
 * badge: a **trilha** é o caminho DESTE turno (o que rodou, em que ordem, o que
 * falhou); o **workflow** é o checklist que fica em disco e volta na semana que
 * vem. Um morre com a resposta, o outro não.
 */
export interface WorkflowArtifact extends BaseArtifact {
  type: 'workflow';
  plano: import('./session').PlanoPayload;
}

export interface TrilhaArtifact extends BaseArtifact {
  type: 'trilha';
  passos: import('./session').CommandRun[];
}

export type Artifact =
  | TableArtifact | ChartArtifact | CodeArtifact | MarkdownArtifact | FileArtifact
  | WorkflowArtifact | TrilhaArtifact;
