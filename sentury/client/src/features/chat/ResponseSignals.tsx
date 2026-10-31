import React from 'react';
import { CheckCircle2, CircleAlert, Compass, LoaderCircle, Lightbulb, Users, Wrench } from 'lucide-react';
import { ResponseSignals as ResponseSignalsPayload } from '../../contracts/domain/session';
import { useChatStore } from '../../stores/chat-store';
import { AvisoDeAprendizado } from './AvisoDeAprendizado';
import { IconeDaFuncao } from './IconeDaFuncao';

const subagentLabels: Record<string, string> = {
  evidence_analyst: 'auditoria de evidência',
  operations_critic: 'crítica operacional',
  action_specialist: 'priorização de ações',
};

export const ResponseSignals: React.FC<{ sessionId: string; signals: ResponseSignalsPayload }> = ({
  sessionId,
  signals,
}) => {
  const sendMessage = useChatStore(state => state.sendMessage);
  const subagents = signals.subagents?.results || [];
  const hasCouncil = Boolean(signals.council && (
    Object.keys(signals.council.perspectives).length || signals.council.consensus
  ));

  return (
    <div className="mt-4 space-y-3">
      {signals.skillActivated && signals.skillActivated.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <Wrench className="h-3.5 w-3.5 text-gold-ink" />
          <span>via {signals.skillActivated.length > 1 ? 'skills' : 'skill'} <strong className="font-semibold text-zinc-700">{signals.skillActivated.join(', ')}</strong></span>
        </div>
      )}
      {signals.funcoesCitadas && signals.funcoesCitadas.length > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-zinc-500">
          <span>via</span>
          {signals.funcoesCitadas.map((rotulo, indice) => (
            <React.Fragment key={rotulo}>
              {indice > 0 ? <span>e</span> : null}
              <strong className="inline-flex items-center gap-1 font-semibold text-zinc-700"><IconeDaFuncao id={rotulo} className="h-3 w-3" />@{rotulo}</strong>
            </React.Fragment>
          ))}
        </div>
      )}

      {subagents.length > 0 && (
        <details className="max-w-3xl rounded-xl border border-stone-200 bg-[#fffdf8]/70 px-4 py-3">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-semibold text-zinc-800">
            <Users className="h-4 w-4 text-gold-ink" />
            Trabalho em paralelo
            <span className="ml-auto text-[10px] font-normal text-zinc-400">{subagents.length} {subagents.length === 1 ? 'subagente' : 'subagentes'}</span>
          </summary>
          <div className="mt-3 divide-y divide-stone-200">
            {subagents.map((result, index) => {
              const concluido = result.status === 'completed';
              const falhou = result.status === 'error' || result.status === 'failed';
              return (
                <div key={`${result.role}-${index}`} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
                  {concluido
                    ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-label="concluído" />
                    : falhou
                      ? <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-red-500" aria-label="falhou" />
                      : <LoaderCircle className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-gold-hover" aria-label="trabalhando" />}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong className="text-xs font-semibold text-zinc-800">{subagentLabels[result.role] || result.role}</strong>
                      <span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${concluido ? 'bg-emerald-50 text-emerald-700' : falhou ? 'bg-red-50 text-red-700' : 'bg-gold-soft text-gold-ink'}`}>
                        {concluido ? 'concluído' : falhou ? 'falhou' : 'trabalhando'}
                      </span>
                    </div>
                    {result.summary ? <p className="mt-1 text-xs leading-5 text-zinc-600">{result.summary}</p> : null}
                  </div>
                </div>
              );
            })}
          </div>
        </details>
      )}

      <AvisoDeAprendizado itens={signals.aprendizados?.length ? signals.aprendizados
        : signals.learned ? [{ tipo: 'memoria' as const, texto: signals.learned }] : []} />

      {signals.proactiveInsight && (
        <div className="max-w-2xl border-l-2 border-gold py-1 pl-4">
          <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.13em] text-gold-ink">
            <Lightbulb className="h-3.5 w-3.5" />
            Observei algo além do pedido
          </div>
          <p className="mt-2 text-sm leading-6 text-zinc-700">{signals.proactiveInsight.text}</p>
          {signals.proactiveInsight.action && (
            <button
              type="button"
              onClick={() => void sendMessage(sessionId, signals.proactiveInsight!.action!)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-gold transition-colors hover:bg-zinc-800"
            >
              {signals.proactiveInsight.action} →
            </button>
          )}
        </div>
      )}

      {hasCouncil && signals.council && (
        <details className="max-w-3xl rounded-xl border border-stone-200 bg-[#fffdf8]/70 px-4 py-3">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-semibold text-zinc-800">
            <Users className="h-4 w-4 text-gold-ink" />
            Conselho de especialistas
            <span className="ml-auto text-[10px] font-normal text-zinc-400">{Object.keys(signals.council.perspectives).length} perspectivas</span>
          </summary>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {Object.entries(signals.council.perspectives).map(([role, text]) => (
              <div key={role} className="border-t border-stone-200 pt-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-zinc-500">{role}</p>
                <p className="mt-1 text-xs leading-5 text-zinc-700">{text}</p>
              </div>
            ))}
          </div>
          {signals.council.tradeOffs.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-zinc-500">Trade-offs</p>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-zinc-700">
                {signals.council.tradeOffs.map(item => <li key={item}>{item}</li>)}
              </ul>
            </div>
          )}
          {signals.council.consensus && (
            <div className="mt-4 border-l-2 border-emerald-500 pl-3 text-sm leading-6 text-zinc-800">
              {signals.council.consensus}
            </div>
          )}
        </details>
      )}

      {signals.deliberation && signals.deliberation.steps.length > 0 && (
        <details className="max-w-3xl border-t border-stone-200 pt-3 text-xs text-zinc-600">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold text-zinc-700">
            <Compass className="h-3.5 w-3.5 text-gold-ink" />
            Como cheguei aqui
            <span className="font-normal text-zinc-400">{signals.deliberation.steps.length} {signals.deliberation.steps.length === 1 ? 'passo' : 'passos'}</span>
          </summary>
          <div className="mt-3 space-y-3 pl-5">
            {signals.deliberation.objective && <p><strong>Objetivo:</strong> {signals.deliberation.objective}</p>}
            <ol className="list-decimal space-y-1 pl-4">
              {signals.deliberation.steps.map((step, index) => <li key={index}>{step.observation || step.tool}</li>)}
            </ol>
            {signals.deliberation.stopReason && <p className="flex items-center gap-1 text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />{signals.deliberation.stopReason}</p>}
          </div>
        </details>
      )}

      {signals.planQuestion && (
        <div className="flex items-start gap-2 text-sm leading-6 text-zinc-700">
          <Compass className="mt-1 h-3.5 w-3.5 shrink-0 text-gold-ink" />
          <span>{signals.planQuestion}</span>
        </div>
      )}
    </div>
  );
};
