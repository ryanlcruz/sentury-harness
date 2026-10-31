import React, { useEffect, useState } from 'react';
import { Check, ChevronDown, ChevronRight, Circle, LoaderCircle, OctagonPause, Play, RotateCcw, TriangleAlert } from 'lucide-react';
import { PlanoPayload, TarefaDoPlano } from '../../contracts/domain/session';
import { CAPABILITIES } from '../../components/CapabilityMark';
import { useChatStore } from '../../stores/chat-store';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

/**
 * O workflow na tela.
 *
 * Ele já existia inteiro em disco — checklist, portão que trava, ciclo de vida,
 * histórico de tentativas — e não aparecia em lugar nenhum: quem não abrisse o
 * `.md` não sabia que havia trabalho em aberto, nem por que ele parou.
 *
 * Mostra a aprovação para começar, os portões de decisão do usuário
 * e as tentativas acumuladas de cada tarefa entre sessões.
 */

const ESTADO: Record<string, { rotulo: string; classe: string }> = {
  ativo: { rotulo: 'ativo', classe: 'bg-emerald-50 text-emerald-700' },
  aberto: { rotulo: 'em andamento', classe: 'bg-indigo-50 text-indigo-700' },
  travado: { rotulo: 'travado', classe: 'bg-amber-50 text-amber-700' },
  fechado: { rotulo: 'concluído', classe: 'bg-emerald-50 text-emerald-700' },
  reaberto: { rotulo: 'reaberto', classe: 'bg-indigo-50 text-indigo-700' },
};

function IconeDoEstado({ estado }: { estado?: string }) {
  if (estado === 'feito') return <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />;
  if (estado === 'fazendo') return <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin text-indigo-500" />;
  if (estado === 'falhou') return <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-red-500" />;
  return <Circle className="h-3 w-3 shrink-0 text-zinc-300" />;
}

function Linha({ t, proxima }: { t: TarefaDoPlano; proxima: boolean }) {
  return (
    <li className={`flex items-start gap-2 rounded px-1 py-0.5 text-xs leading-5 ${proxima ? 'bg-indigo-50/70' : ''}`}>
      <IconeDoEstado estado={t.estado} />
      <span className="shrink-0 tabular-nums text-zinc-400">{t.id}</span>
      <span className={t.feito ? 'text-zinc-400 line-through' : proxima ? 'font-medium text-zinc-800' : 'text-zinc-700'}>
        {t.titulo}
      </span>
      {t.gate ? <span className="shrink-0 rounded bg-amber-100 px-1.5 text-[9px] font-medium text-amber-800">portão</span> : null}
      {t.opcional ? <span className="shrink-0 rounded bg-stone-100 px-1.5 text-[9px] text-zinc-500">opcional</span> : null}
      {t.agenda ? <span className="shrink-0 rounded bg-indigo-50 px-1.5 font-mono text-[9px] text-indigo-700">{t.agenda}</span> : null}
      {/* Tentativa que falhou é evidência: some do Markdown, fica no histórico. */}
      {(t.tentativas || 0) > 1 ? (
        <span className="shrink-0 text-[10px] text-zinc-400" title={`${t.tentativas} tentativas`}>
          {t.tentativas}×
        </span>
      ) : null}
    </li>
  );
}

export const PlanoCard: React.FC<{
  plano: PlanoPayload;
  sessionId: string;
  /**
   * A conversa mostra decisões imediatas; o checklist completo fica no painel.
   */
  compacto?: boolean;
}> = ({ plano, sessionId, compacto = false }) => {
  const tarefas = plano.tarefas || [];
  const feitas = tarefas.filter(t => t.feito).length;
  const total = tarefas.length;
  const workflow = plano.tipo === 'workflow';
  const [workflowAtivo, setWorkflowAtivo] = useState(Boolean(plano.aprovado));
  const [ativando, setAtivando] = useState(false);
  const [erroAtivacao, setErroAtivacao] = useState('');
  // A aprovação do workflow arma o gatilho; a proposta ainda não o ativa.
  const naoComecou = workflow
    ? !workflowAtivo
    : (plano.telemetria?.tentativas || 0) === 0 && feitas === 0;
  const [aberto, setAberto] = useState(naoComecou);
  const sendMessage = useChatStore(state => state.sendMessage);

  const marca = CAPABILITIES.workflow;
  const situacao = ESTADO[workflowAtivo ? 'ativo' : (plano.estado || 'aberto')] || ESTADO.aberto;
  const travado = plano.estado === 'travado' ? plano.travado_por : null;
  const emperradas = plano.telemetria?.emperradas || [];
  const proximaId = travado ? travado.id : plano.proxima?.id;

  useEffect(() => {
    const sincronizar = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string }>).detail;
      if (detail?.id && detail.id === plano.agendamento_id) setWorkflowAtivo(true);
    };
    window.addEventListener('sentury:workflow-active', sincronizar);
    return () => window.removeEventListener('sentury:workflow-active', sincronizar);
  }, [plano.agendamento_id]);

  const aprovar = async () => {
    if (!workflow) {
      await sendMessage(sessionId, `Aprovado. Comece o plano \`${plano.plano}\` pela primeira tarefa.`);
      return;
    }
    if (!plano.agendamento_id) {
      await sendMessage(sessionId, `Aprovo o workflow \`${plano.plano}\`. Comece pela primeira etapa e mantenha o estado para retomarmos depois.`);
      return;
    }
    setAtivando(true); setErroAtivacao('');
    try {
      apiClient.setBaseUrl(getRuntimeConfig().apiUrl);
      await apiClient.post(
        `/sentury/cron/${encodeURIComponent(plano.agendamento_id)}/activate`,
        {},
        { headers: authHeaders() },
      );
      setWorkflowAtivo(true);
      window.dispatchEvent(new CustomEvent('sentury:workflow-active', { detail: { id: plano.agendamento_id } }));
    } catch (reason) {
      setErroAtivacao(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setAtivando(false);
    }
  };

  return (
    <div className={`my-3 overflow-hidden rounded-xl border ${marca.borda} bg-white/90`}>
      <button
        type="button"
        onClick={() => !compacto && setAberto(v => !v)}
        aria-expanded={compacto ? undefined : aberto}
        className={`flex w-full items-center gap-2 ${marca.fundo} px-3 py-2.5 text-left`}
      >
        <marca.Icon className={`h-4 w-4 shrink-0 ${marca.texto}`} aria-hidden />
        {/* A palavra importa: `@plano` e o caminho DESTE turno e morre com a
            resposta; workflow e o que fica em disco e volta na semana que vem.
            Sem o rotulo, os dois pareciam a mesma coisa na tela. */}
        <span className={`shrink-0 text-[10px] font-medium uppercase tracking-wide ${marca.texto} opacity-60`}>
          {workflow ? 'workflow' : 'plano'}
        </span>
        <span className={`truncate text-xs font-semibold ${marca.texto}`}>{plano.plano}</span>
        <span className={`shrink-0 rounded-full px-2 py-px text-[10px] font-medium ${situacao.classe}`}>
          {naoComecou ? 'proposto' : situacao.rotulo}
        </span>
        <span className="ml-auto shrink-0 text-[11px] tabular-nums text-zinc-500">{feitas}/{total}</span>
        {compacto ? null : aberto
          ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
          : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-zinc-400" />}
      </button>

      {/* Barra fina: o número já está ao lado, isto é só a leitura de relance. */}
      {total > 0 && !naoComecou && (
        <div className="h-0.5 w-full bg-stone-100">
          <div className="h-full bg-indigo-400" style={{ width: `${Math.round((feitas / total) * 100)}%` }} />
        </div>
      )}

      {workflow && plano.gatilho ? (
        <p className="border-t border-indigo-100 bg-indigo-50/30 px-3 py-2 font-mono text-[10px] text-indigo-700">
          {plano.gatilho}
        </p>
      ) : null}

      {/* Proposta espera decisão. Montar vinte tarefas e ficar parado, sem
          lugar nenhum para dizer "pode ir", era o que acontecia antes. */}
      {naoComecou && (
        <div className="flex flex-wrap items-center gap-2 border-t border-indigo-100 bg-indigo-50/40 px-3 py-2.5">
          <span className="mr-auto text-[11px] text-zinc-600">
            {workflow
              ? plano.gatilho
                ? `${total} ${total === 1 ? 'passo' : 'passos'}. O agendamento só será armado depois da sua aprovação.`
                : `${total} ${total === 1 ? 'passo' : 'passos'}. O workflow começa depois da sua aprovação.`
              : `${total} ${total === 1 ? 'tarefa' : 'tarefas'}. Começo por onde está marcado?`}
          </span>
          <button
            type="button"
            onClick={() => void aprovar()}
            disabled={ativando}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-indigo-700"
          >
            <Play className="h-3 w-3" /> {workflow
              ? (ativando ? 'Aprovando...' : plano.agendamento_id ? 'Aprovar e agendar' : 'Aprovar e começar')
              : 'Começar'}
          </button>
          <button
            type="button"
            onClick={() => void sendMessage(
              sessionId,
              workflow
                ? `Antes de ativar o workflow \`${plano.plano}\`, quero ajustar o gatilho ou os passos.`
                : `Antes de começar o plano \`${plano.plano}\`, quero ajustar as tarefas.`,
            )}
            className="inline-flex items-center gap-1.5 rounded-lg border border-stone-300 px-2.5 py-1 text-[11px] text-zinc-700 hover:border-zinc-400"
          >
            <RotateCcw className="h-3 w-3" /> Ajustar
          </button>
          {erroAtivacao ? <p className="w-full text-[11px] text-red-700">{erroAtivacao}</p> : null}
        </div>
      )}

      {/* O portão aparece com o card FECHADO também: é a única coisa que exige
          você, e esconder atrás de um clique é fazer o plano parar em silêncio. */}
      {travado && (
        <div className="border-t border-amber-200 bg-amber-50/60 px-3 py-2.5">
          <div className="flex items-start gap-2">
            <OctagonPause className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
            <p className="min-w-0 text-xs font-medium text-amber-900">{travado.titulo}</p>
          </div>
          {travado.opcoes?.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5 pl-6">
              {travado.opcoes.map(opcao => (
                <button
                  key={opcao}
                  type="button"
                  onClick={() => void sendMessage(sessionId, `Sobre o portão ${travado.id} do plano \`${plano.plano}\`: ${opcao}`)}
                  className="rounded-full border border-amber-300 bg-white px-2.5 py-1 text-[11px] text-amber-900 hover:bg-amber-100"
                >
                  {opcao}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      )}

      {emperradas.length > 0 && (
        <div className="border-t border-stone-200 bg-red-50/40 px-3 py-2">
          {emperradas.map(t => (
            <p key={t.id} className="text-[11px] leading-5 text-red-700">
              {t.titulo} — {t.falhas} tentativas sem sair do lugar.
            </p>
          ))}
        </div>
      )}

      {compacto && (
        <p className="border-t border-stone-200 px-3 py-1.5 text-[10px] text-zinc-400">
          O checklist completo está no painel da direita.
        </p>
      )}

      {aberto && !compacto && (
        <>
          {plano.contexto ? (
            <p className="border-t border-stone-200 px-3 py-2 text-[11px] leading-5 text-zinc-500">
              {plano.contexto.split('\n').filter(Boolean)[0]}
            </p>
          ) : null}
          <ul className="space-y-0.5 border-t border-stone-200 px-3 py-2.5">
            {tarefas.map(t => <Linha key={t.id} t={t} proxima={t.id === proximaId} />)}
          </ul>
          {plano.telemetria && plano.telemetria.sessoes > 1 ? (
            <p className="border-t border-stone-200 px-3 py-1.5 text-[10px] text-zinc-400">
              {plano.telemetria.sessoes} sessões · {plano.telemetria.tentativas} tentativas
            </p>
          ) : null}
        </>
      )}
    </div>
  );
};
