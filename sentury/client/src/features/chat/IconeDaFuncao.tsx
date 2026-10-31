import React from 'react';
import { AtSign, Globe, Image, ListChecks, Monitor, Target, Workflow } from 'lucide-react';

const ICONES: Record<string, typeof AtSign> = {
  plano: ListChecks,
  workflow: Workflow,
  goal: Target,
  image: Image,
  computador: Monitor,
  navegador: Globe,
};

/** O ícone de uma função nativa, igual no campo, na mensagem e na faixa de acesso. */
export const IconeDaFuncao: React.FC<{ id: string; className?: string }> = ({ id, className = 'h-3.5 w-3.5' }) => {
  const Icone = ICONES[id] || AtSign;
  return <Icone className={className} aria-hidden="true" />;
};
