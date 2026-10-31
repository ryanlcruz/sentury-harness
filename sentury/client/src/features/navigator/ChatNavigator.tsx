import React, { useMemo, useState } from 'react';
import { useSessionStore } from '../../stores/session-store';
import { SessionRuntimeStatus } from '../../contracts/domain/session';
import { StatusBadge } from '../../components/StatusBadge';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { Plus, ChevronDown, ChevronRight, MessageSquare, Folder, FolderPlus, MoreVertical, Search, Pin, Pencil, Check, X, Trash2 } from 'lucide-react';
import { useHarnessStore } from '../../stores/harness-store';
import { EquipeNaLista } from '../residentes/EquipeNaLista';
import { useHQ } from '../residentes/useEsperando';

const POR_PASTA = 8;

// A conversa que parou esperando a pessoa diz por quê, sem precisar abrir.
const AVISO_DA_ESPERA: Partial<Record<SessionRuntimeStatus, string>> = {
  awaiting_approval: 'Precisa da sua aprovação',
  awaiting_user: 'Tem uma pergunta para você',
  interrupted: 'Parou no meio: continuar?',
};

interface ChatNavigatorProps {
  onNewChat?: () => void;
  onSessionSelected?: () => void;
  residenteSelecionado?: string | null;
  onResidenteSelected?: (nome: string) => void;
  mesaSelecionada?: boolean;
  onMesaSelected?: () => void;
  onAbrirHQ?: () => void;
}

type Aba = 'sentury' | 'equipe';
const CHAVE_DA_ABA = 'sentury.conversas.aba';

export const ChatNavigator: React.FC<ChatNavigatorProps> = ({ onNewChat, onSessionSelected, residenteSelecionado, onResidenteSelected, mesaSelecionada, onMesaSelected, onAbrirHQ }) => {
  // Conversa de residente aberta: o painel abre na Equipe; senão, na última aba usada.
  const [aba, setAba] = useState<Aba>(() => {
    if (residenteSelecionado || mesaSelecionada) return 'equipe';
    try { return localStorage.getItem(CHAVE_DA_ABA) === 'equipe' ? 'equipe' : 'sentury'; } catch { return 'sentury'; }
  });
  const escolherAba = (nova: Aba) => {
    setAba(nova);
    try { localStorage.setItem(CHAVE_DA_ABA, nova); } catch { /* vale só nesta visita */ }
  };
  const hq = useHQ();
  const esperandoNaEquipe = hq.esperando.length;
  const {
    workspaces,
    sessions,
    activeSessionId,
    setActiveSession,
    createSession,
    activeWorkspaceId,
    isLoading,
    loadError,
    renameSession,
    deleteSession,
    toggleSessionPinned,
    createFolder,
    renameFolder,
    deleteFolder,
    toggleFolder,
    moveSessionToFolder,
  } = useSessionStore();
  const harnessStatus = useHarnessStore(state => state.status);
  const [query, setQuery] = useState('');
  const [apagando, setApagando] = useState<{ id: string; title: string } | null>(null);
  const [menuSessionId, setMenuSessionId] = useState<string | null>(null);
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState('');
  const [novaPasta, setNovaPasta] = useState<string | null>(null);
  const [renomeandoPasta, setRenomeandoPasta] = useState<string | null>(null);
  const [nomePasta, setNomePasta] = useState('');
  const [apagandoPasta, setApagandoPasta] = useState<{ id: string; nome: string } | null>(null);
  const [arrastando, setArrastando] = useState<string | null>(null);
  const [pastaAlvo, setPastaAlvo] = useState<string | null>(null);
  // Uma lista longa empurra as outras pastas para fora da tela.
  const [mostrandoTudo, setMostrandoTudo] = useState<Record<string, boolean>>({});
  const visibleSessions = useMemo(() => sessions
    .filter(session => session.title.toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => Number(b.pinned) - Number(a.pinned)), [query, sessions]);

  const handleNewChat = () => {
    if (activeWorkspaceId) {
      createSession(activeWorkspaceId, 'Nova Análise');
      onNewChat?.();
    }
  };

  return (
    <aside className="z-20 flex w-72 shrink-0 select-none flex-col border-r border-stone-200 bg-[#f2f0e9] text-zinc-700">
      {/* Header */}
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-stone-200 px-4">
        <div><span className="text-[11px] font-bold uppercase tracking-[0.16em] text-zinc-800">Conversas</span><p className="mt-0.5 text-[10px] text-zinc-500">{aba === 'sentury' ? 'Organize por pastas' : 'Uma conversa por residente'}</p></div>
        {aba === 'sentury' ? <button
          onClick={handleNewChat}
          className="inline-flex items-center gap-1.5 rounded-md bg-zinc-900 px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-zinc-800"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>Novo</span>
        </button> : null}
      </div>

      <div role="tablist" aria-label="De quem são as conversas" className="mx-3 mt-3 grid grid-cols-2 gap-1 rounded-lg border border-stone-200 bg-[#e9e6dc] p-1">
        {([['sentury', 'Sentury'], ['equipe', 'Equipe']] as const).map(([id, nome]) => (
          <button key={id} type="button" role="tab" aria-selected={aba === id} onClick={() => escolherAba(id)}
            className={`relative h-8 rounded-md text-xs transition ${aba === id ? 'bg-white font-semibold text-zinc-900 shadow-sm' : 'text-zinc-600 hover:text-zinc-900'}`}>
            {nome}
            {id === 'equipe' && esperandoNaEquipe ? (
              <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-gold px-1 text-[10px] font-bold text-zinc-950"
                aria-label={`${esperandoNaEquipe} esperando você`}>{esperandoNaEquipe}</span>
            ) : null}
          </button>
        ))}
      </div>

      {aba === 'equipe' ? (
        <EquipeNaLista selecionado={residenteSelecionado} onSelecionar={nome => onResidenteSelected?.(nome)}
          mesaSelecionada={mesaSelecionada} onMesa={onMesaSelected} onAbrirHQ={onAbrirHQ} />
      ) : (<>

      <div className="mx-3 mt-3 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-zinc-400">Pastas</span>
        <button
          type="button"
          onClick={() => { setNovaPasta(''); setNomePasta(''); }}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] font-medium text-zinc-500 hover:bg-white hover:text-zinc-800"
          title="Nova pasta"
        >
          <FolderPlus className="h-3.5 w-3.5" />Nova pasta
        </button>
      </div>

      {novaPasta !== null && (
        <form
          className="mx-3 mt-1.5 flex items-center gap-1"
          onSubmit={event => { event.preventDefault(); createFolder(nomePasta); setNovaPasta(null); setNomePasta(''); }}
        >
          <input
            autoFocus
            value={nomePasta}
            onChange={event => setNomePasta(event.target.value)}
            placeholder="Nome da pasta"
            className="min-w-0 flex-1 rounded border border-gold bg-white px-2 py-1 text-xs outline-none"
          />
          <button type="submit" className="text-emerald-700" aria-label="Criar pasta"><Check className="h-3.5 w-3.5" /></button>
          <button type="button" onClick={() => setNovaPasta(null)} className="text-zinc-400" aria-label="Cancelar"><X className="h-3.5 w-3.5" /></button>
        </form>
      )}

      <label className="mx-3 mt-3 flex items-center gap-2 rounded-lg border border-stone-200 bg-white/75 px-2.5 py-2 focus-within:border-gold">
        <Search className="h-3.5 w-3.5 text-zinc-400" />
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar conversas" className="w-full bg-transparent text-xs outline-none placeholder:text-zinc-400" />
      </label>

      {/* Workspaces and Sessions List */}
      <div className="flex-1 space-y-4 overflow-y-auto p-3">
        {isLoading && <p className="px-2 py-3 text-xs text-zinc-500">Carregando conversas…</p>}
        {loadError && <p className="mx-1 rounded-lg border border-red-200 bg-red-50 p-2 text-[11px] leading-4 text-red-700">Não foi possível sincronizar. As conversas locais continuam disponíveis.</p>}
        {workspaces.map((ws) => {
          const todas = visibleSessions.filter(s => s.workspaceId === ws.id);
          const aberta = mostrandoTudo[ws.id] || Boolean(query.trim());
          const wsSessions = aberta ? todas : todas.slice(0, POR_PASTA);
          const escondidas = todas.length - wsSessions.length;

          return (
            <div
              key={ws.id}
              className={`space-y-1.5 rounded-lg transition-colors ${pastaAlvo === ws.id ? 'bg-gold-soft/60' : ''}`}
              onDragOver={event => { if (arrastando) { event.preventDefault(); setPastaAlvo(ws.id); } }}
              onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setPastaAlvo(atual => (atual === ws.id ? null : atual)); }}
              onDrop={event => {
                event.preventDefault();
                const id = event.dataTransfer.getData('text/plain') || arrastando;
                setPastaAlvo(null);
                setArrastando(null);
                if (id) moveSessionToFolder(id, ws.id);
              }}
            >
              {/* Workspace Header */}
              <div className="group flex items-center justify-between px-2 py-1 text-[10px] font-bold uppercase tracking-[0.13em] text-zinc-500 transition-colors hover:text-zinc-800">
                {renomeandoPasta === ws.id ? (
                  <form
                    className="flex min-w-0 flex-1 items-center gap-1"
                    onSubmit={event => { event.preventDefault(); renameFolder(ws.id, nomePasta); setRenomeandoPasta(null); }}
                  >
                    <input
                      autoFocus
                      value={nomePasta}
                      onChange={event => setNomePasta(event.target.value)}
                      className="min-w-0 flex-1 rounded border border-gold bg-white px-1.5 py-0.5 text-[11px] normal-case tracking-normal outline-none"
                    />
                    <button type="submit" className="text-emerald-700" aria-label="Salvar nome"><Check className="h-3.5 w-3.5" /></button>
                    <button type="button" onClick={() => setRenomeandoPasta(null)} className="text-zinc-400" aria-label="Cancelar"><X className="h-3.5 w-3.5" /></button>
                  </form>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => toggleFolder(ws.id)}
                      className="flex min-w-0 flex-1 items-center gap-1.5 text-left uppercase tracking-[0.13em]"
                    >
                      {ws.recolhida ? <ChevronRight className="h-3.5 w-3.5 text-zinc-400" /> : <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />}
                      <Folder className="h-3.5 w-3.5 text-gold-hover" />
                      <span className="truncate">{ws.name}</span>
                    </button>
                    <span className="flex items-center gap-1">
                      {ws.id !== 'inbox' && (
                        <>
                          <button
                            type="button"
                            onClick={() => { setRenomeandoPasta(ws.id); setNomePasta(ws.name); }}
                            className="p-0.5 opacity-0 transition-opacity hover:text-zinc-900 group-hover:opacity-100"
                            aria-label={`Renomear ${ws.name}`}
                          >
                            <Pencil className="h-3 w-3" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setApagandoPasta({ id: ws.id, nome: ws.name })}
                            className="p-0.5 opacity-0 transition-opacity hover:text-red-600 group-hover:opacity-100"
                            aria-label={`Apagar ${ws.name}`}
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </>
                      )}
                      <span className="text-[10px] font-normal text-zinc-400">
                        {todas.length} {todas.length === 1 ? 'chat' : 'chats'}
                      </span>
                    </span>
                  </>
                )}
              </div>

              {/* Sessions in this Workspace */}
              <div className={`space-y-1 pl-1 ${ws.recolhida ? 'hidden' : ''}`}>
                {arrastando && pastaAlvo === ws.id && !wsSessions.some(item => item.id === arrastando) ? (
                  <p className="rounded-lg border border-dashed border-gold px-3 py-2 text-[10px] text-gold-ink">Soltar em {ws.name}</p>
                ) : null}
                {wsSessions.map((session) => {
                  const isActive = session.id === activeSessionId;

                  return (
                    <div
                      key={session.id}
                      draggable
                      onDragStart={event => { setArrastando(session.id); event.dataTransfer.setData('text/plain', session.id); }}
                      onDragEnd={() => { setArrastando(null); setPastaAlvo(null); }}
                      onClick={() => {
                        setActiveSession(session.id);
                        onSessionSelected?.();
                      }}
                      className={`group relative cursor-pointer rounded-lg py-2.5 pl-3 pr-2 transition-all ${
                        isActive
                          ? 'bg-white shadow-sm before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full before:bg-gold'
                          : 'hover:bg-white/65'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0 mt-0.5">
                          <MessageSquare className={`h-3.5 w-3.5 shrink-0 ${isActive ? 'text-gold-hover' : 'text-zinc-400'}`} />
                          {renamingSessionId === session.id ? <form className="flex min-w-0 flex-1 items-center gap-1" onClick={event => event.stopPropagation()} onSubmit={event => { event.preventDefault(); void renameSession(session.id, titleDraft); setRenamingSessionId(null); setMenuSessionId(null); }}><input autoFocus value={titleDraft} onChange={event => setTitleDraft(event.target.value)} className="min-w-0 flex-1 rounded border border-gold bg-white px-1.5 py-0.5 text-xs outline-none" /><button type="submit" className="text-emerald-700"><Check className="h-3.5 w-3.5" /></button><button type="button" onClick={() => setRenamingSessionId(null)} className="text-zinc-400"><X className="h-3.5 w-3.5" /></button></form> : <span className="truncate text-xs font-medium text-zinc-800">{session.title}</span>}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          {session.pinned && <Pin className="h-3 w-3 fill-gold text-gold-hover" />}
                          <StatusBadge status={session.runtimeStatus} />
                          <button
                            onClick={(e) => {
                              e.stopPropagation(); setMenuSessionId(current => current === session.id ? null : session.id);
                            }}
                            className="p-0.5 opacity-0 transition-opacity hover:text-zinc-900 group-hover:opacity-100"
                            title="Opções da sessão"
                          >
                            <MoreVertical className="w-3 h-3" />
                          </button>
                        </div>
                      </div>

                      {AVISO_DA_ESPERA[session.runtimeStatus] && (
                        <p className="mt-0.5 truncate pl-[22px] text-[10.5px] font-medium text-gold-ink">
                          {AVISO_DA_ESPERA[session.runtimeStatus]}
                        </p>
                      )}

                      {session.tags.length > 0 && (
                        <div className="pl-6 mt-1 flex items-center text-[10px] text-zinc-500">
                          <span className="truncate">{session.tags.join(', ')}</span>
                        </div>
                      )}
                      {menuSessionId === session.id && <div onClick={event => event.stopPropagation()} className="absolute right-2 top-9 z-20 w-36 rounded-lg border border-stone-200 bg-white p-1 shadow-lg"><button type="button" onClick={() => { setRenamingSessionId(session.id); setTitleDraft(session.title); }} className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-[11px] hover:bg-stone-100"><Pencil className="h-3 w-3" />Renomear</button><button type="button" onClick={() => { toggleSessionPinned(session.id); setMenuSessionId(null); }} className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-[11px] hover:bg-stone-100"><Pin className="h-3 w-3" />{session.pinned ? 'Desafixar' : 'Fixar'}</button><button type="button" onClick={() => { setApagando({ id: session.id, title: session.title }); setMenuSessionId(null); }} className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-[11px] text-red-700 hover:bg-red-50"><Trash2 className="h-3 w-3" />Apagar</button></div>}
                    </div>
                  );
                })}
                {escondidas > 0 && (
                  <button
                    type="button"
                    onClick={() => setMostrandoTudo(atual => ({ ...atual, [ws.id]: true }))}
                    className="w-full rounded-lg px-3 py-2 text-left text-[11px] text-zinc-500 transition-colors hover:bg-white/70 hover:text-zinc-800"
                  >
                    Ver mais {escondidas}
                  </button>
                )}
                {aberta && todas.length > POR_PASTA && !query.trim() && (
                  <button
                    type="button"
                    onClick={() => setMostrandoTudo(atual => ({ ...atual, [ws.id]: false }))}
                    className="w-full rounded-lg px-3 py-2 text-left text-[11px] text-zinc-500 transition-colors hover:bg-white/70 hover:text-zinc-800"
                  >
                    Ver menos
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {!isLoading && sessions.length === 0 && !loadError && (
        <p className="px-5 py-3 text-xs leading-5 text-zinc-500">Nenhuma conversa ainda. Crie a primeira quando quiser.</p>
      )}
      </>)}

      {/* Footer Info */}
      <div className="flex items-center justify-between border-t border-stone-200 p-3 text-[11px] text-zinc-500">
        <span>Sentury</span>
        <span className={harnessStatus === 'online' ? 'font-medium text-emerald-700' : harnessStatus === 'busy' ? 'font-medium text-gold-ink' : 'font-medium text-zinc-500'}>
          {harnessStatus === 'online' ? 'Conectado' : harnessStatus === 'busy' ? 'Executando' : 'Offline'}
        </span>
      </div>
      <ConfirmDialog
    open={apagando !== null}
    destructive
    title="Apagar esta conversa?"
    description={apagando ? `"${apagando.title}" sai da lista e do historico no servidor. Nao da para desfazer.` : ''}
    confirmLabel="Apagar"
    onCancel={() => setApagando(null)}
    onConfirm={() => { if (apagando) void deleteSession(apagando.id); setApagando(null); }}
  />
      <ConfirmDialog
    open={apagandoPasta !== null}
    title={`Apagar a pasta ${apagandoPasta?.nome || ''}?`}
    description="So a pasta e desfeita. As conversas que estavam nela voltam para a raiz."
    confirmLabel="Apagar pasta"
    onCancel={() => setApagandoPasta(null)}
    onConfirm={() => { if (apagandoPasta) deleteFolder(apagandoPasta.id); setApagandoPasta(null); }}
  />
  </aside>
  );
};
