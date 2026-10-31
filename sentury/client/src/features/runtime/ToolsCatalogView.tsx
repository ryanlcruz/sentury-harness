import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { McpPanel } from './McpPanel';
import { ChevronDown, Layers3, RefreshCw, Search, SearchX, Wrench } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const PAGE_SIZE = 12;
const ALL_CATEGORIES = 'todas';

const ToolSchema = z.object({ nome: z.string(), descricao: z.string() }).passthrough();
const ResponseSchema = z.object({ tools_por_categoria: z.record(z.string(), z.array(ToolSchema)) });

type Tool = z.infer<typeof ToolSchema> & { category: string };

// A categoria chega como chave do tools.yaml (sem acento); a tela mostra o nome.
const ROTULO_DA_CATEGORIA: Record<string, string> = {
  analise: 'Análise',
  acao: 'Ação',
  browser: 'Navegador',
  conhecimento: 'Conhecimento',
  execucao: 'Execução',
  exportacao: 'Exportação',
  external: 'Externa',
  memoria: 'Memória',
  residentes: 'Só dos residentes',
  skill: 'Skill',
};

const rotuloDaCategoria = (categoria: string) =>
  ROTULO_DA_CATEGORIA[categoria] || categoria.charAt(0).toLocaleUpperCase('pt-BR') + categoria.slice(1);

const normalize = (value: string) => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLowerCase();

export const ToolsCatalogView: React.FC = () => {
  const [groups, setGroups] = useState<Record<string, z.infer<typeof ToolSchema>[]>>({});
  const [aba, setAba] = useState<'sentury' | 'mcp'>('sentury');
  const [query, setQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState(ALL_CATEGORIES);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    setLoading(true);
    setError('');

    try {
      const response = await apiClient.get('/sentury/tools', { headers: authHeaders() });
      setGroups(ResponseSchema.parse(response).tools_por_categoria);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [query, selectedCategory]);

  const categories = useMemo(
    () => Object.entries(groups)
      .map(([name, tools]) => ({ name, count: tools.length }))
      .sort((left, right) => left.name.localeCompare(right.name, 'pt-BR')),
    [groups],
  );

  const allTools = useMemo<Tool[]>(
    () => Object.entries(groups).flatMap(([category, tools]) => (
      tools.map(tool => ({ ...tool, category }))
    )),
    [groups],
  );

  const filteredTools = useMemo(() => {
    const normalizedQuery = normalize(query.trim());
    return allTools.filter(tool => {
      const matchesCategory = selectedCategory === ALL_CATEGORIES || tool.category === selectedCategory;
      const matchesQuery = !normalizedQuery || normalize(`${tool.nome} ${tool.descricao} ${tool.category}`).includes(normalizedQuery);
      return matchesCategory && matchesQuery;
    });
  }, [allTools, query, selectedCategory]);

  const visibleTools = filteredTools.slice(0, visibleCount);
  const selectedCategoryLabel = selectedCategory === ALL_CATEGORIES ? 'Todas as ferramentas' : rotuloDaCategoria(selectedCategory);

  return (
    <section className="h-full overflow-y-auto px-5 py-6 sm:px-7 sm:py-7">
      <div className="mx-auto max-w-6xl">
        <header className="flex items-start justify-between gap-5">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Ferramentas registradas</p>
            <h1 className="mt-2 text-2xl font-semibold">Tools e MCP</h1>
            <p className="mt-1 max-w-3xl text-sm text-zinc-500">
              Catálogo real do Harness. Explore por categoria ou encontre diretamente o que precisa.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-stone-300 bg-white p-2 transition-colors hover:border-gold"
            aria-label="Atualizar catálogo"
            title="Atualizar catálogo"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </header>

        {/* MCP no rodape de uma lista longa ficava invisivel: quem procura
            servidor externo nao rola 40 tools ate achar. */}
        <div className="mt-5 flex gap-2 border-b border-stone-200">
          {([['sentury', 'Do Sentury'], ['mcp', 'Servidores MCP']] as const).map(([valor, rotulo]) => (
            <button
              key={valor}
              type="button"
              onClick={() => setAba(valor)}
              className={`-mb-px border-b-2 px-3 py-2 text-xs font-semibold transition-colors ${
                aba === valor ? 'border-gold text-zinc-900' : 'border-transparent text-zinc-500 hover:text-zinc-800'
              }`}
            >
              {rotulo}
            </button>
          ))}
        </div>

        {aba === 'mcp' ? <McpPanel /> : null}

        <div className={aba === 'sentury' ? 'sticky top-0 z-10 -mx-2 mt-5 bg-canvas/95 px-2 py-2 backdrop-blur-sm' : 'hidden'}>
          <label className="flex max-w-2xl items-center gap-2 rounded-xl border border-stone-300 bg-white px-3 py-2.5 shadow-sm focus-within:border-gold">
            <Search className="h-4 w-4 shrink-0 text-zinc-400" />
            <input
              value={query}
              onChange={event => setQuery(event.target.value)}
              placeholder="Buscar por nome, função ou categoria"
              className="w-full bg-transparent text-sm outline-none"
            />
            {query ? (
              <button
                type="button"
                onClick={() => setQuery('')}
                className="text-[10px] font-semibold text-zinc-400 hover:text-zinc-700"
              >
                Limpar
              </button>
            ) : null}
          </label>
        </div>

        {aba === 'sentury' ? (<>
        <nav className="mt-3 flex gap-2 overflow-x-auto pb-2" aria-label="Filtrar ferramentas por categoria">
          <button
            type="button"
            aria-pressed={selectedCategory === ALL_CATEGORIES}
            onClick={() => setSelectedCategory(ALL_CATEGORIES)}
            className={`shrink-0 rounded-full border px-3 py-1.5 text-xs transition-colors ${
              selectedCategory === ALL_CATEGORIES
                ? 'border-zinc-900 bg-zinc-900 font-semibold text-white'
                : 'border-stone-300 bg-white text-zinc-600 hover:border-gold'
            }`}
          >
            Todas <span className="ml-1 opacity-60">{allTools.length}</span>
          </button>
          {categories.map(category => (
            <button
              key={category.name}
              type="button"
              aria-pressed={selectedCategory === category.name}
              onClick={() => setSelectedCategory(category.name)}
              className={`shrink-0 rounded-full border px-3 py-1.5 text-xs transition-colors ${
                selectedCategory === category.name
                  ? 'border-gold bg-gold-soft font-semibold text-zinc-900'
                  : 'border-stone-300 bg-white text-zinc-600 hover:border-gold'
              }`}
            >
              {rotuloDaCategoria(category.name)} <span className="ml-1 opacity-60">{category.count}</span>
            </button>
          ))}
        </nav>

        {error ? <p className="mt-5 rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p> : null}

        <div className="mt-5 flex items-end justify-between gap-4 border-b border-stone-200 pb-3">
          <div>
            <h2 className="text-sm font-semibold">{selectedCategoryLabel}</h2>
            <p className="mt-0.5 text-[11px] text-zinc-500">
              {filteredTools.length} {filteredTools.length === 1 ? 'resultado' : 'resultados'}
              {query ? ` para “${query.trim()}”` : ''}
            </p>
          </div>
          <span className="hidden items-center gap-1.5 text-[10px] text-zinc-400 sm:flex">
            <Layers3 className="h-3.5 w-3.5" /> Selecione um card para ver mais
          </span>
        </div>

        {!loading && visibleTools.length > 0 ? (
          <div className="mt-4 grid items-start gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {visibleTools.map(tool => (
              <details
                key={`${tool.category}-${tool.nome}`}
                className="group overflow-hidden rounded-xl border border-stone-200 bg-white/80 transition-colors open:border-gold hover:border-stone-300"
              >
                <summary className="cursor-pointer list-none p-4 marker:hidden">
                  <span className="flex items-start gap-3">
                    <span className="rounded-lg bg-stone-100 p-2 text-zinc-500 transition-colors group-open:bg-gold-soft group-open:text-gold-ink">
                      <Wrench className="h-3.5 w-3.5" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <strong className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-900">{tool.nome}</strong>
                        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform group-open:rotate-180" />
                      </span>
                      <span className="mt-1 block text-[10px] font-semibold uppercase tracking-wide text-gold-ink">{rotuloDaCategoria(tool.category)}</span>
                      <span className="mt-2 line-clamp-2 min-h-10 text-xs leading-5 text-zinc-500 group-open:hidden">
                        {tool.descricao}
                      </span>
                    </span>
                  </span>
                </summary>
                <div className="border-t border-stone-200 bg-[#fffdf8] px-4 py-3 text-xs leading-5 text-zinc-600">
                  {tool.descricao}
                </div>
              </details>
            ))}
          </div>
        ) : null}

        {!loading && filteredTools.length === 0 && !error ? (
          <div className="mt-12 flex flex-col items-center text-center text-zinc-500">
            <span className="rounded-full bg-stone-100 p-3"><SearchX className="h-5 w-5" /></span>
            <strong className="mt-3 text-sm text-zinc-700">Nenhuma ferramenta encontrada</strong>
            <p className="mt-1 text-xs">Tente outro termo ou escolha uma categoria diferente.</p>
          </div>
        ) : null}

        {visibleCount < filteredTools.length ? (
          <div className="mt-6 flex justify-center">
            <button
              type="button"
              onClick={() => setVisibleCount(count => count + PAGE_SIZE)}
              className="rounded-full border border-stone-300 bg-white px-4 py-2 text-xs font-semibold text-zinc-700 transition-colors hover:border-gold"
            >
              Mostrar mais {Math.min(PAGE_SIZE, filteredTools.length - visibleCount)}
            </button>
          </div>
        ) : null}
        </>) : null}
      </div>
    </section>
  );
};
