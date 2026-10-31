import React, { useEffect, useState } from 'react';
import { BrainCircuit, Check, ChevronDown, ChevronRight, Loader2, TriangleAlert } from 'lucide-react';
import { ExecutionStage } from '../../contracts/domain/session';
import { CapabilityIcon, capabilityOfText } from '../../components/CapabilityMark';

interface ExecutionTraceProps {
  stages: ExecutionStage[];
  isStreaming?: boolean;
}

export const ExecutionTrace: React.FC<ExecutionTraceProps> = ({ stages, isStreaming }) => {
  // Enquanto roda, aberto. Fechado, o turno parecia ter parado: a atividade
  // existia e estava atras de um clique que ninguem sabia que precisava dar.
  const [escolhaDoUsuario, setEscolhaDoUsuario] = useState<boolean | null>(null);

  // Quando o turno termina, volta a fechar — mas so se o usuario nao tiver
  // mexido. Reabrir o que ele fechou seria a tela discutindo com ele.
  useEffect(() => {
    if (!isStreaming) setEscolhaDoUsuario(null);
  }, [isStreaming]);

  if (!stages.length) return null;

  const isOpen = escolhaDoUsuario ?? Boolean(isStreaming);
  const setIsOpen = (proximo: boolean | ((a: boolean) => boolean)) =>
    setEscolhaDoUsuario(atual => {
      const agora = atual ?? Boolean(isStreaming);
      return typeof proximo === 'function' ? proximo(agora) : proximo;
    });

  // O passo corrente e o ultimo enquanto o turno nao acabou: o servidor manda
  // `running` em alguns eventos e omite em outros, e uma lista de checks
  // identicos nao diz onde o agente esta agora.
  const indiceCorrente = isStreaming ? stages.length - 1 : -1;

  return (
    <div className="mb-3 text-zinc-500">
      <button
        type="button"
        onClick={() => setIsOpen(open => !open)}
        className="flex items-center gap-2 py-1 text-xs font-semibold transition-colors hover:text-zinc-800"
        aria-expanded={isOpen}
      >
        <BrainCircuit className="h-3.5 w-3.5" />
        <span>Processo analítico</span>
        <span className="font-normal text-zinc-400">
          {/* Contagem E passo atual. So o atual escondia o historico do turno
              quando varias ferramentas rodam em sequencia; so a contagem nao
              responde "ele esta fazendo o que agora?". */}
          {stages.length} {stages.length === 1 ? 'etapa' : 'etapas'}
          {isStreaming && stages.length
            ? ` · ${stages[stages.length - 1].stage || stages[stages.length - 1].text}`
            : ''}
        </span>
        {isStreaming && <Loader2 className="sentury-working-indicator h-3 w-3 text-gold-hover" />}
        {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
      </button>

      {isOpen && (
        <div className="ml-1 mt-2 space-y-2 border-l border-stone-300 pl-4">
          {stages.map((stage, index) => (
            <div key={`${stage.stage}-${index}`} className="flex items-start gap-2 text-xs">
              {/* Check e a afirmacao "isto terminou". Fazia-la no passo que
                  ainda esta rodando era dizer o que nao aconteceu. */}
              {stage.status === 'failed'
                ? <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-600" />
                : (stage.status === 'running' || index === indiceCorrente)
                  ? <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-gold-hover" />
                  : <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />}
              {/* O passo guardado tambem carrega a marca da capacidade: sem
                  isso o historico vira uma lista de checks iguais. */}
              <CapabilityIcon capability={capabilityOfText(stage.stage || stage.text || '')} className="mt-0.5 h-3 w-3 shrink-0" />
              <span className={index === indiceCorrente ? 'font-medium text-zinc-800' : 'text-zinc-600'}>
                {stage.stage || stage.text}
              </span>
              {stage.durationMs != null && <span className="ml-auto text-[10px] tabular-nums text-zinc-400">{stage.durationMs} ms</span>}
            </div>
          ))}

        </div>
      )}
    </div>
  );
};
