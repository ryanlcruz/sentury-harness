import React, { useEffect, useRef, useState } from 'react';
import { copiar } from '../../runtime/clipboard';
import { contarTarefas, renderMarkdown } from '../../domain/markdown';
import { renderizarDiagramas } from '../../domain/mermaid';
import { ChatMessage } from '../../contracts/domain/session';
import { ExecutionTrace } from './ExecutionTrace';
import { CommandCard } from './CommandCard';
import { ClarificationSheet } from './ClarificationSheet';
import { PermissionSheet } from './PermissionSheet';
import { CabecaDoResidente, semPrefixoDoResidente } from '../residentes/NaConversa';
import { TextoComTokens } from './TextoComTokens';
import { comandoAutorizado, residenteAprovado } from './autorizacao';
import { lerRespostas } from '../../domain/clarification';
import { PlanoCard } from './PlanoCard';
import { MarcoDaConversa } from './MarcoDaConversa';
import { EncaminhadoAMesa, EncaminhadoAosResidentes } from './EncaminhadoAosResidentes';
import { mencionados } from './ResidenteTrabalhando';
import { abrirAssuntoDaMesa, abrirConversaDoResidente } from '../residentes/abrirConversa';
import { nomeVisivel } from '../residentes/api';
import { NavegadorCard } from './NavegadorCard';
import { ComputadorCard } from './ComputadorCard';
import { ResponseSignals } from './ResponseSignals';
import { AttachmentRenderer } from './AttachmentRenderer';
import { useProcessTraceEnabled } from '../../runtime/preferences';
import { Check, CircleStop, Copy, ListChecks, MessageSquare, RefreshCw, RotateCw, Users } from 'lucide-react';
import { PropostaDoBloco } from './PropostaDoBloco';
import { aoClicarNoCodigo } from '../../domain/blocoVivo/visualizar';
import { tabelaParaArtefato } from '../../domain/artifact-normalizer';
import { AttachmentStrip } from './AttachmentStrip';
import { DICA_DA_FASE, ROTULO_DA_FASE } from './orientacao';
import { useChatStore } from '../../stores/chat-store';
import { useWorkbenchStore } from '../../stores/workbench-store';

interface MessageBubbleProps {
  message: ChatMessage;
  isLatest?: boolean;
  latestBrowser?: boolean;
  latestComputer?: boolean;
  /** O residente dono da conversa aberta: nela, o atalho para a conversa dele sai. */
  naConversaDe?: string;
}


// A entrada nao e um numero so: parte dela pode ter vindo do cache do provedor,
// cobrada a 10%. Sem separar, um turno barato e um caro parecem iguais.
const detalharTokens = (custo: { tokens?: number; tokensEntrada?: number; tokensCacheados?: number }): string => {
  const n = (v?: number) => (v || 0).toLocaleString('pt-BR');
  if (!custo.tokensEntrada) return 'Tokens gerados neste turno';
  const partes = [`${n(custo.tokensEntrada)} de entrada`];
  if (custo.tokensCacheados) {
    const pct = Math.round((custo.tokensCacheados / custo.tokensEntrada) * 100);
    partes.push(`${n(custo.tokensCacheados)} vieram do cache (${pct}%, cobrados a 10%)`);
  }
  partes.push(`${n(custo.tokens)} gerados`);
  return partes.join(' · ');
};

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message, isLatest = false, latestBrowser = false, latestComputer = false, naConversaDe }) => {
  const processTraceEnabled = useProcessTraceEnabled();
  const [copied, setCopied] = useState(false);
  const retryLastMessage = useChatStore(state => state.retryLastMessage);
  // Marco de sistema (compactacao): linha discreta, nao bolha de resposta.
  if (message.role === 'system') {
    return <MarcoDaConversa texto={message.content} />;
  }
  // A confirmação de que o pedido saiu para os residentes é um aviso, não fala.
  if (message.role === 'assistant' && message.mesa && !message.mesa.resumo) {
    return <EncaminhadoAMesa id={message.mesa.id} titulo={message.mesa.titulo} texto={message.content} />;
  }
  if (message.role === 'assistant' && !message.residente && mencionados(message).length) {
    return <EncaminhadoAosResidentes nomes={mencionados(message)} texto={message.content} />;
  }

  // A aprovação dada no cartão vira registro, não balão: quem falou foi o botão.
  const autorizado = message.role === 'user' ? comandoAutorizado(message.content) : null;
  if (autorizado) {
    const residentes = residenteAprovado(autorizado);
    return (
      <div className="mb-5 flex items-center justify-end gap-1.5 text-xs text-zinc-500" title={message.content}>
        <Check className="h-3.5 w-3.5 text-emerald-600" />
        {residentes
          ? <span>Você aprovou criar {residentes.length > 1 ? 'os residentes' : 'o residente'}{' '}
              <strong className="font-semibold text-zinc-700">
                {residentes.length > 1 ? `${residentes.slice(0, -1).join(', ')} e ${residentes.at(-1)}` : residentes[0]}
              </strong></span>
          : <span>Você autorizou <code className="rounded bg-stone-100 px-1 font-mono text-[11px] text-zinc-700">{autorizado}</code></span>}
        {message.timestamp ? <span className="text-zinc-400">· {message.timestamp}</span> : null}
      </div>
    );
  }

  if (message.role === 'user' && message.automatico) {
    // O texto inteiro e instrucao para o agente; a pessoa so precisa saber que
    // o turno foi do goal, e qual.
    const turno = message.content.match(/turno (\d+) de (\d+)/);
    return (
      <div className="mb-4 flex items-center gap-2 text-[11px] text-zinc-400" title={message.content}>
        <RotateCw className="h-3 w-3" />
        <span>Continuação automática do objetivo{turno ? ` · turno ${turno[1]} de ${turno[2]}` : ''}</span>
      </div>
    );
  }

  // As respostas da folha de perguntas viram cartão, não balão: o texto é o
  // pacote que o servidor valida, e o que a pessoa precisa rever é o que escolheu.
  const respostas = message.role === 'user' ? lerRespostas(message.content) : null;
  if (respostas) {
    return (
      <div className="mb-6 flex animate-[sentury-message-in_220ms_ease-out] justify-end">
        <section aria-label="Suas escolhas" className="w-[min(460px,74%)] overflow-hidden rounded-xl border border-[#e3ddcd] bg-[#fffdf8] shadow-[0_10px_24px_rgba(22,22,22,0.06)]">
          <header className="flex items-center gap-2 border-b border-[#ebe5d8] bg-[#f6f2e8] px-3.5 py-2">
            <ListChecks className="h-3.5 w-3.5 text-gold-ink" />
            <span className="text-[10px] font-bold uppercase tracking-[.13em] text-gold-ink">Suas escolhas</span>
            {message.timestamp ? <span className="ml-auto text-[10px] text-zinc-400">{message.timestamp}</span> : null}
          </header>
          <dl className="divide-y divide-[#efe9dc]">
            {respostas.map((item, indice) => (
              <div key={indice} className="px-3.5 py-2.5">
                <dt className="text-[11px] leading-snug text-zinc-500">{item.pergunta}</dt>
                <dd className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {item.escolhas.map(escolha => (
                    <span key={escolha} className="inline-flex items-center gap-1 rounded-full border border-gold bg-gold-soft/50 px-2.5 py-0.5 text-xs font-medium text-zinc-900">
                      <Check className="h-3 w-3 text-gold-ink" />{escolha}
                    </span>
                  ))}
                  {item.outro ? <span className="text-xs italic text-zinc-700">“{item.outro}”</span> : null}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    );
  }

  if (message.role === 'user') {
    return (
      <div className="mb-6 flex animate-[sentury-message-in_220ms_ease-out] justify-end">
        <div className="max-w-[min(460px,74%)] rounded-lg border border-zinc-800 bg-bubble-user px-3 py-2.5 text-[#fffdf7] shadow-[0_10px_24px_rgba(22,22,22,0.12)]">
          {message.imagens?.length ? (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {message.imagens.map((imagem, indice) => imagem.dataUrl ? (
                <img
                  key={`${imagem.nome}-${indice}`}
                  src={imagem.dataUrl}
                  alt={imagem.nome}
                  className="max-h-40 rounded-md border border-white/15 object-cover"
                />
              ) : (
                // Sessao recarregada: o base64 nao e persistido, so o nome.
                <span key={`${imagem.nome}-${indice}`} className="rounded-md border border-white/20 bg-white/10 px-2 py-1 text-[10px] text-white/70">
                  {imagem.nome}
                </span>
              ))}
            </div>
          ) : null}
          <p className="whitespace-pre-wrap text-sm font-medium leading-relaxed"><TextoComTokens texto={message.content} /></p>
          {message.orientacao ? (
            // Mandada com o turno rodando: diz onde ela esta. Ver orientacao.ts.
            <span className="mt-1.5 flex items-center justify-end gap-1.5 text-[10px] text-white/60" title={DICA_DA_FASE[message.orientacao.fase]}>
              <span className={`h-1.5 w-1.5 rounded-full ${message.orientacao.fase === 'vista' ? 'bg-emerald-400' : message.orientacao.fase === 'aplicada' ? 'bg-gold' : 'animate-pulse bg-white/60'}`} />
              <span>orientação · {ROTULO_DA_FASE[message.orientacao.fase]}</span>
              {message.timestamp ? <span className="text-white/45">· {message.timestamp}</span> : null}
            </span>
          ) : message.timestamp && <span className="mt-1 block text-right text-[10px] text-white/55">{message.timestamp}</span>}
        </div>
      </div>
    );
  }

  const parsedHtml = renderMarkdown(message.residente ? semPrefixoDoResidente(message.content, message.residente) : message.content);
  const tarefas = contarTarefas(message.content);
  const abrirTarefas = () => {
    const id = `tarefas-${message.id}`;
    const { addArtifact, openWorkbench } = useWorkbenchStore.getState();
    addArtifact({ id, type: 'markdown', title: 'Tarefas', content: message.content,
                  sessionId: message.sessionId || '', createdAt: new Date().toISOString() });
    openWorkbench(id);
  };
  const corpoRef = useRef<HTMLDivElement>(null);
  // A tabela vai ao painel quando a pessoa pede; nenhuma vai sozinha.
  const levarTabelaAoPainel = (alvo: HTMLElement): boolean => {
    const botao = alvo.closest<HTMLElement>('[data-tabela-painel]');
    if (!botao) return false;
    const tabela = botao.closest('.md-tabela')?.querySelector('table');
    if (!tabela) return true;
    const todas = Array.from(corpoRef.current?.querySelectorAll('.md-tabela table') ?? []);
    const id = `${message.id}-tabela-${todas.indexOf(tabela) + 1}`;
    const { addArtifact, openWorkbench } = useWorkbenchStore.getState();
    addArtifact(tabelaParaArtefato(tabela, message.sessionId || '', id));
    openWorkbench(id);
    botao.textContent = 'No painel';
    return true;
  };

  // O diagrama e renderizado depois da montagem para a lib do mermaid so ser
  // baixada quando existe um diagrama de verdade na resposta.
  useEffect(() => {
    if (corpoRef.current) void renderizarDiagramas(corpoRef.current);
  }, [parsedHtml]);
  const copyMessage = async () => {
    setCopied(await copiar(message.content));
    window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <div className="mb-8 flex animate-[sentury-message-in_260ms_ease-out] justify-start">
      <div className="w-full max-w-3xl">
        {message.residente ? <CabecaDoResidente nome={message.residente} /> : null}
        {message.mesa?.resumo ? (
          <div className="mb-2 flex items-center gap-2 text-sm">
            <Users className="h-4 w-4 text-gold-hover" aria-hidden />
            <span className="font-semibold text-zinc-900">Mesa fechou: {message.mesa.titulo}</span>
          </div>
        ) : null}
        {processTraceEnabled && Boolean(message.traces?.length) && <ExecutionTrace stages={message.traces || []} />}
        {/* A caixa de aprovacao vive DENTRO do bloco que a pediu. Solta, ela
            aparecia vinte linhas abaixo do comando, e com dois pedidos ao mesmo
            tempo ninguem sabia qual estava aprovando. */}
        {/* O que o navegador fez, antes da resposta: foi o que a produziu. */}
        {message.navegador && <NavegadorCard cartao={message.navegador} sessionId={message.sessionId} latest={latestBrowser} />}
        {message.computador && <ComputadorCard cartao={message.computador} sessionId={message.sessionId} latest={latestComputer} />}
        {message.commands?.filter(run => !(message.navegador && run.tool === 'browser') && !(message.computador && run.tool === 'computador')).map(run => (
          <CommandCard
            key={run.id}
            run={run}
            defaultOpen={false}
            pendente={Boolean(message.permissao) && message.permissaoId === run.id}
            aprovacao={message.permissao && message.permissao.ferramenta !== 'criar_agente' && message.permissaoId === run.id ? (
              <PermissionSheet sessionId={message.sessionId} messageId={message.id} permissao={message.permissao} />
            ) : null}
          />
        ))}
        {message.content && <div
          className={`prose prose-sm max-w-none leading-relaxed ${message.status === 'interrupted' ? 'text-zinc-500' : 'text-zinc-800'}
                     prose-headings:text-zinc-900 prose-headings:font-semibold prose-h3:mb-2 prose-h3:mt-4 prose-h3:text-sm
                     prose-table:my-4 prose-table:w-full prose-table:border-separate prose-table:border-spacing-0 prose-table:overflow-hidden prose-table:rounded-xl prose-table:border prose-table:border-stone-300
                     prose-th:border-0 prose-th:border-b prose-th:border-stone-300 prose-th:bg-[#e9e4d8] prose-th:px-3 prose-th:py-2.5 prose-th:text-xs prose-th:font-semibold prose-th:text-zinc-700
                     prose-td:border-0 prose-td:border-b prose-td:border-stone-200 prose-td:px-3 prose-td:py-2.5 prose-td:text-sm prose-td:text-zinc-700
                     prose-ul:my-2 prose-li:my-0.5`}
          ref={corpoRef}
          onClick={evento => {
            const alvo = evento.target as HTMLElement;
            if (levarTabelaAoPainel(alvo)) return;
            const codigo = aoClicarNoCodigo(alvo);
            if (codigo != null) void copiar(codigo);
          }}
          dangerouslySetInnerHTML={{ __html: parsedHtml }}
        />}
        {/* A lista no chat so informa; acompanhar e marcar e no painel. */}
        {tarefas.total >= 3 && (
          <div className="mt-2 flex items-center gap-2 text-xs text-zinc-500">
            <ListChecks className="h-3.5 w-3.5" />
            <span className="tabular-nums">{tarefas.feitas} de {tarefas.total} feitas{tarefas.andamento ? ` · ${tarefas.andamento} em andamento` : ''}</span>
            <button type="button" onClick={abrirTarefas}
                    className="rounded-md px-1.5 py-0.5 font-medium text-gold-hover hover:bg-stone-100">
              Abrir no workbench
            </button>
          </div>
        )}
        {message.status === 'interrupted' && (
          <div className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-zinc-500" role="status">
            <CircleStop className="h-3.5 w-3.5" />
            Geração interrompida
          </div>
        )}
        {message.clarification && (
          <ClarificationSheet sessionId={message.sessionId} messageId={message.id} clarification={message.clarification} />
        )}
        {/* Sem bloco correspondente ela continua aqui: melhor solta do que
            grudada no bloco errado — e ha permissao que nasce antes do plano. */}
        {/* A fábrica de residente fica no corpo da conversa, nunca dentro do bloco do comando. */}
        {message.permissao && (message.permissao.ferramenta === 'criar_agente' || !message.commands?.some(run => run.id === message.permissaoId)) && (
          <PermissionSheet sessionId={message.sessionId} messageId={message.id} permissao={message.permissao} />
        )}
        {/* O workflow existia so em disco. Vem antes dos sinais porque, quando
            ha um portao, ele e a unica coisa da tela que exige o usuario. */}
        {message.plano && <PlanoCard plano={message.plano} sessionId={message.sessionId} compacto />}
        {message.signals && <ResponseSignals sessionId={message.sessionId} signals={message.signals} />}
        {Array.isArray(message.anexos) && message.anexos.length > 1 && (
          <AttachmentStrip sessionId={message.sessionId} anexos={message.anexos as never[]} />
        )}
        {!(Array.isArray(message.anexos) && message.anexos.length > 1) && Boolean(message.signals?.attachment) && (
          <AttachmentRenderer
            sessionId={message.sessionId}
            rawAttachment={message.signals?.attachment}
            validation={message.signals?.attachmentValidation}
          />
        )}
        {message.status !== 'interrupted' && <div className="mt-3 flex items-center gap-1 text-zinc-500">
          <button type="button" onClick={() => void copyMessage()} className="rounded-md p-1.5 hover:bg-stone-200/70 hover:text-zinc-900" title="Copiar resposta">{copied ? <Check className="h-3.5 w-3.5 text-emerald-700" /> : <Copy className="h-3.5 w-3.5" />}</button>
          {/* Dentro da conversa dele, levar à conversa dele não leva a lugar nenhum. */}
          {message.residente && message.residente !== naConversaDe ? (
            <button type="button" onClick={() => abrirConversaDoResidente(message.residente as string)}
                    className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-medium text-gold-hover hover:bg-stone-200/70"
                    title="A troca completa fica no chat dele">
              <MessageSquare className="h-3.5 w-3.5" />
              Continuar com {nomeVisivel(message.residente)}
            </button>
          ) : null}
          {message.residente && message.residente !== naConversaDe ? <span className="text-[11px] text-zinc-400">ou escreva @{message.residente} aqui</span> : null}
          {message.mesa?.resumo ? (
            <button type="button" onClick={() => abrirAssuntoDaMesa(message.mesa!.id)}
                    className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-medium text-gold-hover hover:bg-stone-200/70">
              <Users className="h-3.5 w-3.5" />
              Abrir a Mesa
            </button>
          ) : null}
          {isLatest && !message.residente && <button type="button" onClick={() => void retryLastMessage(message.sessionId)} className="rounded-md p-1.5 hover:bg-stone-200/70 hover:text-zinc-900" title="Gerar novamente"><RefreshCw className="h-3.5 w-3.5" /></button>}
          {message.custo && (message.custo.ms || message.custo.tokens || message.custo.usd != null) ? (
            <span className="ml-1 flex flex-wrap items-center gap-x-2 text-[10px] tabular-nums text-zinc-400">
              {message.custo.ms ? <span title="Tempo do turno">{(message.custo.ms / 1000).toFixed(1)}s</span> : null}
              {message.custo.tokens ? (
                <span title={detalharTokens(message.custo)}>
                  {message.custo.tokens.toLocaleString('pt-BR')} gerados
                </span>
              ) : null}
              {message.custo.usd != null ? <span title="Custo estimado pelo preco publicado do modelo">US$ {message.custo.usd.toFixed(4)}</span> : null}
              {message.custo.modelo ? <span className="font-mono" title="Modelo que respondeu">{message.custo.modelo}</span> : null}
              {message.custo.recusas?.length ? (
                <span className="text-amber-700" title="Recusou pela política de conteúdo dele; o Router passou ao próximo modelo">
                  {message.custo.recusas.join(', ')} recusou
                </span>
              ) : null}
            </span>
          ) : null}
        </div>}
        {message.content && <PropostaDoBloco corpo={corpoRef} sessionId={message.sessionId} />}
      </div>
    </div>
  );
};
