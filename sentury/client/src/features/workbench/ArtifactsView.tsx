import React, { useEffect, useMemo, useState } from 'react';
import { BarChart3, Braces, FileText, ListChecks, Route, Search, Table2 } from 'lucide-react';
import { useSessionStore } from '../../stores/session-store';
import { useWorkbenchStore } from '../../stores/workbench-store';
import { adotarIdentidadeDaMaquina, authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { referenciaDeArtefato } from '../../domain/artifact-remoto';

/**
 * A biblioteca busca metadados de todas as conversas no servidor. O corpo
 * de cada artefato só é carregado quando a pessoa o abre.
 */
type ArtefatoRemoto = {
  id: string; session_id: string; session_title: string;
  titulo: string; tipo: string; criado_em: number;
};

type Item = {
  id: string; sessionId: string; sessionTitle: string;
  title: string; type: string; createdAt: number; local: boolean;
};

const icons = { table: Table2, chart: BarChart3, code: Braces, markdown: FileText, file: FileText,
  // Checklist para o que fica, rota para o caminho de um turno so.
  workflow: ListChecks, trilha: Route } as const;

export const ArtifactsView: React.FC = () => {
  const [query, setQuery] = useState('');
  const [sessionFilter, setSessionFilter] = useState('all');
  const artifacts = useWorkbenchStore(state => state.artifacts);
  const openWorkbench = useWorkbenchStore(state => state.openWorkbench);
  const addArtifact = useWorkbenchStore(state => state.addArtifact);
  const sessions = useSessionStore(state => state.sessions);
  const [remotos, setRemotos] = useState<ArtefatoRemoto[]>([]);

  useEffect(() => {
    let vivo = true;
    void (async () => {
      try {
        apiClient.setBaseUrl(getRuntimeConfig().apiUrl);
        const userId = await adotarIdentidadeDaMaquina();
        const resposta = await apiClient.get<{ artefatos?: ArtefatoRemoto[] }>(
          `/sentury/artefatos?user_id=${encodeURIComponent(userId)}`,
          { headers: authHeaders() },
        );
        if (vivo) setRemotos(resposta?.artefatos || []);
      } catch {
        // A biblioteca degrada para o que este client tem, em vez de sumir.
      }
    })();
    return () => { vivo = false; };
  }, []);

  const todos = useMemo<Item[]>(() => {
    const locais: Item[] = artifacts.map(a => ({
      id: a.id, sessionId: a.sessionId,
      sessionTitle: sessions.find(s => s.id === a.sessionId)?.title || a.sessionId,
      title: a.title, type: a.type === 'file' ? a.formato : a.type,
      createdAt: new Date(a.createdAt).getTime(), local: true,
    }));
    // O que esta aberto agora ganha do que veio do servidor: mesmo id, um
    // deles ja tem o conteudo em memoria e abre sem ida e volta.
    const vistos = new Set(locais.map(item => item.id));
    const remotosNovos: Item[] = remotos
      .filter(a => !vistos.has(a.id))
      .map(a => ({
        id: a.id, sessionId: a.session_id, sessionTitle: a.session_title,
        title: a.titulo, type: a.tipo, createdAt: (a.criado_em || 0) * 1000, local: false,
      }));
    return [...locais, ...remotosNovos].sort((a, b) => b.createdAt - a.createdAt);
  }, [artifacts, remotos, sessions]);

  const visible = useMemo(() => todos.filter(item =>
    (sessionFilter === 'all' || item.sessionId === sessionFilter)
    && `${item.title} ${item.type}`.toLowerCase().includes(query.trim().toLowerCase()),
  ), [todos, query, sessionFilter]);

  const abrir = (item: Item) => {
    if (!item.local) addArtifact(referenciaDeArtefato(item));
    openWorkbench(item.id);
  };

  return (
    <section className="h-full overflow-y-auto px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <header><p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Saídas reutilizáveis</p><h1 className="mt-2 text-2xl font-semibold">Artefatos</h1><p className="mt-1 text-sm text-zinc-500">Tudo que o Sentury produziu, de todas as suas conversas — não só das que estão abertas agora.</p></header>
        <div className="mt-6 flex flex-wrap gap-2">
          <label className="flex min-w-64 flex-1 items-center gap-2 rounded-xl border border-stone-300 bg-white px-3 py-2.5"><Search className="h-4 w-4 text-zinc-400" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar artefato" className="w-full bg-transparent text-sm outline-none" /></label>
          <select value={sessionFilter} onChange={event => setSessionFilter(event.target.value)} className="rounded-xl border border-stone-300 bg-white px-3 text-xs text-zinc-700"><option value="all">Todas as conversas</option>{sessions.map(session => <option key={session.id} value={session.id}>{session.title}</option>)}</select>
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map(artifact => { const Icon = icons[artifact.type as keyof typeof icons] || FileText; return <button key={artifact.id} type="button" onClick={() => abrir(artifact)} className="group rounded-2xl border border-stone-200 bg-white/80 p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-gold"><div className="flex items-start gap-3"><span className="rounded-lg bg-stone-100 p-2 text-gold-hover"><Icon className="h-4 w-4" /></span><div className="min-w-0 flex-1"><strong className="block truncate text-sm">{artifact.title}</strong><span className="mt-1 block truncate text-[10px] text-zinc-500">{artifact.sessionTitle}</span></div><span className="rounded-full border border-stone-200 px-2 py-1 text-[9px] font-bold uppercase text-zinc-500">{artifact.type}</span></div><time className="mt-5 block text-[10px] text-zinc-400">{artifact.createdAt ? new Date(artifact.createdAt).toLocaleString() : ''}</time></button>; })}
        </div>
        {!visible.length && <div className="mt-8 rounded-2xl border border-dashed border-stone-300 p-10 text-center"><FileText className="mx-auto h-6 w-6 text-zinc-300" /><p className="mt-3 text-sm font-medium">Nenhum artefato carregado</p><p className="mt-1 text-xs text-zinc-500">Abra uma conversa com tabela, gráfico ou anexo para a biblioteca indexá-lo sem fabricar conteúdo.</p></div>}
      </div>
    </section>
  );
};
