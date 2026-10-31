import React, { useCallback, useEffect, useState } from 'react';
import { Check, Package, Plug, Plus, RefreshCw, Server, Terminal, Trash2, TriangleAlert, X } from 'lucide-react';
import { z } from 'zod';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const ServidorSchema = z.object({
  id: z.string(),
  nome: z.string(),
  transporte: z.enum(['stdio', 'http']).catch('stdio'),
  comando: z.string().default(''),
  args: z.array(z.string()).default([]),
  url: z.string().default(''),
  env_vars: z.array(z.string()).default([]),
  ativo: z.boolean().default(true),
  env_presentes: z.record(z.string(), z.boolean()).default({}),
  /* Preenchido quando o servidor vem do pacote do setor ativo. */
  origem: z.string().default(''),
}).passthrough();

const InspecaoSchema = z.object({
  conectado: z.boolean(),
  ms: z.number().optional(),
  erro: z.string().optional(),
  servidor: z.record(z.string(), z.unknown()).optional(),
  tools: z.array(z.object({ nome: z.string(), descricao: z.string().default('') })).default([]),
});

type Servidor = z.infer<typeof ServidorSchema>;
type Inspecao = z.infer<typeof InspecaoSchema>;

interface Rascunho {
  id: string;
  nome: string;
  transporte: 'stdio' | 'http';
  comando: string;
  args: string;
  url: string;
  env_vars: string;
}

const VAZIO: Rascunho = { id: '', nome: '', transporte: 'stdio', comando: '', args: '', url: '', env_vars: '' };

export const McpPanel: React.FC = () => {
  const [servidores, setServidores] = useState<Servidor[]>([]);
  const [config, setConfig] = useState('');
  const [erro, setErro] = useState('');
  const [carregando, setCarregando] = useState(true);
  const [editor, setEditor] = useState<Rascunho | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [inspecoes, setInspecoes] = useState<Record<string, Inspecao | 'carregando'>>({});
  const [removendo, setRemovendo] = useState<Servidor | null>(null);

  const load = useCallback(async () => {
    setCarregando(true);
    setErro('');
    try {
      const dados = z.object({ servidores: z.array(ServidorSchema), config: z.string().default('') })
        .parse(await apiClient.get('/sentury/mcp', { headers: authHeaders() }));
      setServidores(dados.servidores);
      setConfig(dados.config);
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : String(causa));
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const salvar = async () => {
    if (!editor) return;
    setSalvando(true);
    setErro('');
    try {
      await apiClient.post('/sentury/mcp', {
        id: editor.id || undefined,
        nome: editor.nome.trim(),
        transporte: editor.transporte,
        comando: editor.comando.trim(),
        args: editor.args.split(/\s+/).filter(Boolean),
        url: editor.url.trim(),
        env_vars: editor.env_vars.split(/[,\s]+/).filter(Boolean),
      }, { headers: authHeaders() });
      setEditor(null);
      await load();
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : String(causa));
    } finally {
      setSalvando(false);
    }
  };

  const inspecionar = async (servidor: Servidor) => {
    setInspecoes(atual => ({ ...atual, [servidor.id]: 'carregando' }));
    try {
      const dados = InspecaoSchema.parse(
        await apiClient.post(`/sentury/mcp/${encodeURIComponent(servidor.id)}/inspecionar`, {}, { headers: authHeaders() }),
      );
      setInspecoes(atual => ({ ...atual, [servidor.id]: dados }));
    } catch (causa) {
      setInspecoes(atual => ({
        ...atual,
        [servidor.id]: { conectado: false, erro: causa instanceof Error ? causa.message : String(causa), tools: [] },
      }));
    }
  };

  const remover = async (servidor: Servidor) => {
    setRemovendo(null);
    try {
      await apiClient.delete(`/sentury/mcp/${encodeURIComponent(servidor.id)}`, { headers: authHeaders() });
      await load();
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : String(causa));
    }
  };

  return (
    <section className="mt-9 border-t border-stone-200 pt-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Servidores externos</p>
          <h2 className="mt-1 text-lg font-semibold">MCP</h2>
          <p className="mt-1 max-w-2xl text-sm text-zinc-500">
            Ferramentas que vivem fora do Sentury. O registro guarda o nome da variável de ambiente que o
            servidor precisa, nunca o valor.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setEditor({ ...VAZIO })}
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-white"
          >
            <Plus className="h-3.5 w-3.5" />Conectar servidor
          </button>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-stone-300 bg-white p-2"
            aria-label="Atualizar servidores"
          >
            <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {erro ? <p className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">{erro}</p> : null}

      <div className="mt-5 space-y-3">
        {servidores.map(servidor => {
          const inspecao = inspecoes[servidor.id];
          const faltando = Object.entries(servidor.env_presentes).filter(([, presente]) => !presente).map(([nome]) => nome);
          return (
            <article key={servidor.id} className="rounded-xl border border-stone-200 bg-white/85 p-4">
              <div className="flex flex-wrap items-start gap-3">
                <span className="rounded-lg bg-gold-soft p-2 text-gold-ink">
                  {servidor.transporte === 'http' ? <Server className="h-4 w-4" /> : <Terminal className="h-4 w-4" />}
                </span>
                <div className="min-w-48 flex-1">
                  <strong className="block text-sm">{servidor.nome}</strong>
                  <span className="mt-0.5 block truncate font-mono text-[10px] text-zinc-500">
                    {servidor.transporte === 'http' ? servidor.url : [servidor.comando, ...servidor.args].join(' ')}
                  </span>
                  {servidor.origem ? (
                    <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-stone-100 px-1.5 py-0.5 text-[10px] text-zinc-600">
                      <Package className="h-3 w-3" />vem do {servidor.origem}
                    </span>
                  ) : null}
                  {faltando.length ? (
                    <span className="mt-1 inline-flex items-center gap-1 text-[10px] text-amber-700">
                      <TriangleAlert className="h-3 w-3" />falta no ambiente: {faltando.join(', ')}
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <button
                    type="button"
                    onClick={() => void inspecionar(servidor)}
                    className="rounded-lg border border-stone-300 bg-white px-2.5 py-1.5 text-[11px] font-medium hover:border-gold"
                  >
                    {inspecao === 'carregando' ? 'Conectando…' : 'Testar conexão'}
                  </button>
                  {servidor.origem ? null : (
                  <button
                    type="button"
                    onClick={() => setEditor({
                      id: servidor.id,
                      nome: servidor.nome,
                      transporte: servidor.transporte,
                      comando: servidor.comando,
                      args: servidor.args.join(' '),
                      url: servidor.url,
                      env_vars: servidor.env_vars.join(', '),
                    })}
                    className="rounded-lg border border-stone-300 bg-white px-2.5 py-1.5 text-[11px] font-medium hover:border-gold"
                  >
                    Editar
                  </button>
                  )}
                  {servidor.origem ? null : (
                  <button
                    type="button"
                    onClick={() => setRemovendo(servidor)}
                    className="rounded-lg border border-stone-300 bg-white p-1.5 text-zinc-500 hover:border-red-300 hover:text-red-600"
                    aria-label={`Remover ${servidor.nome}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                  )}
                </div>
              </div>

              {inspecao && inspecao !== 'carregando' ? (
                <div className="mt-3 border-t border-stone-100 pt-3">
                  {inspecao.conectado ? (
                    <>
                      <p className="flex items-center gap-1.5 text-[11px] font-medium text-emerald-700">
                        <Check className="h-3.5 w-3.5" />
                        Conectado em {inspecao.ms} ms
                        {typeof inspecao.servidor?.name === 'string' ? ` · ${inspecao.servidor.name}` : ''}
                        {typeof inspecao.servidor?.version === 'string' ? ` ${inspecao.servidor.version}` : ''}
                      </p>
                      <div className="mt-2 space-y-1.5">
                        {inspecao.tools.map(tool => (
                          <div key={tool.nome} className="flex items-start gap-2 text-[11px]">
                            <Plug className="mt-0.5 h-3 w-3 shrink-0 text-zinc-400" />
                            <span className="min-w-0">
                              <span className="font-mono font-medium text-zinc-700">{tool.nome}</span>
                              {tool.descricao ? <span className="ml-2 text-zinc-500">{tool.descricao}</span> : null}
                            </span>
                          </div>
                        ))}
                        {!inspecao.tools.length ? <p className="text-[11px] text-zinc-500">O servidor não expôs ferramentas.</p> : null}
                      </div>
                    </>
                  ) : (
                    <p className="text-[11px] text-red-700">{inspecao.erro}</p>
                  )}
                </div>
              ) : null}
            </article>
          );
        })}
        {!servidores.length && !carregando ? (
          <p className="rounded-xl border border-dashed border-stone-300 p-5 text-center text-sm text-zinc-500">
            Nenhum servidor MCP registrado ainda.
          </p>
        ) : null}
      </div>

      {config ? <p className="mt-3 font-mono text-[10px] text-zinc-400">{config}</p> : null}

      {editor ? (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/30 p-4" onClick={() => setEditor(null)}>
          <div className="w-full max-w-lg rounded-2xl border border-stone-200 bg-[#fffdf8] p-5 shadow-2xl" onClick={event => event.stopPropagation()}>
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-sm font-semibold">{editor.id ? 'Editar servidor' : 'Conectar servidor MCP'}</h3>
                <p className="mt-1 text-[11px] text-zinc-500">stdio roda um processo local; http fala com um endpoint JSON-RPC.</p>
              </div>
              <button type="button" onClick={() => setEditor(null)} className="rounded-md p-1 text-zinc-400 hover:bg-stone-100" aria-label="Fechar">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <label className="block">
                <span className="text-xs font-semibold">Nome</span>
                <input
                  value={editor.nome}
                  onChange={event => setEditor({ ...editor, nome: event.target.value })}
                  placeholder="Meu servidor"
                  className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-gold"
                />
              </label>

              <div className="flex gap-2">
                {(['stdio', 'http'] as const).map(valor => (
                  <button
                    key={valor}
                    type="button"
                    onClick={() => setEditor({ ...editor, transporte: valor })}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${editor.transporte === valor ? 'border-zinc-800 bg-zinc-900 text-white' : 'border-stone-200 bg-white text-zinc-600'}`}
                  >
                    {valor}
                  </button>
                ))}
              </div>

              {editor.transporte === 'stdio' ? (
                <>
                  <label className="block">
                    <span className="text-xs font-semibold">Comando</span>
                    <input
                      value={editor.comando}
                      onChange={event => setEditor({ ...editor, comando: event.target.value })}
                      placeholder="npx"
                      className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 font-mono text-xs outline-none focus:border-gold"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs font-semibold">Argumentos</span>
                    <input
                      value={editor.args}
                      onChange={event => setEditor({ ...editor, args: event.target.value })}
                      placeholder="-y @modelcontextprotocol/server-filesystem ."
                      className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 font-mono text-xs outline-none focus:border-gold"
                    />
                  </label>
                </>
              ) : (
                <label className="block">
                  <span className="text-xs font-semibold">URL</span>
                  <input
                    value={editor.url}
                    onChange={event => setEditor({ ...editor, url: event.target.value })}
                    placeholder="https://exemplo.com/mcp"
                    className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 font-mono text-xs outline-none focus:border-gold"
                  />
                </label>
              )}

              <label className="block">
                <span className="text-xs font-semibold">Variáveis de ambiente necessárias</span>
                <input
                  value={editor.env_vars}
                  onChange={event => setEditor({ ...editor, env_vars: event.target.value })}
                  placeholder="GITHUB_TOKEN, API_KEY"
                  className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 font-mono text-xs outline-none focus:border-gold"
                />
                <span className="mt-1.5 block text-[10px] text-zinc-400">Só o nome. O valor fica no ambiente do servidor e nunca passa por aqui.</span>
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setEditor(null)} className="rounded-lg border border-stone-300 px-3 py-2 text-xs">Cancelar</button>
              <button
                type="button"
                disabled={salvando || !editor.nome.trim()}
                onClick={() => void salvar()}
                className="rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white disabled:opacity-35"
              >
                {salvando ? 'Salvando…' : 'Salvar'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={Boolean(removendo)}
        title={`Remover ${removendo?.nome || ''}?`}
        description="O servidor sai do registro. Nada é apagado do disco dele."
        confirmLabel="Remover"
        onCancel={() => setRemovendo(null)}
        onConfirm={() => { if (removendo) void remover(removendo); }}
      />
    </section>
  );
};
