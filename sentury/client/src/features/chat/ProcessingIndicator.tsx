import React from 'react';
import { LoaderCircle } from 'lucide-react';
import { ExecutionStage } from '../../contracts/domain/session';
import { PlanEntry } from '../../contracts/events/session-events';
import { useProcessTraceEnabled } from '../../runtime/preferences';
import { CommandCard } from './CommandCard';
import { MarcoDaConversa } from './MarcoDaConversa';
import { CAPABILITIES, capabilityOfKind, capabilityOfText } from '../../components/CapabilityMark';


interface ProcessingIndicatorProps {
  stages: ExecutionStage[];
  plan: PlanEntry[];
}

export const ProcessingIndicator: React.FC<ProcessingIndicatorProps> = ({
  stages,
  plan,
}) => {
  const processTraceEnabled = useProcessTraceEnabled();
  const runningStep = plan.find(entry => entry.status === 'running');
  const currentStage = runningStep?.title || stages.at(-1)?.stage || 'Analisando pedido e preparando contexto…';
  const normalizedStage = currentStage.toLocaleLowerCase('pt-BR');
  const isSkill = normalizedStage.includes('skill');
  // Compactar nao e responder. A tela dizia "Processando resposta" enquanto
  // reescrevia o historico — o rotulo errado no momento em que o usuario mais
  // quer saber o que esta acontecendo com a conversa dele.
  const isCompactando = normalizedStage.includes('compactando');
  const isWriting = /redig|resposta|organizando/.test(normalizedStage);
  const isTool = Boolean(runningStep) || /ferrament|execut|gerando|export|calcul/.test(normalizedStage);
  // Com passo rodando, a capacidade e a DELE: o palpite pelo texto so vale
  // enquanto nao ha ferramenta, senao o icone troca no meio da execucao.
  const capacidade = runningStep
    ? capabilityOfKind(runningStep.kind || '')
    : isCompactando
      ? 'memory'
      : capabilityOfText(currentStage);
  const marca = CAPABILITIES[capacidade];
  const StatusIcon = marca.Icon;
  const label = isCompactando
    ? 'Compactando a conversa'
    : isSkill
    ? 'Usando uma skill'
    : runningStep
      ? runningStep.title || 'Executando'
      : isTool
      ? 'Executando'
      : isWriting
        ? 'Redigindo resposta'
        : 'Processando resposta';

  // O rotulo e derivado do proprio estagio, entao os dois costumam dizer a
  // mesma coisa ("Redigindo resposta" / "Redigindo a resposta..."). A linha de
  // detalhe so aparece quando acrescenta informacao.
  const soLetras = (t: string) => t.toLocaleLowerCase('pt-BR').replace(/[^a-zà-ÿ]/g, '');
  // A linha de detalhe repetia o passo que ja aparece na lista logo abaixo.
  const repeteORotulo = soLetras(currentStage).includes(soLetras(label).slice(0, 8));
  const repeteOPasso = processTraceEnabled && plan.some(entry => entry.title === currentStage);
  const detalheRepete = repeteORotulo || repeteOPasso;

  // Compactar é algo que acontece com a conversa: o marco da conversa, e não o
  // bloco de quem está respondendo. Ao terminar, ele vira o marco final.
  if (isCompactando && !runningStep) return <MarcoDaConversa texto="Compactando a conversa" emCurso />;

  return (
    <div className="mb-8 mt-2 w-full max-w-3xl" role="status" aria-live="polite">
      <div className="flex items-start gap-3 text-zinc-700">
        <span className={`sentury-processing-icon relative mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${marca.fundo} ${marca.texto}`}>
          <StatusIcon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="sentury-processing-label flex items-center gap-2 text-sm font-semibold">
            {/* Nome da ferramenta e o passo em palavras: o nome diz o que roda, a
                frase diz para quê. */}
            {runningStep && !isSkill && !isCompactando && runningStep.tool ? (
              <>
                <span className="font-mono text-[13px] text-zinc-900">{runningStep.tool}</span>
                <span className="font-normal text-zinc-700">{label}</span>
              </>
            ) : label}
            {detalheRepete && <LoaderCircle className="sentury-working-indicator h-3 w-3 shrink-0 text-gold-hover" />}
          </p>
          {!detalheRepete && <p className="mt-0.5 flex items-center gap-2 text-xs leading-5 text-zinc-500"><LoaderCircle className="sentury-working-indicator h-3 w-3 shrink-0 text-gold-hover" />{currentStage}</p>}
          {/* O pensamento vale ate a primeira ferramenta. Dali em diante ele
              para de chegar e o bloco congela: o usuario le "vou verificar esta
              pasta agora" parado enquanto a verificacao ja aconteceu — e
              continua lendo isso enquanto a resposta e redigida. A partir do
              primeiro passo, quem conta a historia e a execucao; o texto
              inteiro continua no Processo Analitico, depois. */}
          {/* Raciocinio cru nao e estado operacional. O provedor pode escrever
              hipoteses e o proprio contrato do planner; exibi-lo fazia um
              plano vazio parecer trabalho em andamento. A tela mostra somente
              etapas e ferramentas observaveis. */}
          {processTraceEnabled && plan.length > 0 && (
            <div className="mt-3 space-y-1.5 text-xs text-zinc-500">
              {plan.map(entry => (
                <div key={entry.id}>
                  {/* A fala vem antes do passo que ela anuncia: o porquê
                      primeiro, a execução depois. Sem ela a ferramenta rodava
                      em silêncio e a pessoa só descobria no fim. */}
                  {entry.fala ? (
                    <p className="mb-1 mt-2 text-xs leading-5 text-zinc-600">{entry.fala}</p>
                  ) : null}
                  {/* Uma anatomia so: o cartao vale para toda execucao,
                      com ou sem comando. Duas formas na mesma lista era o que
                      fazia a linha sem comando parecer outra coisa. */}
                  <CommandCard run={entry} defaultOpen={(entry.command || '').includes('\n')} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
