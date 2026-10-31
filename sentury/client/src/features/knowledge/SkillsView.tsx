import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { BookOpen, Check, Edit3, Pin, Plus, RefreshCw, Save, Search, Sparkles, Trash2, Upload, X } from 'lucide-react';
import { z } from 'zod';
import { renderMarkdown } from '../../domain/markdown';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const SkillSchema = z.object({
  name: z.string(), description: z.string(), category: z.string().default(''), family: z.string().default(''),
  priority: z.union([z.string(), z.number()]).optional(), tags: z.array(z.string()).default([]), tools_used: z.array(z.string()).default([]),
  telemetry: z.record(z.string(), z.unknown()).nullable().optional(),
  removivel: z.boolean().default(false),
}).passthrough();
const DetailSchema = SkillSchema.extend({ body: z.string(), version: z.string().optional(), available_references: z.array(z.string()).default([]) });
type Skill = z.infer<typeof SkillSchema>;
type Detail = z.infer<typeof DetailSchema>;

export const SkillsView: React.FC = () => {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [query, setQuery] = useState('');
  const [detail, setDetail] = useState<Detail | null>(null);
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newContent, setNewContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const configure = () => { const config = getRuntimeConfig(); apiClient.setBaseUrl(config.apiUrl); };
  const load = useCallback(async () => {
    configure(); setLoading(true); setError('');
    try { const result = z.object({ skills: z.array(SkillSchema) }).parse(await apiClient.get('/sentury/skills', { headers: authHeaders() })); setSkills(result.skills); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const filtered = useMemo(() => skills.filter(skill => `${skill.name} ${skill.description} ${skill.family} ${skill.tags.join(' ')}`.toLowerCase().includes(query.toLowerCase())), [skills, query]);
  const openSkill = async (name: string) => {
    configure(); setError(''); setEditing(false);
    try { const loaded = DetailSchema.parse(await apiClient.get(`/sentury/skills/${encodeURIComponent(name)}`, { headers: authHeaders() })); setDetail(loaded); setDraft(loaded.body); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  };
  const saveDetail = async () => {
    if (!detail || !draft.trim()) return; setSaving(true); setError('');
    try { await apiClient.post(`/sentury/skills/${encodeURIComponent(detail.name)}`, { content: draft }, { headers: authHeaders() }); setDetail({ ...detail, body: draft }); setEditing(false); setNotice(`/${detail.name} atualizada.`); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setSaving(false); }
  };
  const togglePin = async () => {
    if (!detail) return; const pinned = !Boolean(detail.telemetry?.pinned); setSaving(true); setError('');
    try { await apiClient.post(`/sentury/skills/${encodeURIComponent(detail.name)}/pin`, { pinned }, { headers: authHeaders() }); setDetail({ ...detail, telemetry: { ...(detail.telemetry || {}), pinned } }); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setSaving(false); }
  };
  const createSkill = async () => {
    if (!newName.trim() || !newContent.trim()) return; configure(); setSaving(true); setError('');
    try { const response = z.object({ name: z.string() }).passthrough().parse(await apiClient.post('/sentury/skills', { name: newName, content: newContent }, { headers: authHeaders() })); setCreating(false); setNewName(''); setNewContent(''); setNotice(`/${response.name} criada.`); await load(); await openSkill(response.name); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setSaving(false); }
  };
  const [confirmarCuradoria, setConfirmarCuradoria] = useState(false);
  const [removendo, setRemovendo] = useState<string | null>(null);
  const [importando, setImportando] = useState(false);
  const inputPacoteRef = useRef<HTMLInputElement>(null);

  const removerSkill = async (nome: string) => {
    setSaving(true);
    setError('');
    try {
      await apiClient.delete(`/sentury/skills/${encodeURIComponent(nome)}`, { headers: authHeaders() });
      setNotice(`/${nome} removida (arquivada no disco).`);
      setDetail(null);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(false);
      setRemovendo(null);
    }
  };

  // Skill baixada de fora: o SKILL.md manda, e os demais arquivos do pacote
  // viram os scripts de apoio dela.
  const importarPacote = async (arquivos: FileList | null) => {
    const lista = Array.from(arquivos || []);
    if (!lista.length) return;
    setImportando(true);
    setError('');
    try {
      const lidos = await Promise.all(lista.map(async arquivo => ({
        caminho: (arquivo.webkitRelativePath || arquivo.name).split('/').slice(1).join('/') || arquivo.name,
        nome: arquivo.name,
        conteudo: await arquivo.text(),
      })));
      const principal = lidos.find(item => /(^|\/)SKILL\.md$/i.test(item.caminho) || /^SKILL\.md$/i.test(item.nome));
      if (!principal) {
        setError('O pacote precisa conter um SKILL.md.');
        return;
      }
      const raiz = lista[0].webkitRelativePath?.split('/')[0] || '';
      const nome = (raiz || principal.nome.replace(/\.md$/i, '')).toLowerCase().replace(/\s+/g, '-');
      const apoio = lidos.filter(item => item !== principal && item.caminho);
      const resposta = z.object({ name: z.string() }).passthrough().parse(
        await apiClient.post('/sentury/skills/import', {
          name: nome,
          content: principal.conteudo,
          arquivos: apoio.map(item => ({ caminho: item.caminho, conteudo: item.conteudo })),
        }, { headers: authHeaders() }),
      );
      setNotice(`/${resposta.name} importada${apoio.length ? ` com ${apoio.length} arquivo(s)` : ''}.`);
      await load();
      await openSkill(resposta.name);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setImportando(false);
    }
  };

  const runCurator = async () => {
    configure(); setLoading(true); setError('');
    try { await apiClient.post('/sentury/skills/curator/run', {}, { headers: authHeaders() }); setNotice('Curadoria concluída.'); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setLoading(false); }
  };

  return <section className="relative h-full overflow-y-auto px-7 py-7"><div className="mx-auto max-w-6xl">
    <header className="flex items-start justify-between gap-4"><div><p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Capacidades procedurais</p><h1 className="mt-2 text-2xl font-semibold">Skills</h1><p className="mt-1 text-sm text-zinc-500">Descoberta, edição, proteção, curadoria e conteúdo real de cada SKILL.md.</p></div><div className="flex gap-2"><button type="button" onClick={() => { setCreating(true); setDetail(null); }} className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-white"><Plus className="h-3.5 w-3.5" />Nova skill</button><input ref={inputPacoteRef} type="file" multiple hidden onChange={event => { void importarPacote(event.target.files); event.target.value = ''; }} /><button type="button" disabled={importando} onClick={() => inputPacoteRef.current?.click()} className="inline-flex items-center gap-2 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs disabled:opacity-40" title="Selecione o SKILL.md e os arquivos de apoio"><Upload className="h-3.5 w-3.5" />{importando ? 'Importando…' : 'Importar'}</button><button type="button" onClick={() => setConfirmarCuradoria(true)} className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs">Curadoria</button><button type="button" onClick={() => void load()} className="rounded-lg border border-stone-300 bg-white p-2"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /></button></div></header>
    <label className="mt-6 flex max-w-xl items-center gap-2 rounded-xl border border-stone-300 bg-white px-3 py-2.5"><Search className="h-4 w-4 text-zinc-400" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar por nome, família, tag ou descrição" className="w-full bg-transparent text-sm outline-none" /></label>
    {error && <p className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p>}{notice && <p className="mt-5 flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700"><Check className="h-3.5 w-3.5" />{notice}</p>}
    <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{filtered.map(skill => { const telemetry = skill.telemetry || {}; const uses = typeof telemetry.uses === 'number' ? telemetry.uses : typeof telemetry.use_count === 'number' ? telemetry.use_count : null; return <button key={skill.name} type="button" onClick={() => void openSkill(skill.name)} className="flex flex-col items-stretch justify-start rounded-xl border border-stone-200 bg-white/80 p-4 text-left transition-all hover:-translate-y-0.5 hover:border-gold hover:shadow-sm"><div className="flex items-start gap-3"><span className="rounded-lg bg-gold-soft p-2 text-gold-ink"><Sparkles className="h-4 w-4" /></span><span className="min-w-0"><strong className="block truncate text-sm">/{skill.name}</strong><span className="mt-1 line-clamp-3 text-xs leading-5 text-zinc-500" title={skill.description}>{skill.description}</span></span></div><div className="mt-auto flex flex-wrap gap-1.5 pt-3"><span className="rounded-full bg-stone-100 px-2 py-1 text-[10px] text-zinc-600">{skill.family || skill.category || 'geral'}</span>{uses != null && <span className="rounded-full bg-stone-100 px-2 py-1 text-[10px] text-zinc-600">{uses} usos</span>}{Boolean(telemetry.pinned) && <span className="rounded-full bg-gold-soft px-2 py-1 text-[10px] text-gold-ink"><Pin className="mr-1 inline h-2.5 w-2.5" />fixada</span>}</div></button>; })}</div>{!loading && !filtered.length && <p className="mt-6 text-sm text-zinc-500">Nenhuma skill corresponde à busca.</p>}
  </div>
  {detail && <aside className="fixed inset-y-0 right-0 z-50 flex w-[min(48rem,calc(100vw-3.5rem))] animate-[sentury-workbench-in_220ms_ease-out] flex-col border-l border-stone-200 bg-[#fffdf8] shadow-2xl"><header className="flex items-center gap-3 border-b border-stone-200 px-5 py-4"><BookOpen className="h-4 w-4 text-gold-hover" /><div className="min-w-0 flex-1"><h2 className="truncate text-sm font-semibold">/{detail.name}</h2><p className="text-[10px] text-zinc-500">{detail.family} · {detail.version || 'versão não informada'}</p></div><button type="button" disabled={saving} onClick={() => void togglePin()} className={`rounded-md p-2 hover:bg-stone-100 ${detail.telemetry?.pinned ? 'text-gold-hover' : 'text-zinc-500'}`} title={detail.telemetry?.pinned ? 'Desafixar' : 'Fixar'}><Pin className={`h-4 w-4 ${detail.telemetry?.pinned ? 'fill-current' : ''}`} /></button><button type="button" onClick={() => setEditing(value => !value)} className="rounded-md p-2 text-zinc-500 hover:bg-stone-100" title="Editar SKILL.md"><Edit3 className="h-4 w-4" /></button><button type="button" disabled={!detail.removivel} onClick={() => setRemovendo(detail.name)} className="rounded-md p-2 text-zinc-500 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-zinc-500" title={detail.removivel ? 'Remover skill' : 'Faz parte da instalação: só skills que você criou ou importou podem ser removidas'}><Trash2 className="h-4 w-4" /></button><button type="button" onClick={() => setDetail(null)} className="rounded-md p-2 hover:bg-stone-100"><X className="h-4 w-4" /></button></header><div className="flex-1 overflow-y-auto p-6"><p className="mb-5 text-sm leading-6 text-zinc-600">{detail.description}</p>{editing ? <><textarea value={draft} onChange={event => setDraft(event.target.value)} spellCheck={false} className="min-h-[65vh] w-full rounded-xl border border-stone-300 bg-white p-4 font-mono text-xs leading-6 outline-none focus:border-gold" /><div className="mt-3 flex justify-end gap-2"><button type="button" onClick={() => { setDraft(detail.body); setEditing(false); }} className="rounded-lg border border-stone-300 px-3 py-2 text-xs">Descartar</button><button type="button" disabled={saving || !draft.trim()} onClick={() => void saveDetail()} className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"><Save className="h-3.5 w-3.5" />Salvar</button></div></> : <div className="bubble__md prose prose-sm max-w-none" dangerouslySetInnerHTML={{ __html: renderMarkdown(detail.body) }} />}</div></aside>}
  {creating && <aside className="fixed inset-y-0 right-0 z-50 flex w-[min(42rem,calc(100vw-3.5rem))] animate-[sentury-workbench-in_220ms_ease-out] flex-col border-l border-stone-200 bg-[#fffdf8] shadow-2xl"><header className="flex items-center justify-between border-b border-stone-200 px-5 py-4"><div><h2 className="text-sm font-semibold">Nova skill</h2><p className="text-[10px] text-zinc-500">O conteúdo será salvo como SKILL.md no diretório de skills do usuário.</p></div><button type="button" onClick={() => setCreating(false)} className="rounded-md p-2 hover:bg-stone-100"><X className="h-4 w-4" /></button></header><div className="flex-1 space-y-4 overflow-y-auto p-6"><label className="block"><span className="text-xs font-semibold">Nome</span><input value={newName} onChange={event => setNewName(event.target.value)} placeholder="minha-skill" className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-gold" /></label><label className="block"><span className="text-xs font-semibold">Conteúdo completo do SKILL.md</span><textarea value={newContent} onChange={event => setNewContent(event.target.value)} placeholder={'---\nname: minha-skill\ndescription: ...\n---\n\n# Instruções'} spellCheck={false} className="mt-1.5 min-h-[60vh] w-full rounded-xl border border-stone-300 bg-white p-4 font-mono text-xs leading-6 outline-none focus:border-gold" /></label></div><footer className="flex justify-end border-t border-stone-200 p-4"><button type="button" disabled={saving || !newName.trim() || !newContent.trim()} onClick={() => void createSkill()} className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white disabled:opacity-35"><Save className="h-3.5 w-3.5" />Criar skill</button></footer></aside>}
    <ConfirmDialog
    open={confirmarCuradoria}
    title="Rodar a curadoria de skills?"
    description="A curadoria arquiva skills inativas criadas pelo agente. Skills fixadas e criadas por voce nao sao tocadas."
    confirmLabel="Rodar curadoria"
    onCancel={() => setConfirmarCuradoria(false)}
    onConfirm={() => { setConfirmarCuradoria(false); void runCurator(); }}
  />
    <ConfirmDialog
    open={Boolean(removendo)}
    title={`Remover /${removendo || ''}?`}
    description="A skill sai da biblioteca e vai para .arquivadas no disco, entao da para recuperar depois. Skills que vem com o Sentury nao podem ser removidas."
    confirmLabel="Remover"
    onCancel={() => setRemovendo(null)}
    onConfirm={() => { const alvo = removendo; if (alvo) void removerSkill(alvo); }}
  />
  </section>;
};
