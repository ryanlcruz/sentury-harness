import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { Coruja, type EstadoCoruja } from '../Coruja';
import { NOME_DO_ESTADO, colegaDaOrigem, estadoDaCoruja, ferramentaPedida, residentes, type Agente, type Evento, type Tarefa } from '../api';
import { Escritorio, MAXIMO_NA_SALA, type ResidenteNaCena } from './escritorio';
import { clarear } from './iso';
import { EventosDaSala } from './eventosDaSala';
import { QUADRO_DO_ESCRITORIO } from './estilo';
import { ConsultaDaSala } from './consultaDaSala';

/** A aba Escritório da HQ: os residentes de verdade numa sala em 3D.
 *
 * Tudo o que se mexe vem da HQ: o estado de cada um, as tarefas que chegam
 * (envelope na caixa), o que começou, o que terminou e o que espera você.
 * Sem residentes, a sala mostra quatro de exemplo, com um aviso no pé da cena.
 */

interface ItemDoFeed {
  id: string;
  em: number;
  agente: string;
  texto: string;
  origem: string;
  tipo: string;
}

const CINZA = { penas: '#76767e', asas: '#55555c', barriga: '#b4b4bb', olho: '#c9c9d1' };
const nomeVisivel = (nome: string) => nome.charAt(0).toUpperCase() + nome.slice(1);
const dinheiro = (valor: number) => `US$ ${valor.toFixed(2).replace('.', ',')}`;
const hora = (em: number) => new Date(em * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
const inicioDoDia = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; };
const curto = (t: string, n = 70) => (t.length > n ? `${t.slice(0, n - 1)}…` : t);

function origemLegivel(origem: string): string {
  if (!origem) return '';
  if (origem === 'tela') return 'Pedido por você';
  if (origem.startsWith('rotina:')) return 'Rotina';
  if (origem.startsWith('telegram')) return 'Telegram';
  if (origem === 'sentury') return 'Sentury';
  if (origem === 'api') return 'API';
  if (colegaDaOrigem(origem)) return `Pedido por ${colegaDaOrigem(origem)}`;
  return origem;
}

/** O evento da HQ em uma frase, e o que a coruja diz na cena. */
function lerEvento(e: Evento): { feed: string; fala: string; para?: string } {
  const pedido = curto(e.pedido, 60);
  switch (e.tipo) {
    case 'mesa_aberta': return {
      feed: `${e.agente === 'pessoa' ? 'você abriu' : e.iniciativa ? 'abriu por iniciativa própria' : 'abriu'} na Mesa: ${pedido}`,
      fala: e.agente === 'pessoa' ? '' : `Abri na Mesa: ${curto(e.pedido, 34)}`,
    };
    case 'mesa_entrou': return { feed: `entrou no assunto da Mesa: ${pedido}`, fala: '' };
    case 'mesa_fala': return {
      feed: `na Mesa${e.para ? ` com ${nomeVisivel(e.para)}` : ''}: ${curto(e.texto, 60)}`,
      fala: e.texto, para: e.para ? nomeVisivel(e.para) : 'todos',
    };
    case 'mesa_passou': return { feed: `passou a vez na Mesa: ${pedido}`, fala: '' };
    case 'mesa_fechada': return { feed: `fechou o assunto da Mesa: ${pedido}`, fala: '' };
    case 'mesa_reaberta': return { feed: `você retomou o assunto da Mesa: ${pedido}`, fala: '' };
    case 'mesa_sua_vez': return { feed: `todos falaram, a vez é sua no assunto da Mesa: ${pedido}`, fala: '' };
    case 'enfileirada': return colegaDaOrigem(e.origem)
      ? { feed: `recebeu de ${colegaDaOrigem(e.origem)}: ${pedido}`, fala: '' }
      : { feed: `recebeu: ${pedido}`, fala: '' };
    case 'comecou': return { feed: `começou: ${pedido}`, fala: `Começando: ${curto(e.pedido, 40)}` };
    case 'esperando': {
      if (e.aguardando.length) {
        const nomes = e.aguardando.map(nomeVisivel).join(' e ');
        return { feed: `aguardando ${nomes}`, fala: `Aguardando ${nomes}.` };
      }
      const ferramenta = ferramentaPedida(e.pendente);
      if (ferramenta) return { feed: `pediu a ferramenta ${ferramenta}`, fala: `Posso usar ${curto(ferramenta, 30)}?`, para: 'você' };
      return e.pendente
        ? { feed: `quer rodar ${curto(e.pendente, 50)}`, fala: `Posso rodar ${curto(e.pendente, 34)}?`, para: 'você' }
        : { feed: `perguntou: ${curto(e.motivo || pedido, 60)}`, fala: 'Te fiz uma pergunta.', para: 'você' };
    }
    case 'liberada':
      if (e.por === 'colegas') return { feed: 'recebeu a resposta dos colegas e voltou à tarefa', fala: 'Recebi. Sigo daqui.' };
      if (e.negado) return { feed: `seguiu sem a ferramenta ${ferramentaPedida(e.negado)}`, fala: 'Tudo bem, sigo sem ela.', para: 'você' };
      return { feed: 'recebeu sua resposta e voltou à tarefa', fala: 'Obrigado. Sigo daqui.', para: 'você' };
    case 'feita': return { feed: `terminou: ${pedido}`, fala: `Pronto: ${curto(e.pedido, 40)}` };
    case 'falhou': return { feed: `não conseguiu: ${curto(e.motivo || pedido, 60)}`, fala: 'Não consegui. Deixei o motivo na tarefa.' };
    case 'volta_para_a_fila': return { feed: `vai tentar de novo: ${curto(e.motivo, 50)}`, fala: 'Vou tentar de novo.' };
    case 'cancelada': return { feed: `cancelou: ${pedido}`, fala: '' };
    default: return { feed: `${e.tipo}: ${pedido}`, fala: '' };
  }
}

function paraCena(agente: Agente, esperando: Tarefa[]): ResidenteNaCena {
  const c = agente.cores;
  return {
    nome: agente.nome,
    rotulo: nomeVisivel(agente.nome),
    familia: agente.aparencia.familia,
    cores: c.penas
      ? { penas: c.penas, asas: c.asas || c.penas, barriga: c.barriga || c.penas, olho: c.olho || clarear(c.penas, 0.45) }
      : CINZA,
    acessorios: agente.aparencia.acessorios,
    pose: estadoDaCoruja(agente, esperando),
  };
}

// ---------- a demonstração, para quando ainda não há residentes ----------
const EXEMPLOS: (ResidenteNaCena & { papel: string; tarefas: string[] })[] = [
  { nome: 'atlas', rotulo: 'Atlas', familia: 'atendimento', papel: 'Planejador', pose: 'parado',
    cores: { penas: '#3f72b3', asas: '#2d588f', barriga: '#b4cff0', olho: '#5ab0ff' }, acessorios: { rosto: 'oculos', pescoco: 'cachecol', asa: 'prancheta' },
    tarefas: ['Montar o plano da semana', 'Marcar a revisão com o fornecedor'] },
  { nome: 'iris', rotulo: 'Iris', familia: 'dados', papel: 'Analista', pose: 'parado',
    cores: { penas: '#bd6aa0', asas: '#934f80', barriga: '#f3cbe2', olho: '#c58cff' }, acessorios: { ouvidos: 'fone', asa: 'notebook' },
    tarefas: ['Cruzar vendas com estoque', 'Conferir a tabela de preços'] },
  { nome: 'forge', rotulo: 'Forge', familia: 'codigo', papel: 'Construtor', pose: 'parado',
    cores: { penas: '#c97a40', asas: '#a35e2f', barriga: '#f4cfa3', olho: '#ffb15c' }, acessorios: { asa: 'chave', cabeca: 'capacete' },
    tarefas: ['Ver por que o CI ficou vermelho', 'Atualizar as dependências'] },
  { nome: 'nox', rotulo: 'Nox', familia: 'pesquisa', papel: 'Pesquisador', pose: 'dormindo',
    cores: { penas: '#2e2b38', asas: '#221f2b', barriga: '#5d5673', olho: '#a68bff' }, acessorios: { asa: 'lupa', pescoco: 'cachecol' },
    tarefas: ['Achar fontes sobre o setor', 'Resumir o relatório do mês'] },
];

export const EscritorioView: React.FC<{ agentes: Agente[]; esperando: Tarefa[]; onAbrir: (nome: string) => void }> = ({ agentes, esperando, onAbrir }) => {
  const hostRef = useRef<HTMLDivElement>(null);
  const motorRef = useRef<Escritorio | null>(null);
  const retomarRef = useRef<(() => void) | null>(null);
  const [selecionado, setSelecionado] = useState<string | null>(null);
  const [feed, setFeed] = useState<ItemDoFeed[]>([]);
  const [feitasHoje, setFeitasHoje] = useState(0);
  const [erro, setErro] = useState('');
  const [retrato, setRetrato] = useState<string | null>(null);
  const demo = agentes.length === 0;
  const [poseDemo, setPoseDemo] = useState<Record<string, EstadoCoruja>>({});

  useEffect(() => {
    if (!hostRef.current) return undefined;
    const motor = new Escritorio(hostRef.current, {
      progressivo: true,
      aoSelecionar: setSelecionado,
      aoAtividade: ativa => { if (ativa) retomarRef.current?.(); },
    });
    motorRef.current = motor;
    return () => { motor.destruir(); motorRef.current = null; };
  }, []);

  const naCena = useMemo<ResidenteNaCena[]>(() => (demo
    ? EXEMPLOS.map(r => ({ ...r, pose: poseDemo[r.nome] || r.pose }))
    : agentes.map(a => paraCena(a, esperando))), [demo, agentes, esperando, poseDemo]);
  // Só ressincroniza quando algo da sala mudou de fato, não a cada busca da HQ.
  const assinatura = JSON.stringify(naCena);
  const naCenaRef = useRef(naCena);
  naCenaRef.current = naCena;
  useEffect(() => { motorRef.current?.sincronizar(naCenaRef.current); }, [assinatura]);

  useEffect(() => { motorRef.current?.selecionar(selecionado); }, [selecionado]);
  useEffect(() => {
    setRetrato(selecionado ? motorRef.current?.retrato(selecionado) ?? null : null);
  }, [selecionado, assinatura]);

  // Números do quadro do dia, do rack e do farol.
  const abertas = agentes.reduce((t, a) => t + a.tarefas_abertas, 0);
  const usd = agentes.reduce((t, a) => t + a.uso_de_hoje.usd, 0);
  const turnos = agentes.reduce((t, a) => t + a.uso_de_hoje.turnos, 0);
  useEffect(() => {
    motorRef.current?.painel({ feitas: feitasHoje, fila: Math.max(0, abertas - esperando.length), esperando: esperando.length, usd, turnos });
  }, [feitasHoje, abertas, esperando.length, usd, turnos]);

  // O feed: o dia inteiro na primeira leitura, depois só o que é novo.
  const trilhaRef = useRef(new EventosDaSala());
  const mostrar = useCallback((eventos: Evento[], animar: boolean) => {
    const todos = trilhaRef.current.receber(eventos, animar, motorRef.current, lerEvento);
    // Cada vez na Mesa é uma tarefa por baixo (recebeu, começou, terminou); no
    // feed basta o que se disse nela: a fala, o passe e o fechamento.
    const novos = todos.filter(e => !(e.origem?.startsWith('mesa:') && !e.tipo.startsWith('mesa_')));
    const feitas = novos.filter(e => e.tipo === 'feita').length;
    if (feitas) setFeitasHoje(n => n + feitas);
    if (novos.length) setFeed(atual => [
      ...novos.reverse().map(e => ({
        id: JSON.stringify([e.tarefa, e.em, e.tipo, e.agente]), em: e.em, agente: e.agente,
        texto: lerEvento(e).feed, origem: e.tipo === 'enfileirada' ? origemLegivel(e.origem) : '', tipo: e.tipo,
      })), ...atual,
    ].slice(0, 40));
  }, []);

  useEffect(() => {
    if (demo) return undefined;
    trilhaRef.current = new EventosDaSala();
    trilhaRef.current.desde = inicioDoDia();
    setFeed([]);
    setFeitasHoje(0);
    const consulta = new ConsultaDaSala({
      eventos: () => residentes.eventos(Math.max(0, trilhaRef.current.desde - 0.001), 200),
      estado: async () => {
        const [lista, esperandoAgora, assuntos] = await Promise.all([
          residentes.listar(), residentes.esperando(), residentes.assuntos(),
        ]);
        return { agentes: lista.agentes, esperando: esperandoAgora, assuntos };
      },
    }, {
      eventos: mostrar,
      estado: atual => {
        motorRef.current?.sincronizar(atual.agentes.map(a => paraCena(a, atual.esperando)));
        trilhaRef.current.restaurarMesas(atual.assuntos, motorRef.current);
      },
      reconciliar: () => trilhaRef.current.reconciliar(motorRef.current),
      erro: setErro,
    });
    retomarRef.current = () => consulta.retomar();
    void consulta.buscar();
    // Fora de vista a sala está pausada: a volta (`retomar`) busca o que mudou.
    const intervalo = window.setInterval(() => { if (motorRef.current?.ativa()) void consulta.buscar(); }, 4000);
    return () => { consulta.parar(); retomarRef.current = null; window.clearInterval(intervalo); };
  }, [demo, mostrar]);

  // A demonstração: de tempos em tempos um exemplo recebe, faz e entrega uma tarefa.
  useEffect(() => {
    if (!demo) return undefined;
    setFeed([]);
    setFeitasHoje(0);
    let vivo = true, vez = 0;
    const timers: number[] = [];
    const depois = (ms: number, fn: () => void) => { timers.push(window.setTimeout(() => { if (vivo) fn(); }, ms)); };
    const agora = () => Date.now() / 1000;
    const anotar = (agente: string, tipo: string, texto: string, origem = '') =>
      setFeed(atual => [{ id: `demo-${agente}-${agora()}-${tipo}`, em: agora(), agente, texto, origem, tipo }, ...atual].slice(0, 40));
    const ciclo = () => {
      const r = EXEMPLOS[vez % EXEMPLOS.length];
      const tarefa = r.tarefas[Math.floor(vez / EXEMPLOS.length) % r.tarefas.length];
      vez += 1;
      anotar(r.nome, 'enfileirada', `recebeu: ${tarefa}`, 'Exemplo');
      motorRef.current?.pedidoChegou(r.nome);
      depois(4200, () => {
        setPoseDemo(p => ({ ...p, [r.nome]: 'trabalhando' }));
        motorRef.current?.falar(r.nome, `Começando: ${tarefa}`);
        anotar(r.nome, 'comecou', `começou: ${tarefa}`);
      });
      depois(11000, () => {
        setPoseDemo(p => ({ ...p, [r.nome]: 'parado' }));
        motorRef.current?.falar(r.nome, `Pronto: ${tarefa}`);
        anotar(r.nome, 'feita', `terminou: ${tarefa}`);
        setFeitasHoje(n => n + 1);
      });
      depois(9000, ciclo);
    };
    depois(1500, ciclo);
    return () => { vivo = false; timers.forEach(t => window.clearTimeout(t)); };
  }, [demo]);

  const porNome = useMemo(() => Object.fromEntries(agentes.map(a => [a.nome, a])), [agentes]);
  const corDe = (nome: string) => naCena.find(r => r.nome === nome)?.cores.olho || '#a8a29e';
  const sel = selecionado ? naCena.find(r => r.nome === selecionado) : undefined;
  const agenteSel = selecionado ? porNome[selecionado] : undefined;
  const exemploSel = demo && selecionado ? EXEMPLOS.find(r => r.nome === selecionado) : undefined;
  const ultimoDoSel = selecionado ? feed.find(i => i.agente === selecionado) : undefined;
  const esperaDoSel = selecionado ? esperando.find(t => t.agente === selecionado) : undefined;
  const foraDaSala = Math.max(0, agentes.length - MAXIMO_NA_SALA);
  const rotulo = 'text-[11px] font-semibold uppercase tracking-[0.08em] text-[#7a7263]';

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section aria-label="Escritório" className="relative min-w-0 self-start overflow-hidden rounded-2xl border border-[#d8cfbd] bg-[radial-gradient(80%_70%_at_45%_40%,#1a2133_0%,#0f1420_70%)]">
        <div ref={hostRef} style={QUADRO_DO_ESCRITORIO} />
        {foraDaSala ? (
          <span className="pointer-events-none absolute left-3 top-3 z-10 rounded-full bg-[#0f1420]/80 px-2.5 py-1 text-[11px] text-stone-300">+{foraDaSala} na aba Residentes</span>
        ) : null}
        {demo ? (
          <p className="absolute inset-x-3 bottom-3 z-10 rounded-xl bg-[#0f1420]/85 px-3 py-2 text-xs leading-snug text-stone-300">
            Ainda não há residentes: estes quatro são de exemplo. Descreva o trabalho na conversa e o Sentury propõe o primeiro.
          </p>
        ) : null}
      </section>

      <aside className="flex min-w-0 flex-col gap-4">
        {sel ? (
          <section aria-label={`Ficha de ${sel.rotulo}`} className="rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] p-4">
            <div className="flex items-center gap-3">
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl bg-[#1a2133]">
                {retrato
                  ? <img src={retrato} alt="" className="h-16 w-16 object-contain" />
                  : <Coruja cores={sel.cores} acessorios={sel.acessorios} estado={sel.pose} tamanho={56} rotulo={sel.rotulo} />}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-base font-semibold">{sel.rotulo}</p>
                <p className="truncate text-[13px] text-zinc-600">{agenteSel?.papel || exemploSel?.papel}</p>
                <span className="mt-1 inline-block rounded-full bg-stone-100 px-2 py-0.5 text-[11px] text-stone-700">{NOME_DO_ESTADO[sel.pose]}</span>
              </div>
              <button type="button" onClick={() => setSelecionado(null)} aria-label="Fechar a ficha" className="self-start rounded-md px-1.5 text-lg leading-none text-zinc-500 hover:bg-stone-100">×</button>
            </div>
            <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
              <dt className="text-zinc-500">Agora</dt>
              <dd className="min-w-0">{esperaDoSel
                ? (ferramentaPedida(esperaDoSel.pendente) ? `Esperando você liberar a ferramenta ${ferramentaPedida(esperaDoSel.pendente)}`
                  : esperaDoSel.pendente ? `Esperando você para rodar ${esperaDoSel.pendente}` : 'Esperando sua resposta')
                : sel.pose === 'trabalhando' && ultimoDoSel ? ultimoDoSel.texto
                  : sel.pose === 'dormindo' ? 'Dormindo até chegar tarefa' : NOME_DO_ESTADO[sel.pose]}</dd>
              {agenteSel ? (
                <>
                  <dt className="text-zinc-500">Cérebro</dt>
                  <dd className="min-w-0">{agenteSel.cerebro.modelo ? `${agenteSel.cerebro.modelo} via ${agenteSel.cerebro.provedor}` : 'Router do RobinBandit'}</dd>
                  <dt className="text-zinc-500">Uso hoje</dt>
                  <dd className="tabular-nums">{agenteSel.uso_de_hoje.turnos} turnos · {dinheiro(agenteSel.uso_de_hoje.usd)}</dd>
                  <dt className="text-zinc-500">Abertas</dt>
                  <dd className="tabular-nums">{agenteSel.tarefas_abertas}</dd>
                </>
              ) : null}
            </dl>
            {agenteSel ? (
              <button type="button" onClick={() => onAbrir(agenteSel.nome)}
                className="mt-3 inline-flex h-10 items-center gap-1.5 rounded-lg border border-[#d8cfbd] bg-white px-3 text-sm hover:border-zinc-400">
                Abrir {sel.rotulo}<ArrowUpRight className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </section>
        ) : (
          <p className="rounded-2xl border border-dashed border-[#d8cfbd] px-4 py-3 text-[13px] text-zinc-600">
            Clique numa coruja para ver o que ela está fazendo.
          </p>
        )}

        <section aria-label="Ao vivo" className="min-h-0 overflow-hidden rounded-2xl border border-[#e3ddcd] bg-[#fffdf8]">
          <h2 className={`border-b border-[#ebe5d8] px-4 py-3 ${rotulo}`}>Ao vivo</h2>
          {erro ? <p className="px-4 py-3 text-xs text-red-600">{erro}</p> : null}
          <ul className="max-h-[420px] overflow-y-auto" aria-live="polite">
            {feed.map(item => (
              <li key={item.id} className="grid grid-cols-[38px_8px_minmax(0,1fr)] items-baseline gap-2 border-b border-[#f1ece0] px-4 py-2 text-[13px] last:border-b-0">
                <span className="font-mono text-[11px] tabular-nums text-zinc-500">{hora(item.em)}</span>
                <span className="h-2 w-2 self-center rounded-full" style={{ background: corDe(item.agente) }} />
                <span className="min-w-0 text-zinc-700">
                  <button type="button" onClick={() => setSelecionado(item.agente)} className="mr-1 font-semibold text-zinc-900 hover:underline">{nomeVisivel(item.agente)}</button>
                  {item.texto}
                  {item.origem ? <span className="ml-1.5 inline-block rounded-full border border-amber-300/70 bg-amber-50 px-1.5 py-px align-middle text-[10.5px] font-medium text-amber-800">{item.origem}</span> : null}
                </span>
              </li>
            ))}
            {!feed.length ? <li className="px-4 py-4 text-[13px] text-zinc-500">{demo ? 'Começando a demonstração…' : 'Nada hoje ainda. Quando chegar tarefa, aparece aqui.'}</li> : null}
          </ul>
        </section>
      </aside>
    </div>
  );
};

export default EscritorioView;
