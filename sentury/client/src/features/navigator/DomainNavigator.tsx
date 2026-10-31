import React from 'react';
import { ChevronRight } from 'lucide-react';
import { DomainId, FeatureId, domainById } from '../../app/navigation';
import { useHarnessStore } from '../../stores/harness-store';
import { useWorkbenchStore } from '../../stores/workbench-store';

interface DomainNavigatorProps {
  domainId: DomainId;
  activeFeatureId: FeatureId;
  onSelectFeature: (featureId: FeatureId) => void;
}

export const DomainNavigator: React.FC<DomainNavigatorProps> = ({
  domainId,
  activeFeatureId,
  onSelectFeature,
}) => {
  const domain = domainById(domainId);
  const harnessStatus = useHarnessStore(state => state.status);
  const unseenArtifacts = useWorkbenchStore(state => state.unseenArtifactIds.length);

  return (
    <aside className="z-20 flex w-72 shrink-0 select-none flex-col border-r border-stone-200 bg-[#f2f0e9] text-zinc-700">
      <div className="flex h-16 shrink-0 items-center border-b border-stone-200 px-4">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">{domain.eyebrow}</span>
          <h2 className="mt-0.5 text-sm font-semibold text-zinc-900">{domain.label}</h2>
        </div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label={domain.label}>
        {domain.features.map(feature => {
          const isActive = activeFeatureId === feature.id;
          return (
            <button
              key={feature.id}
              type="button"
              onClick={() => onSelectFeature(feature.id)}
              className={`relative flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left transition-colors ${
                isActive
                  ? 'bg-white shadow-sm before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full before:bg-gold'
                  : 'hover:bg-white/65'
              }`}
            >
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-xs font-semibold text-zinc-800">
                  {feature.label}
                  {feature.id === 'artifacts' && unseenArtifacts > 0 ? (
                    <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-gold px-1.5 text-[9px] font-bold leading-5 text-zinc-950">
                      {unseenArtifacts > 99 ? '99+' : unseenArtifacts}
                    </span>
                  ) : null}
                </span>
                <span className="mt-0.5 block text-[10px] leading-4 text-zinc-500">{feature.description}</span>
              </span>
              {!feature.available && (
                <span className="rounded-full bg-stone-200/80 px-1.5 py-0.5 text-[9px] font-medium text-zinc-500">
                  migrando
                </span>
              )}
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
            </button>
          );
        })}
      </nav>

      <div className="flex items-center justify-between border-t border-stone-200 p-3 text-[11px] text-zinc-500">
        <span>Sentury</span>
        <span className={harnessStatus === 'online' ? 'font-medium text-emerald-700' : harnessStatus === 'busy' ? 'font-medium text-gold-ink' : 'font-medium text-zinc-500'}>
          {harnessStatus === 'online' ? 'Conectado' : harnessStatus === 'busy' ? 'Executando' : 'Offline'}
        </span>
      </div>
    </aside>
  );
};
