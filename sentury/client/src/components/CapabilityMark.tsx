import React from 'react';
import { ArrowRightLeft, Code2, Database, Diamond, Globe, Hexagon, ListChecks, Move, Network, Search, ShieldCheck, Trash2 } from 'lucide-react';

/* Cor e ícone identificam a capacidade; o estado é comunicado separadamente. */

export type Capability = 'core' | 'planner' | 'researcher' | 'builder' | 'reviewer' | 'memory' | 'router' | 'mutation' | 'workflow';

interface Marca {
  rotulo: string;
  Icon: typeof Search;
  /** Cor de assinatura: aplicada ao ícone e a fundos discretos, nunca ao texto todo. */
  texto: string;
  fundo: string;
  borda: string;
}

// Os ícones preservam a identidade visual de cada capacidade.
export const CAPABILITIES: Record<Capability, Marca> = {
  core: { rotulo: 'Sentury', Icon: Diamond, texto: 'text-gold-ink', fundo: 'bg-gold-soft', borda: 'border-gold' },
  planner: { rotulo: 'Planner', Icon: Network, texto: 'text-sky-700', fundo: 'bg-sky-50', borda: 'border-sky-200' },
  researcher: { rotulo: 'Researcher', Icon: Search, texto: 'text-emerald-700', fundo: 'bg-emerald-50', borda: 'border-emerald-200' },
  builder: { rotulo: 'Builder', Icon: Code2, texto: 'text-orange-700', fundo: 'bg-orange-50', borda: 'border-orange-200' },
  reviewer: { rotulo: 'Reviewer', Icon: ShieldCheck, texto: 'text-violet-700', fundo: 'bg-violet-50', borda: 'border-violet-200' },
  memory: { rotulo: 'Memory', Icon: Database, texto: 'text-cyan-700', fundo: 'bg-cyan-50', borda: 'border-cyan-200' },
  router: { rotulo: 'Router', Icon: Move, texto: 'text-red-700', fundo: 'bg-red-50', borda: 'border-red-200' },
  // Magenta é a cor de assinatura declarada na arte do Mutation ("SIGNATURE //
  // Neon Magenta"), não uma escolha aproximada. Vale para tudo que envolve
  // mutação, e é o que separa uma alteração do agente de qualquer outra coisa
  // acontecendo na tela.
  mutation: { rotulo: 'Mutation', Icon: Hexagon, texto: 'text-pink-600', fundo: 'bg-pink-50', borda: 'border-pink-200' },
  // Indigo porque sobrou distinguivel: mais fundo que o sky do Planner e mais
  // azul que o violet do Reviewer, e o workflow vive perto dos dois na tela.
  // O icone e checklist porque o plano E um checklist em Markdown — nao uma
  // metafora de fluxo que o arquivo nao tem.
  workflow: { rotulo: 'Workflow', Icon: ListChecks, texto: 'text-indigo-700', fundo: 'bg-indigo-50', borda: 'border-indigo-200' },
};

/** `kind` do backend (vocabulário fechado) para a capacidade correspondente. */
export function capabilityOfKind(kind?: string | null): Capability {
  switch ((kind || '').toLowerCase()) {
    case 'search': return 'researcher';
    case 'fetch': return 'researcher';
    case 'execute': return 'builder';
    case 'edit': return 'builder';
    case 'delete': return 'builder';
    case 'move': return 'builder';
    case 'read': return 'planner';
    default: return 'core';
  }
}

/* A capacidade diz QUEM opera, e é ela que dá a cor. Mas apagar, mover e ir
   na internet são o mesmo Builder ou o mesmo Researcher de editar e de buscar
   aqui dentro — e são as três coisas que o usuário mais precisa reconhecer de
   relance, porque são as que ele talvez quisesse ter interrompido.

   Então o ícone deixa de ser sempre o da capacidade e passa a dizer o que foi
   feito, nos casos em que o "o quê" pesa mais que o "quem". Nos outros, o
   ícone da capacidade continua valendo — sem exceção inventada. */
const ICONE_DO_KIND: Record<string, typeof Search> = {
  delete: Trash2,
  move: ArrowRightLeft,
  fetch: Globe,
};

/** O par cor + ícone de um passo. Cor da capacidade, ícone do que aconteceu. */
export function markOfKind(kind?: string | null, texto = ''): Marca {
  const k = (kind || '').toLowerCase();
  const capacidade = kind ? capabilityOfKind(k) : capabilityOfText(texto);
  const marca = CAPABILITIES[capacidade];
  const proprio = ICONE_DO_KIND[k];
  return proprio ? { ...marca, Icon: proprio } : marca;
}

/** Última linha de defesa quando só existe o texto do passo. */
export function capabilityOfText(texto: string): Capability {
  const t = (texto || '').toLocaleLowerCase('pt-BR');
  if (/busc|pesquis|consult|investig|procur|lendo|web/.test(t)) return 'researcher';
  if (/execut|gerando|gerar|export|construin|montan|salvan|criando|edit/.test(t)) return 'builder';
  if (/revis|valid|critic|conferin|checa/.test(t)) return 'reviewer';
  if (/memor|context|lembr|recuper|hist/.test(t)) return 'memory';
  if (/rotea|provedor|modelo|fallback|escolh.*rota/.test(t)) return 'router';
  if (/plan|estrutur|decomp|organiz|prepar/.test(t)) return 'planner';
  return 'core';
}

interface CapabilityIconProps {
  capability: Capability;
  className?: string;
}

export const CapabilityIcon: React.FC<CapabilityIconProps> = ({ capability, className = 'h-3.5 w-3.5' }) => {
  const marca = CAPABILITIES[capability];
  return <marca.Icon className={`${className} ${marca.texto}`} aria-hidden />;
};

interface CapabilityBadgeProps {
  capability: Capability;
  /** Texto próprio quando a etapa diz mais que o nome da capacidade. */
  label?: string;
  title?: string;
}

export const CapabilityBadge: React.FC<CapabilityBadgeProps> = ({ capability, label, title }) => {
  const marca = CAPABILITIES[capability];
  return (
    <span
      title={title || marca.rotulo}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${marca.borda} ${marca.fundo} ${marca.texto}`}
    >
      <marca.Icon className="h-2.5 w-2.5" aria-hidden />
      {label || marca.rotulo}
    </span>
  );
};
