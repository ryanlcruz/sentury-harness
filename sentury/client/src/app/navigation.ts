export type DomainId = 'chat' | 'work' | 'knowledge' | 'runtime' | 'observability';

export type FeatureId =
  | 'help'
  | 'hq'
  | 'conversations'
  | 'tasks'
  | 'schedules'
  | 'artifacts'
  | 'context'
  | 'memory'
  | 'skills'
  | 'domains'
  | 'providers'
  | 'robinbandit'
  | 'mcp'
  | 'traces'
  | 'usage'
  | 'evals'
  | 'diagnostics'
  | 'harness'
  | 'mutation';

export interface NavigationFeature {
  id: FeatureId;
  label: string;
  description: string;
  available: boolean;
}

export interface NavigationDomain {
  id: DomainId;
  label: string;
  eyebrow: string;
  features: NavigationFeature[];
}

export const navigationDomains: NavigationDomain[] = [
  {
    id: 'chat',
    label: 'Conversas',
    eyebrow: 'Chat',
    features: [
      { id: 'conversations', label: 'Conversas', description: 'Sessões e histórico', available: true },
    ],
  },
  {
    id: 'work',
    label: 'Trabalho',
    eyebrow: 'Work',
    features: [
      { id: 'tasks', label: 'Tarefas', description: 'Planos de ação e aprovações', available: true },
      { id: 'schedules', label: 'Agendamentos', description: 'Rotinas e execuções recorrentes', available: true },
      { id: 'artifacts', label: 'Artefatos', description: 'Relatórios, tabelas e arquivos', available: true },
    ],
  },
  {
    id: 'knowledge',
    label: 'Conhecimento',
    eyebrow: 'Knowledge',
    features: [
      { id: 'context', label: 'Context Engine', description: 'Identidade, contrato e playbooks', available: true },
      { id: 'memory', label: 'Memória', description: 'O que o Sentury lembra de você', available: true },
      { id: 'skills', label: 'Skills', description: 'Capacidades operacionais', available: true },
      { id: 'domains', label: 'Setores', description: 'Setor ativo, métricas e vocabulário', available: true },
    ],
  },
  {
    id: 'runtime',
    label: 'Runtime',
    eyebrow: 'Runtime',
    features: [
      { id: 'providers', label: 'Provedores', description: 'Disponibilidade, modelos e custo', available: true },
      { id: 'robinbandit', label: 'RobinBandit', description: 'Roteamento, tiers e prioridades', available: false },
      { id: 'mcp', label: 'Tools e MCP', description: 'Catálogo real e integrações externas', available: true },
    ],
  },
  {
    id: 'observability',
    label: 'Observabilidade',
    eyebrow: 'Qualidade e operação',
    features: [
      { id: 'traces', label: 'Traces', description: 'Linha do tempo de turnos e ferramentas', available: true },
      { id: 'usage', label: 'Uso e créditos', description: 'Chamadas, latência, créditos e limites', available: true },
      { id: 'evals', label: 'Evals', description: 'Casos, critérios, resultados e regressões', available: true },
      { id: 'diagnostics', label: 'Diagnósticos', description: 'Saúde do runtime e investigação', available: true },
    ],
  },
];

export function domainById(id: DomainId): NavigationDomain {
  return navigationDomains.find(domain => domain.id === id) || navigationDomains[0];
}
