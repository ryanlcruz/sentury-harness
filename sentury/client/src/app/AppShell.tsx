import React, { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { GoalCard } from '../features/chat/GoalCard';
import { NavegadorCard } from '../features/chat/NavegadorCard';
import { ComputadorCard } from '../features/chat/ComputadorCard';
import { CheckpointSheet } from '../features/chat/CheckpointSheet';
import { TurnoInterrompidoCard } from '../features/chat/TurnoInterrompidoCard';
import { ReconectandoAviso } from '../features/chat/ReconectandoAviso';
import { ArrowDown, Bug, History, X } from 'lucide-react';
import { MigrationNotice } from '../components/MigrationNotice';
import { IconRail } from '../components/IconRail';
import { Composer } from '../features/chat/Composer';
import type { SettingsSection } from '../features/settings/FullSettingsView';
import { MessageBubble } from '../features/chat/MessageBubble';
import { ResidenteTrabalhando } from '../features/chat/ResidenteTrabalhando';
import { aoAbrirAssuntoDaMesa, aoAbrirConversaDoResidente } from '../features/residentes/abrirConversa';
import { ProcessingIndicator } from '../features/chat/ProcessingIndicator';
import { OperationsDrawer } from '../features/harness/OperationsDrawer';
import { HarnessView } from '../features/harness/HarnessView';
import { ChatNavigator } from '../features/navigator/ChatNavigator';
import { DomainNavigator } from '../features/navigator/DomainNavigator';
import { WorkbenchPanel } from '../features/workbench/WorkbenchPanel';
import { ScopeBar } from '../features/chat/ScopeBar';
import { authHeaders, getRuntimeConfig } from '../runtime/config';
import { useChatStore } from '../stores/chat-store';
import { useHarnessStore } from '../stores/harness-store';
import { useSessionStore } from '../stores/session-store';
import { useWorkbenchStore } from '../stores/workbench-store';
import { apiClient } from '../transport/http-client';
import { DomainId, FeatureId } from './navigation';
import { LogoQueViraCoruja } from './LogoQueViraCoruja';
import { PrimeiroAcesso } from './PrimeiroAcesso';

const ProvidersView = lazy(() => import('../features/runtime/ProvidersView').then(module => ({ default: module.ProvidersView })));
const FullSettingsView = lazy(() => import('../features/settings/FullSettingsView').then(module => ({ default: module.FullSettingsView })));
const UsageView = lazy(() => import('../features/observability/UsageView').then(module => ({ default: module.UsageView })));
const DomainsView = lazy(() => import('../features/knowledge/DomainsView').then(module => ({ default: module.DomainsView })));
const SkillsView = lazy(() => import('../features/knowledge/SkillsView').then(module => ({ default: module.SkillsView })));
const MemoryView = lazy(() => import('../features/knowledge/MemoryView').then(module => ({ default: module.MemoryView })));
const RobinBanditView = lazy(() => import('../features/runtime/RobinBanditView').then(module => ({ default: module.RobinBanditView })));
const TracesView = lazy(() => import('../features/observability/TracesView').then(module => ({ default: module.TracesView })));
const MutationView = lazy(() => import('../features/mutation/MutationView').then(module => ({ default: module.MutationView })));
const EvalsView = lazy(() => import('../features/observability/EvalsView').then(module => ({ default: module.EvalsView })));
const TasksView = lazy(() => import('../features/work/TasksView').then(module => ({ default: module.TasksView })));
const SchedulesView = lazy(() => import('../features/work/SchedulesView').then(module => ({ default: module.SchedulesView })));
const ContextEngineView = lazy(() => import('../features/knowledge/ContextEngineView').then(module => ({ default: module.ContextEngineView })));
const ToolsCatalogView = lazy(() => import('../features/runtime/ToolsCatalogView').then(module => ({ default: module.ToolsCatalogView })));
const ArtifactsView = lazy(() => import('../features/workbench/ArtifactsView').then(module => ({ default: module.ArtifactsView })));
const DiagnosticsView = lazy(() => import('../features/observability/DiagnosticsView').then(module => ({ default: module.DiagnosticsView })));
const HQView = lazy(() => import('../features/residentes/HQView').then(module => ({ default: module.HQView })));
const ConversaDoResidente = lazy(() => import('../features/residentes/ConversaDoResidente'));
const MesaView = lazy(() => import('../features/residentes/MesaView'));
const HelpLibraryView = lazy(() => import('../features/help/HelpLibraryView').then(module => ({ default: module.HelpLibraryView })));

const LoadingSurface = () => <div className="flex h-full items-center justify-center text-xs text-zinc-500"><span className="sentury-processing-label">Carregando área…</span></div>;

const featureDomains: Record<FeatureId, DomainId> = {
  harness: 'runtime',
  mutation: 'observability',
  hq: 'work',
  help: 'knowledge',
  conversations: 'chat',
  tasks: 'work',
  schedules: 'work',
  artifacts: 'work',
  context: 'knowledge',
  memory: 'knowledge',
  skills: 'knowledge',
  domains: 'knowledge',
  providers: 'runtime',
  robinbandit: 'runtime',
  mcp: 'runtime',
  traces: 'observability',
  usage: 'observability',
  evals: 'observability',
  diagnostics: 'observability',
};


// A hora do dia muda o cumprimento, e só isso: "boa noite" às 3 da tarde é o
// tipo de detalhe que faz a interface parecer desatenta.
const saudacao = (): string => {
  const hora = new Date().getHours();
  if (hora < 5) return 'Ainda acordado?';
  if (hora < 12) return 'Bom dia. Como posso ajudar?';
  if (hora < 18) return 'Boa tarde. O que você precisa?';
  return 'Boa noite. Por onde começamos?';
};

export const AppShell: React.FC = () => {
  const [panelDomain, setPanelDomain] = useState<DomainId | null>(null);
  const [isRailExpanded, setIsRailExpanded] = useState(false);
  const [activeFeature, setActiveFeature] = useState<FeatureId>('conversations');
  const [isQuickSheetOpen, setIsQuickSheetOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSection>('overview');
  const [isAwayFromLatest, setIsAwayFromLatest] = useState(false);
  const [composerHeight, setComposerHeight] = useState(96);
  const [verCheckpoints, setVerCheckpoints] = useState(false);
  const [conversaResidente, setConversaResidente] = useState<string | null>(null);
  const [mesaAberta, setMesaAberta] = useState(false);
  const [assuntoDaMesa, setAssuntoDaMesa] = useState<string | null>(null);
  // O HQ fica montado depois da primeira visita, escondido nas outras telas:
  // a sala do Escritório se pausa e volta de onde parou em vez de nascer de novo.
  const [hqVisitado, setHqVisitado] = useState(false);
  useEffect(() => { if (activeFeature === 'hq') setHqVisitado(true); }, [activeFeature]);
  useEffect(() => aoAbrirConversaDoResidente(nome => {
    setMesaAberta(false); setPanelDomain(null); setConversaResidente(nome); setActiveFeature('conversations');
  }), []);
  useEffect(() => aoAbrirAssuntoDaMesa(id => {
    setConversaResidente(null); setPanelDomain(null); setAssuntoDaMesa(id); setMesaAberta(true); setActiveFeature('conversations');
  }), []);
  // Qual residente a HQ abre; `vez` faz o mesmo clique abrir de novo.
  const [residenteAberto, setResidenteAberto] = useState<{ nome: string | null; vez: number }>({ nome: null, vez: 0 });
  const feedRef = useRef<HTMLDivElement>(null);
  const activeSessionId = useSessionStore(state => state.activeSessionId);
  const loadSessions = useSessionStore(state => state.loadSessions);
  const activeSessionTitle = useSessionStore(state => state.sessions.find(session => session.id === state.activeSessionId)?.title);
  const transcripts = useChatStore(state => state.transcripts);
  const streams = useChatStore(state => state.streams);
  const scopes = useChatStore(state => state.scopes);
  const loadSession = useChatStore(state => state.loadSession);
  const toggleHarnessDrawer = useHarnessStore(state => state.toggleDrawer);
  const [dominioAtivo, setDominioAtivo] = useState<string>('');
  const updateHarnessState = useHarnessStore(state => state.updateHarnessState);
  const seguirSessao = useHarnessStore(state => state.seguirSessao);

  // O painel do Harness e do turno da conversa aberta.
  useEffect(() => { seguirSessao(activeSessionId); }, [activeSessionId, seguirSessao]);

  const messages = activeSessionId ? transcripts[activeSessionId] || [] : [];
  const stream = activeSessionId ? streams[activeSessionId] : undefined;
  const ultimoNavegador = messages.reduce((indice, mensagem, atual) => mensagem.navegador ? atual : indice, -1);
  const ultimoComputador = messages.reduce((indice, mensagem, atual) => mensagem.computador ? atual : indice, -1);
  const stableStreamText = stream?.lastToken
    ? stream.text.slice(0, -stream.lastToken.length)
    : stream?.text || '';
  const scope = activeSessionId ? scopes[activeSessionId] || {} : {};
  const hasConversation = messages.length > 0 || Boolean(stream?.running);
  const currentDomain = featureDomains[activeFeature];

  const toggleDomainPanel = (domainId: DomainId) => {
    if (panelDomain === domainId) {
      setPanelDomain(null);
      return;
    }
    setPanelDomain(domainId);
    if (domainId === 'chat') setActiveFeature('conversations');
  };

  const selectFeature = (featureId: FeatureId) => {
    if (featureId === 'artifacts') useWorkbenchStore.getState().markArtifactsSeen();
    setActiveFeature(featureId);
    setPanelDomain(null);
  };

  useEffect(() => {
    void loadSessions();
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    void apiClient.get('/health', { headers: authHeaders() })
      .then(() => updateHarnessState({ status: 'online' }))
      .catch(() => updateHarnessState({ status: 'offline' }));
    // Sem pacote carregado ele é generalista; com um, responde pelo vocabulário
    // daquele setor. A tela precisa dizer qual dos dois está na frente.
    void apiClient.get<{ ativo?: string }>('/sentury/domains', { headers: authHeaders() })
      .then(dados => setDominioAtivo((dados?.ativo || '').toUpperCase()))
      .catch(() => setDominioAtivo(''));
  }, [loadSessions, updateHarnessState]);

  useEffect(() => {
    if (activeSessionId) void loadSession(activeSessionId);
  }, [activeSessionId, loadSession]);

  // Quantas conversas esperam a pessoa, na aba do navegador: dá para ver de
  // outra janela que alguma parou pedindo aprovação ou com pergunta.
  const esperando = useSessionStore(state => state.sessions.filter(session =>
    session.runtimeStatus === 'awaiting_approval' || session.runtimeStatus === 'awaiting_user').length);
  useEffect(() => {
    const nome = activeSessionTitle ? `${activeSessionTitle} · Sentury` : 'Sentury';
    document.title = esperando ? `(${esperando}) ${nome}` : nome;
  }, [activeSessionTitle, esperando]);

  useEffect(() => {
    setIsAwayFromLatest(false);
    window.requestAnimationFrame(() => {
      if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
    });
  }, [activeSessionId]);

  useEffect(() => {
    if (isAwayFromLatest) return;
    window.requestAnimationFrame(() => {
      feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: stream?.running ? 'smooth' : 'auto' });
    });
  }, [messages.length, stream?.stages.length, stream?.text.length, stream?.running, isAwayFromLatest]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        setIsQuickSheetOpen(previous => !previous);
      }
      if (event.key === 'Escape') setPanelDomain(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const chatCanvas = (
    <>
      {/* Sem faixa: uma barra de tela inteira para dois botoes deixava um
          vazio atravessado no topo quando nao havia escopo. Agora os controles
          flutuam sobre o feed e so o escopo, quando existe, ocupa espaco. */}
      {hasConversation && activeSessionId ? (
        <>
          {scope ? (
            <div className="pointer-events-none absolute inset-x-0 top-0 z-20 px-5 pt-2">
              <div className="pointer-events-auto mx-auto flex w-full max-w-[920px]">
                <ScopeBar sessionId={activeSessionId} scope={scope} />
              </div>
            </div>
          ) : null}
          <div className="absolute right-4 top-3 z-30 flex items-center gap-2">
            <button
              type="button"
              onClick={() => setVerCheckpoints(true)}
              className="flex h-8 cursor-pointer items-center gap-1.5 rounded-lg bg-zinc-900/90 px-3 text-[11px] font-semibold text-gold shadow-sm backdrop-blur transition-colors hover:bg-zinc-900"
              title="Pontos da conversa"
            >
              <History className="h-3.5 w-3.5" />Pontos
            </button>
            <button
              type="button"
              onClick={toggleHarnessDrawer}
              className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg border border-stone-300 bg-white/90 text-zinc-500 shadow-sm backdrop-blur transition-colors hover:border-gold hover:text-zinc-900"
              title="Diagnóstico do turno"
              aria-label="Diagnóstico do turno"
            >
              <Bug className="h-4 w-4" />
            </button>
          </div>
        </>
      ) : null}

      <div
        ref={feedRef}
        onScroll={event => {
          const node = event.currentTarget;
          setIsAwayFromLatest(node.scrollHeight - node.scrollTop - node.clientHeight > 120);
        }}
        className={`min-h-0 flex-1 overflow-y-auto scroll-smooth px-6 ${hasConversation ? 'pt-14' : 'pb-[38vh] pt-[10vh]'}`}
        style={hasConversation ? { paddingBottom: `${Math.max(144, composerHeight + 48)}px` } : undefined}
      >
        <div className="mx-auto w-full max-w-[920px]">
          {!hasConversation && (
            <div className="mx-auto max-w-xl text-center">
              <LogoQueViraCoruja />
              <p className="mt-3 text-[11px] font-bold uppercase tracking-[0.18em] text-gold-ink">Sentury</p>
              {/* A tela vazia convida, não anuncia especialidade: quem chega
                  quer começar, não ler a descrição do produto. */}
              <h1 className="mt-1 text-[34px] font-semibold tracking-tight text-zinc-950">{saudacao()}</h1>
              <p className="mt-2 text-sm text-zinc-600">Pergunte, peça uma análise ou diga o que precisa resolver.</p>
              {/* Só quando há um setor carregado: no generalista não há o que
                  anunciar, e um selo dizendo "nenhum" é ruído. */}
              {dominioAtivo && dominioAtivo.toLowerCase() !== 'generalista' && (
                <p className="mt-6 inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white/70 px-3 py-1 text-xs">
                  <span className="text-zinc-500">Setor</span>
                  <span className="font-semibold text-gold-ink">{dominioAtivo}</span>
                </p>
              )}
              <PrimeiroAcesso aoConfigurarOutros={() => setActiveFeature('providers')} />
            </div>
          )}

          {messages.map((message, index) => <MessageBubble key={message.id} message={message}
            isLatest={index === messages.length - 1 && message.role === 'assistant'}
            latestBrowser={index === ultimoNavegador && !stream?.running}
            latestComputer={index === ultimoComputador && !stream?.running} />)}
          {!stream?.running && activeSessionId ? <ResidenteTrabalhando sessionId={activeSessionId} mensagens={messages} /> : null}
          {stream?.running && (
            <>
              {/* Navegador e computador primeiro: são etapas já em curso, e o passo
                  atual (um shell depois do clique, por exemplo) nasce embaixo deles,
                  na ordem em que aconteceu. */}
              {stream.navegador && activeSessionId ? (
                <NavegadorCard cartao={stream.navegador} sessionId={activeSessionId} aoVivo />
              ) : null}
              {stream.computador && activeSessionId ? (
                <ComputadorCard cartao={stream.computador} sessionId={activeSessionId} aoVivo />
              ) : null}
              <ProcessingIndicator
                stages={stream.stages}
                plan={stream.plan}
              />
              {stream.reconectando ? (
                <ReconectandoAviso tentativa={stream.reconectando.tentativa} total={stream.reconectando.total} />
              ) : null}
              {stream.text ? (
                <p className="mb-8 max-w-3xl whitespace-pre-wrap text-sm leading-relaxed text-zinc-800" aria-live="polite">
                  {stableStreamText}
                  <span key={stream.text.length} className="sentury-stream-token">{stream.lastToken}</span>
                </p>
              ) : null}
            </>
          )}
          {activeSessionId ? <GoalCard sessionId={activeSessionId} conversando={Boolean(stream?.running)} /> : null}
          {activeSessionId ? <TurnoInterrompidoCard sessionId={activeSessionId} conversando={Boolean(stream?.running)} /> : null}
        </div>
      </div>


      {verCheckpoints && activeSessionId && (
        <CheckpointSheet sessionId={activeSessionId} onClose={() => setVerCheckpoints(false)} />
      )}

      {hasConversation && isAwayFromLatest && (
        <button
          type="button"
          onClick={() => {
            feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' });
            setIsAwayFromLatest(false);
          }}
          className="absolute left-1/2 z-30 flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-stone-300 bg-[#fffdf8] text-zinc-700 shadow-lg transition hover:-translate-y-0.5 hover:border-gold"
          style={{ bottom: `${composerHeight + 30}px` }}
          title="Ir para a última mensagem"
          aria-label="Ir para a última mensagem"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      )}

      <Composer
        hasConversation={hasConversation}
        onOpenQuickSheet={() => setIsQuickSheetOpen(true)}
        isQuickSheetOpen={isQuickSheetOpen}
        onCloseQuickSheet={() => setIsQuickSheetOpen(false)}
        onOpenHarness={() => { setPanelDomain(null); setActiveFeature('harness'); }}
        onOpenBrowserSettings={() => { setSettingsSection('browser'); setIsSettingsOpen(true); }}
        onHeightChange={setComposerHeight}
      />
    </>
  );

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-canvas text-zinc-900">
      <IconRail
        activeDomain={panelDomain || currentDomain}
        openDomain={panelDomain}
        onSelectDomain={toggleDomainPanel}
        onIrPara={feature => { setPanelDomain(null); setActiveFeature(feature as FeatureId); }}
        onOpenSettings={() => { setSettingsSection('overview'); setIsSettingsOpen(true); }}
        onOpenHelp={() => { setPanelDomain(null); setActiveFeature('help'); }}
        onOpenHarness={() => { setPanelDomain(null); setActiveFeature('harness'); }}
        harnessAtivo={activeFeature === 'harness'}
        onOpenHQ={nome => { setPanelDomain(null); setConversaResidente(null); setActiveFeature('hq'); setResidenteAberto({ nome: nome || null, vez: Date.now() }); }}
        hqAtivo={activeFeature === 'hq'}
        onOpenMutation={() => { setPanelDomain(null); setActiveFeature('mutation'); }}
        mutacaoAtivo={activeFeature === 'mutation'}
        isExpanded={isRailExpanded}
        onToggleExpanded={() => setIsRailExpanded(expanded => !expanded)}
      />

      {panelDomain && (
        <>
          <button
            type="button"
            aria-label="Fechar painel lateral"
            className="fixed inset-y-0 right-0 z-20 bg-zinc-950/10 backdrop-blur-[1px] transition-opacity"
            style={{ left: isRailExpanded ? '14rem' : '3.5rem' }}
            onClick={() => setPanelDomain(null)}
          />
          <div
            className="fixed inset-y-0 z-30 flex w-72 animate-[sentury-drawer-in_180ms_ease-out] shadow-[14px_0_38px_rgba(35,31,24,0.16)]"
            style={{ left: isRailExpanded ? '14rem' : '3.5rem' }}
          >
            {/* Clicar fora e Esc ja fechavam, mas sem alvo visivel nem todo
                mundo descobre. */}
            <button
              type="button"
              onClick={() => setPanelDomain(null)}
              className="absolute right-2 top-2 z-10 rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-stone-200/70 hover:text-zinc-700"
              title="Fechar painel (Esc)"
              aria-label="Fechar painel"
            >
              <X className="h-4 w-4" />
            </button>
            {/* Fechar tambem pelo X: clicar fora e Esc ja funcionavam, mas nem
                todo mundo descobre sem um alvo visivel. */}
            <button
              type="button"
              onClick={() => setPanelDomain(null)}
              className="absolute right-2 top-2 z-10 rounded-md p-1.5 text-zinc-400 transition-colors hover:bg-stone-200/70 hover:text-zinc-700"
              title="Fechar painel (Esc)"
              aria-label="Fechar painel"
            >
              <X className="h-4 w-4" />
            </button>
            {panelDomain === 'chat'
              ? <ChatNavigator residenteSelecionado={conversaResidente} mesaSelecionada={mesaAberta}
                  onNewChat={() => { setConversaResidente(null); setMesaAberta(false); setPanelDomain(null); }}
                  onSessionSelected={() => { setConversaResidente(null); setMesaAberta(false); setPanelDomain(null); }}
                  onResidenteSelected={nome => { setMesaAberta(false); setConversaResidente(nome); setActiveFeature('conversations'); setPanelDomain(null); }}
                  onMesaSelected={() => { setConversaResidente(null); setMesaAberta(true); setActiveFeature('conversations'); setPanelDomain(null); }}
                  onAbrirHQ={() => { setConversaResidente(null); setMesaAberta(false); setPanelDomain(null); setActiveFeature('hq'); }} />
              : (
                <DomainNavigator
                  domainId={panelDomain}
                  activeFeatureId={activeFeature}
                  onSelectFeature={selectFeature}
                />
              )}
          </div>
        </>
      )}

      <main id="sentury-main" className={`relative flex min-w-0 flex-1 flex-col overflow-hidden bg-canvas transition-[filter,opacity] duration-200 ${panelDomain ? 'pointer-events-none opacity-60 blur-[1px]' : ''}`}>
        <Suspense fallback={<LoadingSurface />}>{hqVisitado || activeFeature === 'hq' ? (
          <div className={activeFeature === 'hq' ? 'h-full min-h-0' : 'hidden'}>
            <HQView visivel={activeFeature === 'hq'} abrir={residenteAberto} onConversar={nome => { setMesaAberta(false); setConversaResidente(nome); setActiveFeature('conversations'); }} />
          </div>
        ) : null}{activeFeature === 'help'
          ? <HelpLibraryView onNavigate={selectFeature} />
          : activeFeature === 'hq'
          ? null
          : activeFeature === 'conversations'
          ? mesaAberta ? <MesaView key={assuntoDaMesa || 'mesa'} inicial={assuntoDaMesa} /> : conversaResidente ? <ConversaDoResidente key={conversaResidente} nome={conversaResidente} /> : chatCanvas
          : activeFeature === 'providers'
            ? <ProvidersView />
            : activeFeature === 'usage'
              ? <UsageView />
              : activeFeature === 'domains'
                ? <DomainsView />
                : activeFeature === 'skills'
                  ? <SkillsView />
                  : activeFeature === 'traces'
                    ? <TracesView />
                    : activeFeature === 'evals'
                      ? <EvalsView />
                    : activeFeature === 'tasks'
                      ? <TasksView />
                      : activeFeature === 'schedules'
                        ? <SchedulesView onResidente={nome => { setResidenteAberto(atual => ({ nome, vez: atual.vez + 1 })); setActiveFeature('hq'); }} />
                        : activeFeature === 'artifacts'
                          ? <ArtifactsView />
                        : activeFeature === 'context'
                          ? <ContextEngineView />
                          : activeFeature === 'mcp'
                            ? <ToolsCatalogView />
                            : activeFeature === 'diagnostics'
                              ? <DiagnosticsView />
                            : activeFeature === 'memory'
                              ? <MemoryView />
                            : activeFeature === 'robinbandit'
                              ? <RobinBanditView />
                            : activeFeature === 'harness'
                              ? <HarnessView />
                            : activeFeature === 'mutation'
                              ? <MutationView />
            : <MigrationNotice featureId={activeFeature} />}</Suspense>
      </main>

      <WorkbenchPanel />
      <OperationsDrawer />
      {isSettingsOpen && <Suspense fallback={<div className="fixed inset-0 z-[70] bg-canvas"><LoadingSurface /></div>}>
        <FullSettingsView
          initialSection={settingsSection}
          onClose={() => setIsSettingsOpen(false)}
          onNavigate={feature => {
            setIsSettingsOpen(false);
            selectFeature(feature);
          }}
        />
      </Suspense>}
    </div>
  );
};
