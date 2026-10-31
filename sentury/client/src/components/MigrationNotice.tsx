import React from 'react';
import { Construction } from 'lucide-react';
import { FeatureId } from '../app/navigation';

const labels: Partial<Record<FeatureId, string>> = {
  tasks: 'Tarefas',
  schedules: 'Agendamentos',
  artifacts: 'Artefatos',
  context: 'Context Engine',
  memory: 'Memória',
  skills: 'Skills',
  robinbandit: 'RobinBandit',
  mcp: 'MCP',
};

export const MigrationNotice: React.FC<{ featureId: FeatureId }> = ({ featureId }) => (
  <section className="flex h-full items-center justify-center px-8">
    <div className="max-w-md text-center">
      <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-stone-200/80 text-zinc-600">
        <Construction className="h-5 w-5" />
      </div>
      <h1 className="mt-4 text-lg font-semibold text-zinc-900">{labels[featureId] || featureId}</h1>
      <p className="mt-2 text-sm leading-6 text-zinc-500">
        Esta área continua disponível no frontend atual e ainda não foi conectada ao novo client. Ela será migrada sem remover suas funções existentes.
      </p>
    </div>
  </section>
);

