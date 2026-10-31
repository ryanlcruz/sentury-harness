import React, { useMemo, useState } from 'react';
import {
  BookOpen,
  Bot,
  BrainCircuit,
  Boxes,
  FileDiff,
  FileStack,
  MessagesSquare,
  Monitor,
  Palette,
  Route,
  Search,
  Wrench,
} from 'lucide-react';
import { FeatureId } from '../../app/navigation';
import { CAPABILITIES, Capability, CapabilityBadge } from '../../components/CapabilityMark';

interface HelpLibraryViewProps {
  onNavigate: (feature: FeatureId) => void;
}

const articles: Array<{
  title: string;
  summary: string;
  details: string[];
  feature: FeatureId;
  action: string;
  icon: React.ComponentType<{ className?: string }>;
  tags: string[];
}> = [
  {
    title: 'Conversar com o Sentury',
    summary: 'Envio, follow-ups, comandos /skill e estados da resposta.',
    details: ['Enter envia; Shift+Enter quebra a linha.', 'Digite / para localizar e inserir uma skill, e @ para ligar uma função.', 'O botão de parar preserva o turno como interrompido.'],
    feature: 'conversations', action: 'Abrir conversa', icon: Bot, tags: ['chat', 'mensagem', 'interromper', 'follow-up'],
  },
  {
    title: 'Falar com o Sentury enquanto ele trabalha',
    summary: 'Orientar no meio do turno, deixar na fila, parar sem cortar escrita e voltar quando a conexão cai.',
    details: [
      'Com o turno rodando, Enter orienta: a mensagem entra antes do próximo passo, e o chip mostra aguardando, entregue e vista.',
      'Alt+Enter deixa na fila; ela sai sozinha quando o turno termina bem. "Parar e enviar" fica no menu do botão.',
      'Parar corta leitura na hora; escrita, envio e comando terminam antes. Clicar de novo corta já.',
      'Se a conexão cai, a tela tenta voltar 5 vezes. Se o servidor reiniciou no meio, a conversa oferece Continuar.',
    ],
    feature: 'conversations', action: 'Abrir conversa', icon: MessagesSquare, tags: ['orientar', 'fila', 'parar', 'reconectar', 'reinício', 'continuar'],
  },
  {
    title: 'Computador e navegador',
    summary: 'O Sentury usando o mouse, o teclado e o navegador, com aprovação e atalho para parar.',
    details: [
      'Ligue @computador no pedido. O primeiro gesto de cada turno pede aprovação no cartão.',
      'Enquanto ele usa o computador, a tela ganha a moldura e o cursor vira a seta do Sentury.',
      'Ctrl+Alt+Shift+S para na hora e devolve o mouse e o teclado.',
    ],
    feature: 'harness', action: 'Ver o Harness', icon: Monitor, tags: ['computador', 'computer use', 'navegador', 'browser', 'mouse', 'atalho'],
  },
  {
    title: 'Arquivos e instruções do projeto',
    summary: 'O que mudou em cada arquivo e as instruções que você deixa na pasta do projeto.',
    details: [
      'Arquivo criado ou editado mostra "+N −M" no passo; clicando, abre os trechos com o número da linha.',
      'Deixe um Sentury.md, CLAUDE.md ou AGENTS.md na pasta: ao mexer nela, o Sentury segue essas instruções.',
      'A conversa marca quais instruções de projeto passaram a valer.',
    ],
    feature: 'harness', action: 'Ver pastas liberadas', icon: FileDiff, tags: ['diff', 'arquivo', 'editar', 'claude.md', 'agents.md', 'sentury.md', 'projeto'],
  },
  {
    title: 'Router, Reforçado e Dedicado',
    summary: 'Como o RobinBandit escolhe provedores, usa fallback e respeita uma escolha fixa.',
    details: ['Router escolhe a cadeia por custo, saúde e qualidade.', 'Reforçado começa na conta escolhida e pode continuar por fallback.', 'Dedicado termina o turno se a conta escolhida falhar.'],
    feature: 'providers', action: 'Ver provedores', icon: Route, tags: ['router', 'robinbandit', 'modelo', 'provedor'],
  },
  {
    title: 'Processo analítico e diagnóstico',
    summary: 'Etapas reais, ferramentas, modelos, tempos, validações e cópia do JSON técnico.',
    details: ['O progresso acompanha os eventos emitidos pelo Harness.', 'Após a resposta, as etapas ficam recolhidas no Processo analítico.', 'Diagnósticos mostram a execução completa sem fingir eventos ausentes.'],
    feature: 'diagnostics', action: 'Abrir diagnósticos', icon: BrainCircuit, tags: ['think', 'harness', 'debug', 'trace'],
  },
  {
    title: 'Skills, Tools e MCP',
    summary: 'Capacidades procedurais, ferramentas nativas e integrações externas.',
    details: ['Skills orientam como executar uma tarefa.', 'Tools executam operações e consultam dados reais.', 'MCP conecta capacidades externas com permissões explícitas.'],
    feature: 'skills', action: 'Explorar skills', icon: Wrench, tags: ['skill', 'tool', 'mcp', 'integração'],
  },
  {
    title: 'Contexto, memória e compactação',
    summary: 'O que entra na janela do modelo, o que persiste e quando o histórico é compactado.',
    details: ['Context Engine monta identidade, contrato e playbooks.', 'Memória preserva fatos e decisões reutilizáveis.', 'O medidor da caixa de texto usa apenas limites reportados pelo servidor.'],
    feature: 'context', action: 'Ver Context Engine', icon: Boxes, tags: ['contexto', 'memória', 'tokens', 'compactação'],
  },
  {
    title: 'Artefatos, planos e tarefas',
    summary: 'Previews de Markdown, HTML, PDF e envio de planos para acompanhamento.',
    details: ['Artefatos abrem em um painel de leitura sem esconder a conversa.', 'Downloads usam o arquivo validado pelo Harness.', 'Planos podem virar tarefas acompanháveis; [-] marca o item em andamento.'],
    feature: 'artifacts', action: 'Abrir artefatos', icon: FileStack, tags: ['pdf', 'markdown', 'html', 'plano', 'tarefas'],
  },
];

/** Busca sem ligar para acento nem maiúscula: "compactacao" acha "compactação". */
function semAcento(texto: string): string {
  return texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
}

export const HelpLibraryView: React.FC<HelpLibraryViewProps> = ({ onNavigate }) => {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => {
    const normalized = semAcento(query.trim());
    if (!normalized) return articles;
    return articles.filter(article => semAcento([article.title, article.summary, ...article.details, ...article.tags]
      .join(' ')).includes(normalized));
  }, [query]);

  return (
    <section className="h-full overflow-y-auto bg-canvas px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <div className="flex items-start gap-3 border-b border-stone-300 pb-6">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gold-soft text-gold-ink"><BookOpen className="h-5 w-5" /></span>
          <div><p className="text-[10px] font-bold uppercase tracking-[.16em] text-gold-ink">Biblioteca & Ajuda</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Documentação para usar e entender o Sentury</h1><p className="mt-1 text-sm text-zinc-500">Encontre uma função, entenda o que acontece no turno ou vá direto para a área relacionada.</p></div>
        </div>

        <label className="mt-6 flex items-center gap-3 rounded-xl border border-stone-300 bg-[#fffdf8] px-4 py-3 shadow-sm focus-within:border-gold">
          <Search className="h-4 w-4 text-zinc-400" />
          <input value={query} onChange={event => setQuery(event.target.value)} className="w-full bg-transparent text-sm outline-none" placeholder="Buscar: Router, compactação, orientar, diff, skills..." />
        </label>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {filtered.map(article => {
            const Icon = article.icon;
            return <article key={article.title} className="flex flex-col rounded-2xl border border-stone-300 bg-[#fffdf8] p-5 shadow-sm">
              <div className="flex items-start gap-3"><span className="rounded-lg bg-stone-100 p-2 text-gold-ink"><Icon className="h-4 w-4" /></span><div><h2 className="text-sm font-semibold">{article.title}</h2><p className="mt-1 text-xs leading-5 text-zinc-500">{article.summary}</p></div></div>
              <ul className="mt-4 space-y-2 text-xs leading-5 text-zinc-600">{article.details.map(detail => <li key={detail} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-gold-hover" />{detail}</li>)}</ul>
              <button type="button" onClick={() => onNavigate(article.feature)} className="mt-5 self-start rounded-lg border border-stone-300 px-3 py-2 text-xs font-semibold hover:border-gold hover:bg-gold-soft">{article.action}</button>
            </article>;
          })}
        </div>
        {filtered.length === 0 && <p className="py-16 text-center text-sm text-zinc-500">Nenhum artigo encontrado. Tente outro termo.</p>}

        <div className="mt-12 rounded-2xl border border-stone-300 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-3 border-b border-stone-200 pb-4">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-pink-50 text-pink-600"><Palette className="h-4 w-4" /></span>
            <div>
              <h2 className="text-lg font-semibold text-zinc-800">Guia Visual: Subagentes</h2>
              <p className="text-xs text-zinc-500">Cores e ícones que indicam qual capacidade do Sentury está ativa.</p>
            </div>
          </div>
          
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(Object.keys(CAPABILITIES) as Capability[]).map(key => {
              const descriptions: Record<Capability, string> = {
                core: 'Processamento central e conversação base.',
                planner: 'Criando planos de ação e estruturando tarefas.',
                researcher: 'Buscando informações, lendo arquivos ou navegando na web.',
                builder: 'Executando ferramentas, gerando arquivos ou editando código.',
                reviewer: 'Validando saídas, criticando resultados ou conferindo erros.',
                memory: 'Recuperando contexto ou compactando o histórico.',
                router: 'Decidindo qual provedor ou modelo atende melhor a tarefa.',
                mutation: 'Alterando o estado do agente ou do sistema ativamente.',
                workflow: 'Gerenciando uma cadeia de tarefas estruturada.'
              };
              
              return (
                <div key={key} className="flex items-start gap-3 rounded-xl border border-stone-200 p-3 hover:bg-stone-50">
                  <div className="pt-0.5">
                    <CapabilityBadge capability={key} />
                  </div>
                  <p className="text-xs leading-5 text-zinc-600">{descriptions[key]}</p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
};

