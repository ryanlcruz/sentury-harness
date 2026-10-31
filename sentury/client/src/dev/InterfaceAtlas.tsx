import React, { useState } from 'react';
import { MessageBubble } from '../features/chat/MessageBubble';
import { ProcessingIndicator } from '../features/chat/ProcessingIndicator';
import { CommandCard } from '../features/chat/CommandCard';
import { StatusBadge } from '../components/StatusBadge';
import { ChatMessage, CommandRun, SessionRuntimeStatus } from '../contracts/domain/session';
import { QUADRO_DO_ESCRITORIO } from '../features/residentes/escritorio/estilo';
import { respostaComApps, respostaComCodigo, respostaComCores, respostaDoHd, respostaEmHtml } from './atlasBlocoVivo';

type Sheet = 'chat' | 'bloco' | 'vitrine' | 'processing' | 'intelligence' | 'states' | 'inventory' | 'office';
const EscritorioAtlas = React.lazy(() => import('./EscritorioAtlas'));
const VitrineAtlas = React.lazy(() => import('./VitrineAtlas').then(m => ({ default: m.VitrineAtlas })));

const assistantMarkdown = `Revisei o caminho para migrar o **PostgreSQL legado** com uma janela curta de indisponibilidade:

### Estado da migração

| Componente | Risco | Próxima ação |
| --- | --- | --- |
| Esquema | validado | congelar alterações |
| Dados | atenção | ensaiar a cópia incremental |
| Cutover | pendente | aprovar a janela e o rollback |

> [!IMPORTANT]
> O rollback precisa ser provado no ensaio; existir apenas no documento não basta.

- [x] Inventariar extensões e versões
- [ ] Ensaiar a migração com uma cópia anonimizada
- [ ] Aprovar a janela de corte`;

const baseMessage: ChatMessage = {
  id: 'atlas-assistant',
  sessionId: 'atlas',
  role: 'assistant',
  content: assistantMarkdown,
  timestamp: '12:37',
  traces: [
    { stage: 'Contexto recuperado', durationMs: 118, status: 'completed' },
    { stage: 'Plano verificado', durationMs: 385, status: 'completed' },
    { stage: 'Resposta revisada', durationMs: 94, status: 'completed' },
  ],
  status: 'complete',
};

const sheets: Array<{ id: Sheet; label: string }> = [
  { id: 'chat', label: 'Chat' },
  { id: 'bloco', label: 'Bloco vivo' },
  { id: 'vitrine', label: 'Vitrine' },
  { id: 'processing', label: 'Processamento' },
  { id: 'intelligence', label: 'Inteligência' },
  { id: 'states', label: 'Estados' },
  { id: 'inventory', label: 'Inventário' },
  { id: 'office', label: 'Escritório' },
];

const commandStates: CommandRun[] = [
  { id: 'pending', title: 'Esperando a etapa anterior', kind: 'read', status: 'pending' },
  { id: 'running', title: 'Executando a ação atual', kind: 'execute', status: 'running' },
  { id: 'ok', title: 'Ação concluída', kind: 'read', status: 'ok' },
  { id: 'handled', title: 'Fonte falhou; outra rota funcionou', kind: 'fetch', status: 'handledError', resumo: 'A falha foi observada e contornada no mesmo turno.' },
  { id: 'error', title: 'Erro que encerrou a execução', kind: 'execute', status: 'error' },
  { id: 'rejected', title: 'Ação recusada pela política', kind: 'delete', status: 'rejected' },
  { id: 'canceled', title: 'Interrompido pelo usuário', kind: 'edit', status: 'canceled' },
  { id: 'skipped', title: 'Etapa dispensada', kind: 'other', status: 'skipped' },
];

const inventory = [
  ['Chat', 'empty, conversa, erro, retry, follow-up'],
  ['Sessões', 'pastas, status vivo, abrir, renomear, buscar'],
  ['Conteúdo rico', 'Markdown, tabela, callout, código, Mermaid, SVG'],
  ['Artifacts', 'CSV, gráfico, imagem, HTML, plano, PDF, arquivo'],
  ['Knowledge', 'Biblioteca, Skills, Context Engine, Memory'],
  ['Work', 'Tasks, Schedules, Artifacts'],
  ['Runtime', 'Providers, RobinBandit, MCP'],
  ['Observability', 'Harness, Traces, Usage, Diagnostics'],
  ['Sistema', 'Setores, Settings, Telegram, flags'],
  ['Voz', 'STT, chamada live, TTS, transcript'],
];

export const InterfaceAtlas: React.FC = () => {
  const [sheet, setSheet] = useState<Sheet>('chat');
  const [motionReplay, setMotionReplay] = useState(0);
  const statuses: SessionRuntimeStatus[] = ['idle', 'working', 'awaiting_user', 'awaiting_approval', 'finished', 'error', 'interrupted'];

  return (
    <div className="sentury-scroll h-screen overflow-y-scroll bg-canvas text-zinc-900">
      <header className="sticky top-0 z-20 border-b border-stone-200 bg-[#fffdf8]/95 px-6 py-4 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-6">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Dev reference · fixtures isoladas</p>
            <h1 className="mt-1 text-lg font-semibold">Atlas da interface Sentury</h1>
          </div>
          <nav className="flex flex-wrap gap-1 rounded-xl border border-stone-200 bg-stone-100/70 p-1">
            {sheets.map(item => (
              <button key={item.id} type="button" onClick={() => setSheet(item.id)} className={`rounded-lg px-3 py-1.5 text-xs font-medium ${sheet === item.id ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:bg-white'}`}>
                {item.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        {sheet === 'office' ? <React.Suspense fallback={<div style={QUADRO_DO_ESCRITORIO} className="rounded-2xl bg-[#0f1420] p-5 text-sm text-stone-300">Carregando a sala…</div>}><EscritorioAtlas /></React.Suspense> : null}
        {sheet === 'vitrine' && <React.Suspense fallback={null}><VitrineAtlas /></React.Suspense>}
        {sheet === 'chat' && (
          <section>
            <p className="mb-8 max-w-2xl text-sm leading-6 text-zinc-500">Referência do feed: usuário compacto; Sentury diretamente no canvas; processo analítico recolhível.</p>
            <MessageBubble message={{ id: 'atlas-user', sessionId: 'atlas', role: 'user', content: 'Monte um plano seguro para migrar meu banco PostgreSQL legado.', timestamp: '12:36' }} />
            <MessageBubble message={baseMessage} />
          </section>
        )}

        {sheet === 'bloco' && (
          <section>
            <p className="mb-8 max-w-2xl text-sm leading-6 text-zinc-500">Respostas com bloco vivo, pelo renderizador real do chat: cada quadro roda isolado, com o kit e os ícones do Sentury. O simulador mexe e o botão propõe uma mensagem, que pede confirmação na bolha.</p>
            <MessageBubble message={{ id: 'atlas-hd-pergunta', sessionId: 'atlas', role: 'user', content: 'Como está o meu HD?', timestamp: '09:12' }} />
            <MessageBubble message={{ id: 'atlas-hd', sessionId: 'atlas', role: 'assistant', content: respostaDoHd, timestamp: '09:12', status: 'complete' }} />
            <MessageBubble message={{ id: 'atlas-cores-pergunta', sessionId: 'atlas', role: 'user', content: 'Resume outubro das lojas.', timestamp: '09:15' }} />
            <MessageBubble message={{ id: 'atlas-cores', sessionId: 'atlas', role: 'assistant', content: respostaComCores, timestamp: '09:15', status: 'complete' }} />
            <MessageBubble message={{ id: 'atlas-html', sessionId: 'atlas', role: 'assistant', content: respostaEmHtml, timestamp: '09:16', status: 'complete' }} />
            <MessageBubble message={{ id: 'atlas-apps-pergunta', sessionId: 'atlas', role: 'user', content: 'O que está pesando no meu PC?', timestamp: '09:16' }} />
            <MessageBubble message={{ id: 'atlas-apps', sessionId: 'atlas', role: 'assistant', content: respostaComApps, timestamp: '09:16', status: 'complete' }} />
            <MessageBubble message={{ id: 'atlas-codigo-pergunta', sessionId: 'atlas', role: 'user', content: 'Me passa o código HTML desse cartão.', timestamp: '09:17' }} />
            <MessageBubble message={{ id: 'atlas-codigo', sessionId: 'atlas', role: 'assistant', content: respostaComCodigo, timestamp: '09:17', status: 'complete' }} />
          </section>
        )}

        {sheet === 'processing' && (
          <section>
            <p className="mb-8 max-w-2xl text-sm leading-6 text-zinc-500">Eventos SSE reais dirigem o texto, o checklist e o estado. A fixture existe apenas nesta folha de referência.</p>
            <ProcessingIndicator
              stages={[{ stage: 'Consultando base operacional', status: 'completed' }]}
              plan={[
                { id: '1', title: 'Inspecionar esquema e versões', tool: 'inspecionar_banco', kind: 'read', status: 'ok' },
                { id: '2', title: 'Consultar extensão no catálogo antigo', tool: 'consultar_catalogo', kind: 'fetch', status: 'handledError', resumo: 'O catálogo antigo não respondeu; a execução seguiu pela documentação local.' },
                { id: '3', title: 'Validar compatibilidade por outra fonte', tool: 'buscar_documentacao', kind: 'search', status: 'ok' },
                { id: '4', title: 'Preparar ensaio e rollback', tool: 'criar_plano', kind: 'edit', status: 'running' },
              ]}
            />
          </section>
        )}

        {sheet === 'intelligence' && (
          <section>
            <p className="mb-8 max-w-2xl text-sm leading-6 text-zinc-500">Sinais que tornam visível o que o Harness realmente fez, sem competir com a resposta principal.</p>
            <MessageBubble message={{
              ...baseMessage,
              id: 'atlas-signals',
              content: 'O plano foi validado contra o estado atual do ambiente.',
              signals: {
                skillActivated: ['planejamento-migracao'],
                subagents: { requested: true, results: [
                  { role: 'evidence_analyst', status: 'completed', summary: 'Confirmou versões, extensões e dependências do esquema.' },
                  { role: 'operations_critic', status: 'completed', summary: 'Encontrou a lacuna no rollback e pediu um ensaio completo.' },
                ] },
                learned: 'Este ambiente exige rollback ensaiado antes da janela de corte.',
                aprendizados: [{ tipo: 'memoria', texto: 'Este ambiente exige rollback ensaiado antes da janela de corte.' }],
                proactiveInsight: { text: 'A extensão legada não está na instalação nova; vale decidir a substituição antes de copiar os dados.' },
                council: {
                  perspectives: {
                    architecture: 'O esquema deve ser compatível antes da primeira cópia.',
                    reliability: 'O rollback precisa caber na mesma janela operacional.',
                    delivery: 'Cada etapa deve ter dono, critério de saída e evidência.',
                  },
                  tradeOffs: ['Janela menor reduz impacto, mas deixa menos tempo para validar a cópia.'],
                  consensus: 'Ensaiar a sequência completa e só então aprovar o cutover.',
                },
                deliberation: {
                  objective: 'Migrar sem perda de dados e com retorno verificável.',
                  steps: [
                    { tool: 'inspecionar_banco', observation: 'A versão nova aceita o esquema principal.' },
                    { tool: 'buscar_documentacao', observation: 'Uma extensão exige substituição antes do corte.' },
                  ],
                  stopReason: 'evidência suficiente para propor ensaio e rollback',
                },
              },
            }} />
          </section>
        )}

        {sheet === 'states' && (
          <section>
            <div className="flex max-w-3xl items-center justify-between gap-4">
              <h2 className="text-xl font-semibold">Estados do agente</h2>
              <button
                type="button"
                onClick={() => setMotionReplay(value => value + 1)}
                className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 hover:border-gold hover:text-gold-ink"
              >
                Repetir movimento
              </button>
            </div>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">Cada estado precisa contar o que aconteceu sem fazer uma recuperação parecer falha fatal ou um cancelamento parecer execução infinita.</p>
            <div className="mt-6 max-w-3xl">
              {commandStates.map(run => <CommandCard key={run.id} run={run} defaultOpen={run.status === 'handledError'} />)}
            </div>
            <div className="mt-8 flex flex-wrap gap-3">
              {statuses.map(status => <div key={status} className="flex items-center gap-2 rounded-lg border border-stone-200 bg-white/70 px-3 py-2"><StatusBadge status={status} /><span className="font-mono text-[10px] text-zinc-500">{status}</span></div>)}
            </div>
            <div key={motionReplay} className="mt-8 grid max-w-3xl gap-4 md:grid-cols-2">
              <article className="rounded-xl border border-stone-200 bg-white/70 p-4">
                <p className="text-[10px] font-bold uppercase tracking-[.12em] text-zinc-500">Texto chegando</p>
                <p className="mt-2 text-sm text-zinc-700">Compatibilidade confirmada; preparando <span className="sentury-stream-token">o rollback.</span></p>
              </article>
              <article className="sentury-needs-user rounded-xl border border-gold bg-[#fffdf8] p-4">
                <p className="text-[10px] font-bold uppercase tracking-[.12em] text-gold-ink">Precisa de você</p>
                <p className="mt-2 text-sm text-zinc-700">Autorizar a etapa mutante antes de continuar.</p>
              </article>
            </div>
          </section>
        )}

        {sheet === 'inventory' && (
          <section>
            <h2 className="text-xl font-semibold">Folhas previstas</h2>
            <p className="mt-2 text-sm text-zinc-500">Nada desta lista pode desaparecer silenciosamente durante a refatoração.</p>
            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {inventory.map(([title, description]) => (
                <article key={title} className="rounded-xl border border-stone-200 bg-[#fffdf8] p-4">
                  <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
                  <p className="mt-1 text-xs leading-5 text-zinc-500">{description}</p>
                </article>
              ))}
            </div>
            <div className="mt-8 flex flex-wrap gap-3">
              {statuses.map(status => <div key={status} className="flex items-center gap-2 rounded-lg border border-stone-200 bg-white/70 px-3 py-2"><StatusBadge status={status} /><span className="font-mono text-[10px] text-zinc-500">{status}</span></div>)}
            </div>
          </section>
        )}
      </main>
    </div>
  );
};
