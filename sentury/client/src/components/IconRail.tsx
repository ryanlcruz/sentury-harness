import React, { useState } from 'react';
import {
  MessageSquare,
  CheckSquare,
  Sparkles,
  Cpu,
  ShieldCheck,
  Settings,
  HelpCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Activity,
  Building2,
  ChevronDown,
  Dna,
} from 'lucide-react';
import { DomainId } from '../app/navigation';
import { useWorkbenchStore } from '../stores/workbench-store';
import { coresDoAgente, useHQ } from '../features/residentes/useEsperando';
import { Coruja } from '../features/residentes/Coruja';
import { estadoDaCoruja, NOME_DO_ESTADO } from '../features/residentes/api';

interface IconRailProps {
  activeDomain: DomainId;
  openDomain: DomainId | null;
  onSelectDomain: (domain: DomainId) => void;
  /** Leva direto a uma feature. O aviso precisa apontar o LUGAR. */
  onIrPara?: (feature: string) => void;
  onOpenSettings?: () => void;
  onOpenHelp?: () => void;
  onOpenHarness?: () => void;
  harnessAtivo?: boolean;
  /** Com nome, abre a página daquele residente. */
  onOpenHQ?: (residente?: string) => void;
  hqAtivo?: boolean;
  onOpenMutation?: () => void;
  mutacaoAtivo?: boolean;
  isExpanded: boolean;
  onToggleExpanded: () => void;
}

export const IconRail: React.FC<IconRailProps> = ({
  activeDomain,
  openDomain,
  onSelectDomain,
  onIrPara,
  onOpenSettings,
  onOpenHelp,
  onOpenHarness,
  harnessAtivo,
  onOpenHQ,
  hqAtivo,
  onOpenMutation,
  mutacaoAtivo,
  isExpanded,
  onToggleExpanded,
}) => {
  const unseenArtifacts = useWorkbenchStore(state => state.unseenArtifactIds.length);
  const hq = useHQ();
  const esperandoNaHQ = hq.esperando.length;
  // A bandeja dos residentes lembra se ficou recolhida; sem armazenamento, começa aberta.
  const [bandejaAberta, setBandejaAberta] = useState(() => {
    try { return localStorage.getItem('sentury.hq.bandeja') !== 'fechada'; } catch { return true; }
  });
  const alternarBandeja = () => setBandejaAberta(aberta => {
    try { localStorage.setItem('sentury.hq.bandeja', aberta ? 'fechada' : 'aberta'); } catch { /* segue sem lembrar */ }
    return !aberta;
  });
  const items: Array<{ id: DomainId; label: string; icon: React.ComponentType<{ className?: string }> }> = [
    { id: 'chat', label: 'Conversas', icon: MessageSquare },
    { id: 'work', label: 'Trabalho', icon: CheckSquare },
    { id: 'knowledge', label: 'Conhecimento', icon: Sparkles },
    { id: 'runtime', label: 'Runtime', icon: Cpu },
    { id: 'observability', label: 'Observabilidade', icon: Activity },
  ];

  return (
    <aside className={`${isExpanded ? 'w-56' : 'w-14'} z-40 flex shrink-0 select-none flex-col border-r border-zinc-800 bg-[#1f1e1b] py-3 text-zinc-100 transition-[width] duration-200`}>
      <div className={`mb-6 flex h-9 items-center ${isExpanded ? 'justify-between px-2.5' : 'justify-center'}`}>
        <button
          type="button"
          onClick={onToggleExpanded}
          className={`flex h-9 items-center rounded-xl transition-colors hover:bg-zinc-800 ${isExpanded ? 'min-w-0 gap-2 px-1.5' : 'w-9 justify-center'}`}
          title={isExpanded ? 'Recolher navegação' : 'Expandir navegação'}
          aria-expanded={isExpanded}
        >
          {isExpanded
            ? <PanelLeftClose className="h-4.5 w-4.5 shrink-0 text-zinc-300" />
            : <img src="/sentury-icone.png" alt="Sentury" className="h-9 w-9 object-contain" />}
          {isExpanded && <span className="truncate text-xs font-semibold">Sentury</span>}
        </button>
        {isExpanded && <PanelLeftOpen className="h-4 w-4 text-zinc-600" aria-hidden="true" />}
      </div>

      {/* Nav Items */}
      <nav className="flex w-full flex-col items-center gap-2 px-2">
        {items.map(item => {
          const Icon = item.icon;
          // HQ e Mutação têm botão próprio: só ele acende, não o domínio onde moram.
          const isActive = activeDomain === item.id && !hqAtivo && !mutacaoAtivo;
          const isOpen = openDomain === item.id;

          return (
            <button
              key={item.id}
              // Com artefato novo, o clique vai para Artefatos. O aviso ficava
              // no dominio certo e abria em Tarefas, que e a primeira feature —
              // a pessoa tinha de PROCURAR para achar o que tinha chegado.
              onClick={() => (item.id === 'work' && unseenArtifacts > 0 && onIrPara)
                ? onIrPara('artifacts')
                : onSelectDomain(item.id)}
              aria-expanded={isOpen}
              aria-label={item.id === 'work' && unseenArtifacts > 0
                ? `${unseenArtifacts} ${unseenArtifacts === 1 ? 'artefato novo' : 'artefatos novos'} — abrir Artefatos`
                : item.label}
              className={`${isExpanded ? 'w-full justify-start gap-3 px-3' : 'w-10 justify-center'} flex h-10 items-center rounded-xl transition-all ${
                isActive
                  ? 'text-gold bg-zinc-800/90 shadow-2xs border border-gold/30'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
              }`}
              title={item.label}
            >
              <span className="relative shrink-0">
                <Icon className="h-5 w-5" />
                {item.id === 'work' && unseenArtifacts > 0 && (
                  <span
                    className="absolute -right-2.5 -top-2.5 flex min-w-4 items-center justify-center rounded-full border border-[#1f1e1b] bg-gold px-1 text-[9px] font-bold leading-[14px] text-zinc-950"
                    aria-hidden="true"
                  >
                    {unseenArtifacts > 99 ? '99+' : unseenArtifacts}
                  </span>
                )}
              </span>
              {isExpanded && <span className="text-xs font-medium">{item.label}</span>}
            </button>
          );
        })}

        {/* A casa dos residentes. O selo conta quem espera a pessoa. */}
        <div className={`${isExpanded ? 'w-full' : ''} flex items-center`}>
        <button
          onClick={() => onOpenHQ?.()}
          aria-label={esperandoNaHQ ? `Sentury HQ: ${esperandoNaHQ} esperando você` : 'Sentury HQ'}
          className={`${isExpanded ? 'w-full justify-start gap-3 px-3' : 'w-10 justify-center'} flex h-10 items-center rounded-xl transition-all ${
            hqAtivo
              ? 'text-gold bg-zinc-800/90 shadow-2xs border border-gold/30'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
          }`}
          title="Sentury HQ"
        >
          <span className="relative shrink-0">
            <Building2 className="h-5 w-5" />
            {esperandoNaHQ > 0 && (
              <span
                className="absolute -right-2.5 -top-2.5 flex min-w-4 items-center justify-center rounded-full border border-[#1f1e1b] bg-gold px-1 text-[9px] font-bold leading-[14px] text-zinc-950"
                aria-hidden="true"
              >
                {esperandoNaHQ > 99 ? '99+' : esperandoNaHQ}
              </span>
            )}
          </span>
          {isExpanded && <span className="text-xs font-medium">Sentury HQ</span>}
        </button>
        {isExpanded && hq.agentes.length > 0 && (
          <button type="button" onClick={() => alternarBandeja()} aria-expanded={bandejaAberta}
            aria-label={bandejaAberta ? 'Recolher a lista de residentes' : 'Mostrar a lista de residentes'}
            className="ml-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-zinc-800/50 hover:text-zinc-200">
            <ChevronDown className={`h-4 w-4 transition-transform ${bandejaAberta ? '' : '-rotate-90'}`} />
          </button>
        )}
        </div>
        {/* Expandida, a sidebar mostra quem mora na HQ e em que estado; a bandeja recolhe. */}
        {isExpanded && bandejaAberta && hq.agentes.length > 0 && (
          <div className="flex w-full flex-col gap-0.5 pl-3">
            {hq.agentes.slice(0, 6).map(agente => {
              const estado = estadoDaCoruja(agente, hq.esperando);
              return (
                <button key={agente.nome} type="button" onClick={() => onOpenHQ?.(agente.nome)}
                  className="flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left text-zinc-300 transition hover:bg-zinc-800/60">
                  <span className="flex h-7 w-7 shrink-0 items-end justify-center overflow-hidden rounded-md bg-[#f7f3e8] leading-none">
                    <Coruja cores={coresDoAgente(agente)} acessorios={agente.aparencia.acessorios} estado={estado} tamanho={26} rotulo={agente.nome} />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium capitalize">{agente.nome}</span>
                    <span className={`block text-[10px] ${estado === 'esperando' ? 'text-gold' : 'text-zinc-500'}`}>{NOME_DO_ESTADO[estado]}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {/* Separador */}
        <div className={`${isExpanded ? 'w-[calc(100%-16px)]' : 'w-6'} my-1 h-px bg-zinc-800`} />

        {/* O Harness como sistema. O diagnostico de um turno e do botao de
            depuracao, ao lado da conversa: os dois abriam o mesmo painel. */}
        <button
          onClick={onOpenHarness}
          className={`${isExpanded ? 'w-full justify-start gap-3 px-3' : 'w-10 justify-center'} flex h-10 items-center rounded-xl transition-all ${
            harnessAtivo
              ? 'text-emerald-400 bg-emerald-950/40 border border-emerald-500/40'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
          }`}
          title="Harness: o que o agente pode fazer"
        >
          <ShieldCheck className="w-5 h-5" />
          {isExpanded && <span className="text-xs font-medium">Harness</span>}
        </button>

        {/* Onde o Sentury muda a si mesmo: proposta, medição e decisão. */}
        <button
          onClick={onOpenMutation}
          className={`${isExpanded ? 'w-full justify-start gap-3 px-3' : 'w-10 justify-center'} flex h-10 items-center rounded-xl transition-all ${
            mutacaoAtivo
              ? 'text-violet-300 bg-violet-950/40 border border-violet-500/40'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
          }`}
          title="Mutação: o Sentury melhorando a si mesmo"
        >
          <Dna className="w-5 h-5" />
          {isExpanded && <span className="text-xs font-medium">Mutação</span>}
        </button>
      </nav>

      {/* Bottom Actions */}
      <div className="mt-auto flex w-full flex-col items-center gap-2 px-2">
        <button
          onClick={onOpenHelp}
          className={`${isExpanded ? 'w-full justify-start gap-3 px-3' : 'w-10 justify-center'} flex h-10 items-center rounded-xl text-zinc-400 transition-all hover:bg-zinc-800/50 hover:text-zinc-200`}
          title="Biblioteca & Ajuda"
        >
          <HelpCircle className="w-5 h-5" />
          {isExpanded && <span className="text-xs font-medium">Biblioteca e ajuda</span>}
        </button>
        <button
          onClick={onOpenSettings}
          className={`${isExpanded ? 'w-full justify-start gap-3 px-3' : 'w-10 justify-center'} flex h-10 items-center rounded-xl text-zinc-400 transition-all hover:bg-zinc-800/50 hover:text-zinc-200`}
          title="Configurações"
        >
          <Settings className="w-5 h-5" />
          {isExpanded && <span className="text-xs font-medium">Configurações</span>}
        </button>
      </div>
    </aside>
  );
};
