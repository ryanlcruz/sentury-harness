import React, { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, BookOpen, Check, ChevronDown, Clock, Pause, Play, Send, ShieldAlert, X } from 'lucide-react';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ContextoDoResidente } from './ContextoDoResidente';
import { renderMarkdown } from '../../domain/markdown';
import { Coruja, CorujaVazia, type CoresCoruja, type EstadoCoruja } from './Coruja';
import { EditarManifesto } from './EditarManifesto';
import { Esperando } from './Esperando';
import { RotinasDoResidente } from './RotinasDoResidente';
import { TelaDoResidente } from './TelaDoResidente';
import { atualizarHQ, coresDoAgente } from './useEsperando';
import {
  ENCAIXES, NOME_DO_ESTADO, PECAS, estadoDaCoruja, residentes,
  type Agente, type Catalogo, type Tarefa,
} from './api';

// O Escritório carrega o three.js: só baixa quando alguém abre a aba.
const EscritorioView = lazy(() => import('./escritorio/EscritorioView'));
const DecisoesView = lazy(() => import('./DecisoesView'));
const MesaView = lazy(() => import('./MesaView'));

type Vista = 'residentes' | 'escritorio' | 'mesa' | 'decisoes';
const CHAVE_DA_VISTA = 'sentury.hq.vista';
const vistaGuardada = (): Vista => {
  try {
    const guardada = localStorage.getItem(CHAVE_DA_VISTA);
    return guardada === 'escritorio' || guardada === 'mesa' || guardada === 'decisoes' ? guardada : 'residentes';
  } catch { return 'residentes'; }
};

const coresDe = (agente: Agente): CoresCoruja => coresDoAgente(agente);

const CHIP: Record<EstadoCoruja, string> = {
  parado: 'bg-stone-100 text-stone-700',
  dormindo: 'bg-[#ebe5d8] text-[#57503f]',
  trabalhando: 'bg-emerald-50 text-emerald-800',
  esperando: 'bg-amber-50 text-amber-800',
  pausado: 'bg-stone-200 text-stone-700',
};

const dinheiro = (valor: number) => `US$ ${valor.toFixed(2).replace('.', ',')}`;

const Cena: React.FC<{ altura: number; children: React.ReactNode; balao?: string }> = ({ altura, children, balao }) => (
  <div className="relative flex items-end justify-center overflow-hidden rounded-xl bg-[#f3efe4]" style={{ height: altura }}>
    <div className="absolute inset-x-0 bottom-0 bg-[#ebe5d8]" style={{ height: altura / 4 }} />
    {balao ? (
      <span className="absolute left-3 right-3 top-3 w-fit max-w-[220px] rounded-xl rounded-bl-sm border border-[#e3ddcd] bg-white px-2.5 py-1.5 text-xs leading-snug text-zinc-700">
        {balao}
      </span>
    ) : null}
    <div className="relative mb-1 leading-none">{children}</div>
  </div>
);

const Chip: React.FC<{ estado: EstadoCoruja }> = ({ estado }) => (
  <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${CHIP[estado]}`}>
    {estado === 'esperando' ? <span className="h-1.5 w-1.5 rounded-full bg-amber-600" /> : null}
    {NOME_DO_ESTADO[estado]}
  </span>
);

const Barra: React.FC<{ rotulo: string; valor: string; fracao: number }> = ({ rotulo, valor, fracao }) => (
  <div>
    <div className="flex justify-between text-xs tabular-nums text-[#57503f]"><span>{rotulo}</span><span>{valor}</span></div>
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#ebe5d8]">
      <div className="h-full bg-gold-hover" style={{ width: `${Math.min(100, Math.round(fracao * 100))}%` }} />
    </div>
  </div>
);

const Uso: React.FC<{ agente: Agente }> = ({ agente }) => {
  const usd = agente.orcamento.usd_por_dia || 0;
  const turnos = agente.orcamento.turnos_por_dia || 0;
  return (
    <div className="flex flex-col gap-2">
      <Barra rotulo="Gasto hoje" valor={`${dinheiro(agente.uso_de_hoje.usd)} de ${dinheiro(usd)}`} fracao={usd ? agente.uso_de_hoje.usd / usd : 0} />
      <Barra rotulo="Turnos hoje" valor={`${agente.uso_de_hoje.turnos} de ${turnos}`} fracao={turnos ? agente.uso_de_hoje.turnos / turnos : 0} />
      {agente.uso_de_hoje.turnos_sem_custo ? (
        <p className="text-[11px] leading-snug text-amber-800">
          {agente.uso_de_hoje.turnos_sem_custo} {agente.uso_de_hoje.turnos_sem_custo === 1 ? 'turno' : 'turnos'} sem custo conhecido
          (assinatura ou preço fora do catálogo). O limite em US$ não vê esses; o de turnos vê.
        </p>
      ) : null}
    </div>
  );
};

const NOME_DA_TAREFA: Record<string, string> = { na_fila: 'na fila', rodando: 'rodando agora', feita: 'feita', falhou: 'falhou', cancelada: 'cancelada' };

/** Uma tarefa recolhida numa linha: o pedido e a resposta inteiros ficam a um clique, para a lista não virar um paredão. */
const LinhaDaTarefa: React.FC<{ tarefa: Tarefa }> = ({ tarefa }) => {
  const [aberta, setAberta] = useState(false);
  const titulo = tarefa.pedido.replace(/\s+/g, ' ').trim();
  const codigo = tarefa.id.split('-').pop() || tarefa.id;
  return (
    <div className="border-b border-[#ebe5d8] last:border-b-0">
      <button type="button" onClick={() => setAberta(valor => !valor)} aria-expanded={aberta}
        className="flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-[#faf6ea]">
        {tarefa.estado === 'feita'
          ? <Check className="h-4 w-4 shrink-0 text-emerald-700" />
          : tarefa.estado === 'falhou' || tarefa.estado === 'cancelada'
            ? <X className="h-4 w-4 shrink-0 text-red-600" />
            : <Clock className="h-4 w-4 shrink-0 text-[#7a7263]" />}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm">{titulo}</span>
          <span className="mt-0.5 block text-xs tabular-nums text-zinc-500">
            {NOME_DA_TAREFA[tarefa.estado] || tarefa.estado} · <span className="font-mono">#{codigo}</span>{tarefa.custo_usd ? ` · ${dinheiro(tarefa.custo_usd)}` : ''}
          </span>
        </span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-zinc-400 transition-transform ${aberta ? 'rotate-180' : ''}`} />
      </button>
      {aberta ? (
        <div className="px-5 pb-4 pl-12">
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-zinc-800">{tarefa.pedido}</p>
          {tarefa.resposta ? <div className="prose prose-sm mt-3 max-w-none border-t border-[#ebe5d8] pt-3 text-[13px] leading-relaxed text-zinc-700 prose-headings:text-zinc-900 prose-headings:font-semibold prose-h3:mb-1 prose-h3:mt-3 prose-h3:text-sm prose-table:my-2 prose-th:px-2 prose-th:py-1.5 prose-td:px-2 prose-td:py-1.5"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(tarefa.resposta) }} /> : null}
          {tarefa.motivo && tarefa.estado !== 'feita' ? <p className="mt-2 text-xs text-zinc-600">{tarefa.motivo}</p> : null}
          {tarefa.origem ? <p className="mt-2 text-xs text-zinc-500">Origem: {tarefa.origem}</p> : null}
        </div>
      ) : null}
    </div>
  );
};

const cerebroEmTexto = (agente: Agente) => (agente.cerebro.modelo
  ? `${agente.cerebro.modelo} via ${agente.cerebro.provedor}`
  : 'Router do RobinBandit');


const CardDoAgente: React.FC<{ agente: Agente; estado: EstadoCoruja; balao?: string; onAbrir: () => void }> = ({ agente, estado, balao, onAbrir }) => (
  <button type="button" onClick={onAbrir}
    className="flex flex-col gap-3 rounded-2xl border border-[#d8cfbd] bg-[#fffdf8] p-3.5 text-left transition hover:border-gold-hover">
    <div className="w-full"><Cena altura={156} balao={balao}><Coruja cores={coresDe(agente)} acessorios={agente.aparencia.acessorios} estado={estado} tamanho={120} rotulo={agente.nome} /></Cena></div>
    <div className="flex w-full flex-col gap-1 px-1">
      <div className="flex items-center gap-2">
        <p className="flex-1 text-base font-semibold capitalize">{agente.nome}</p>
        <Chip estado={estado} />
      </div>
      <p className="text-[13px] text-zinc-600">{agente.papel}</p>
      <p className="text-xs text-zinc-500">{cerebroEmTexto(agente)}</p>
    </div>
    <div className="w-full px-1"><Uso agente={agente} /></div>
    {agente.tarefas_abertas ? <p className="px-1 text-xs text-zinc-600">{agente.tarefas_abertas} {agente.tarefas_abertas === 1 ? 'tarefa aberta' : 'tarefas abertas'}</p> : null}
  </button>
);

const FolhaDeAcessorios: React.FC<{ agente: Agente; catalogo: Catalogo; onFechar: () => void; onSalvo: (agente: Agente) => void }> = ({ agente, catalogo, onFechar, onSalvo }) => {
  const [escolha, setEscolha] = useState<Record<string, string>>(agente.aparencia.acessorios);
  const [estado, setEstado] = useState<EstadoCoruja>('parado');
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');
  const doSentury = agente.aparencia.sugeridos || {};
  const plumagem = catalogo.plumagens[agente.aparencia.plumagem]?.nome || '';
  const salvar = async () => {
    setSalvando(true);
    setErro('');
    try {
      onSalvo(await residentes.trocarAcessorios(agente.nome, escolha));
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui salvar');
      setSalvando(false);
    }
  };
  const opcao = (selecionada: boolean) => `min-h-11 rounded-lg px-3.5 text-[13px] transition ${selecionada
    ? 'border-2 border-gold-hover bg-gold-soft' : 'border border-[#ded7c6] bg-white hover:border-zinc-400'}`;
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-zinc-950/30 p-4" role="dialog" aria-modal="true" aria-label={`Acessórios de ${agente.nome}`}>
      <div className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-[#d8cfbd] bg-[#f6f5f0] shadow-2xl">
        <header className="flex items-center gap-3 border-b border-[#e3ddcd] px-5 py-4">
          <div className="flex-1">
            <h2 className="text-lg font-semibold">Acessórios de <span className="capitalize">{agente.nome}</span></h2>
            <p className="text-[13px] text-zinc-600">A plumagem é do Sentury. Os acessórios são seus: um por encaixe.</p>
          </div>
          <button type="button" onClick={onFechar} aria-label="Fechar" className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-200"><X className="h-4 w-4" /></button>
        </header>
        <div className="flex flex-1 flex-wrap gap-5 overflow-y-auto p-5">
          <div className="flex min-w-[260px] flex-1 flex-col gap-3">
            <Cena altura={280}><Coruja cores={coresDe(agente)} acessorios={escolha} estado={estado} tamanho={230} rotulo={agente.nome} /></Cena>
            <div className="flex flex-wrap gap-2">
              {(['parado', 'dormindo', 'trabalhando', 'esperando', 'pausado'] as EstadoCoruja[]).map(item => (
                <button key={item} type="button" aria-pressed={item === estado} onClick={() => setEstado(item)}
                  className={`${opcao(item === estado)} rounded-full`}>{NOME_DO_ESTADO[item]}</button>
              ))}
            </div>
            <p className="rounded-xl border border-[#e3ddcd] bg-[#f3efe4] px-3.5 py-2.5 text-xs text-[#57503f]">
              Plumagem {plumagem.toLowerCase() || 'do nome'}, escolhida pelo Sentury pelo papel. Ela não muda.
            </p>
          </div>
          <div className="flex min-w-[300px] flex-1 flex-col gap-4 rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] p-4">
            {Object.entries(catalogo.encaixes).map(([encaixe, pecas]) => (
              <div key={encaixe}>
                <p className="mb-2 text-[13px] font-semibold">{ENCAIXES[encaixe] || encaixe}
                  {doSentury[encaixe] ? <span className="font-normal text-zinc-500"> · o Sentury pôs {(PECAS[doSentury[encaixe]] || doSentury[encaixe]).toLowerCase()}</span> : null}
                </p>
                <div className="flex flex-wrap gap-2">
                  {['', ...pecas].map(peca => (
                    <button key={peca || 'nenhum'} type="button" aria-pressed={(escolha[encaixe] || '') === peca}
                      onClick={() => setEscolha(atual => {
                        const proxima = { ...atual };
                        if (peca) proxima[encaixe] = peca; else delete proxima[encaixe];
                        return proxima;
                      })}
                      className={opcao((escolha[encaixe] || '') === peca)}>{peca ? PECAS[peca] || peca : 'Nenhum'}</button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <footer className="flex items-center gap-2 border-t border-[#e3ddcd] px-5 py-3">
          {erro ? <p className="flex-1 text-xs text-red-600">{erro}</p> : <span className="flex-1" />}
          <button type="button" onClick={() => setEscolha(doSentury)} className="h-11 px-3 text-[13px] text-zinc-600 underline underline-offset-2">Voltar aos do Sentury</button>
          <button type="button" disabled={salvando} onClick={() => void salvar()}
            className="h-11 rounded-lg bg-gold px-5 text-sm font-semibold text-zinc-950 hover:bg-gold-hover disabled:opacity-50">Salvar</button>
        </footer>
      </div>
    </div>
  );
};

const PaginaDoAgente: React.FC<{ nome: string; catalogo: Catalogo | null; esperando: Tarefa[]; onVoltar: () => void; onMudou: () => void; onConversar?: (nome: string) => void }> = ({ nome, catalogo, esperando, onVoltar, onMudou, onConversar }) => {
  const [agente, setAgente] = useState<Agente | null>(null);
  const [pedido, setPedido] = useState('');
  const [erro, setErro] = useState('');
  const [acessorios, setAcessorios] = useState(false);
  const [aposentar, setAposentar] = useState(false);
  const [editando, setEditando] = useState(false);
  const [aba, setAba] = useState<'ficha' | 'tela' | 'contexto'>('ficha');

  const carregar = useCallback(async () => {
    try {
      setAgente(await residentes.ver(nome));
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui abrir o agente');
    }
  }, [nome]);

  useEffect(() => {
    void carregar();
    const intervalo = window.setInterval(() => void carregar(), 5000);
    return () => window.clearInterval(intervalo);
  }, [carregar]);

  if (!agente) {
    return <div className="p-8 text-sm text-zinc-500">{erro || 'Carregando…'}</div>;
  }

  const estado = estadoDaCoruja(agente, esperando);
  const nomeVisivel = agente.nome[0].toUpperCase() + agente.nome.slice(1);
  const daqui = esperando.filter(t => t.agente === agente.nome);
  const ultima = agente.tarefas?.[0];
  const fala = daqui[0]
    ? (daqui[0].pendente ? `Parei aqui: preciso da sua autorização para ${daqui[0].pendente}.` : daqui[0].resposta || daqui[0].motivo)
    : ultima?.estado === 'feita' ? resumoDaFala(ultima.resposta || '') : '';

  const mudar = async (acao: 'pausar' | 'retomar' | 'aposentar') => {
    try {
      setAgente(await residentes.mudar(agente.nome, acao));
      onMudou();
      if (acao === 'aposentar') onVoltar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui mudar o estado');
    }
  };
  const enviar = async () => {
    if (!pedido.trim()) return;
    try {
      await residentes.pedir(agente.nome, pedido.trim());
      setPedido('');
      await carregar();
      onMudou();
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui mandar a tarefa');
    }
  };

  const rotulo = 'mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#7a7263]';
  return (
    <div className="mx-auto flex w-full max-w-[1040px] flex-col gap-5">
      <button type="button" onClick={onVoltar} className="flex w-fit items-center gap-1.5 text-[13px] text-zinc-600 hover:text-zinc-900">
        <ArrowLeft className="h-3.5 w-3.5" />Sentury HQ
      </button>
      <header className="flex flex-wrap items-center gap-4">
        <div className="w-[168px] shrink-0"><Cena altura={164}><Coruja cores={coresDe(agente)} acessorios={agente.aparencia.acessorios} estado={estado} tamanho={148} rotulo={agente.nome} /></Cena></div>
        <div className="min-w-[220px] flex-1">
          <div className="flex items-center gap-2.5">
            <h1 className="text-[26px] font-semibold capitalize tracking-tight">{agente.nome}</h1>
            <Chip estado={estado} />
          </div>
          <p className="mt-1 text-sm text-zinc-600">{agente.papel}</p>
          {fala ? <p className="mt-2.5 w-fit max-w-xl rounded-2xl rounded-bl-sm border border-[#e3ddcd] bg-white px-3 py-2 text-sm leading-snug text-zinc-700">{fala}</p> : null}
        </div>
        <div className="flex gap-2">
          {agente.estado === 'pausado'
            ? <button type="button" onClick={() => void mudar('retomar')} className="flex h-11 items-center gap-2 rounded-lg border border-[#d8cfbd] bg-white px-3.5 text-sm"><Play className="h-3.5 w-3.5" />Retomar</button>
            : <button type="button" onClick={() => void mudar('pausar')} className="flex h-11 items-center gap-2 rounded-lg border border-[#d8cfbd] bg-white px-3.5 text-sm"><Pause className="h-3.5 w-3.5" />Pausar</button>}
          {onConversar ? <button type="button" onClick={() => onConversar(nome)} className="flex h-11 items-center gap-2 rounded-lg bg-gold px-3.5 text-sm font-semibold text-zinc-950 hover:bg-gold-hover"><Send className="h-3.5 w-3.5" />Conversar</button> : null}
          <button type="button" onClick={() => setEditando(true)} className="h-11 rounded-lg border border-[#d8cfbd] bg-white px-3.5 text-sm">Editar</button>
          {catalogo ? <button type="button" onClick={() => setAcessorios(true)} className="h-11 rounded-lg border border-[#d8cfbd] bg-white px-3.5 text-sm">Acessórios</button> : null}
          <button type="button" onClick={() => setAposentar(true)} className="h-11 px-2.5 text-sm text-zinc-600 underline underline-offset-2">Aposentar</button>
        </div>
      </header>

      <div role="tablist" aria-label="Ficha do residente" className="flex w-fit gap-1 rounded-xl border border-[#e3ddcd] bg-[#f3efe4] p-1">
        {(['ficha', 'tela', 'contexto'] as const).map(item => <button key={item} type="button" role="tab" aria-selected={aba === item}
          onClick={() => setAba(item)} className={`h-9 rounded-lg px-4 text-sm ${aba === item ? 'bg-white font-semibold shadow-sm' : 'text-zinc-600'}`}>
          {item === 'ficha' ? 'Ficha' : item === 'tela' ? 'Tela' : 'Contexto'}</button>)}
      </div>
      {aba === 'tela' ? <TelaDoResidente key={nome} nome={nome} /> : null}
      {aba === 'contexto' ? <ContextoDoResidente key={nome} nome={nome} /> : null}
      <form className={`${aba !== 'ficha' ? 'hidden' : 'flex'} items-center gap-2.5 rounded-xl border border-[#d8cfbd] bg-[#fffdf8] py-2 pl-4 pr-2`} onSubmit={event => { event.preventDefault(); void enviar(); }}>
        <label htmlFor="pedido-ao-agente" className="sr-only">Nova tarefa para {nomeVisivel}</label>
        <input id="pedido-ao-agente" value={pedido} onChange={event => setPedido(event.target.value)} placeholder={`Nova tarefa para ${nomeVisivel}`}
          className="h-11 min-w-0 flex-1 bg-transparent text-sm outline-none" />
        <button type="submit" aria-label="Enviar tarefa" disabled={!pedido.trim()}
          className="flex h-11 w-11 items-center justify-center rounded-lg bg-zinc-900 text-[#f6f5f0] disabled:opacity-40"><Send className="h-4 w-4" /></button>
      </form>
      {erro ? <p className="text-xs text-red-600">{erro}</p> : null}

      <div className={`${aba !== 'ficha' ? 'hidden' : 'flex'} flex-wrap items-start gap-5`}>
        <section aria-label="Tarefas" className="min-w-0 flex-[1_1_520px] overflow-hidden rounded-2xl border border-[#e3ddcd] bg-[#fffdf8]">
          <h2 className="border-b border-[#ebe5d8] px-5 py-3.5 text-[13px] font-semibold">Tarefas</h2>
          {daqui.map(tarefa => (
            <div key={tarefa.id} className="border-b border-[#ebe5d8] bg-[#fffbea]">
              <Esperando tarefa={tarefa} onRespondida={() => { void carregar(); onMudou(); }} />
            </div>
          ))}
          {(agente.tarefas || []).filter(t => t.estado !== 'esperando').map(tarefa => <LinhaDaTarefa key={tarefa.id} tarefa={tarefa} />)}
          {!daqui.length && !(agente.tarefas || []).length ? <p className="px-5 py-6 text-sm text-zinc-500">Nenhuma tarefa ainda.</p> : null}
        </section>

        <aside className="flex min-w-0 flex-[1_1_300px] flex-col gap-4">
          <RotinasDoResidente key={agente.nome} agente={agente} />
          <section aria-label="Uso de hoje" className="rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] p-4">
            <h2 className="mb-3 text-[13px] font-semibold">Uso de hoje</h2>
            <Uso agente={agente} />
            {agente.corte ? <p className="mt-2 text-xs text-amber-800">{agente.corte}</p> : null}
          </section>
          <section aria-label="Manifesto" className="flex flex-col gap-3 rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] p-4">
            <h2 className="text-[13px] font-semibold">Manifesto</h2>
            <div><p className={rotulo}>Objetivo</p><p className="text-[13px] leading-relaxed">{agente.objetivo}</p></div>
            <div>
              <p className={rotulo}>Ferramentas</p>
              <div className="flex flex-wrap gap-1.5">
                {agente.ferramentas.map(f => <span key={f} className="rounded-md border border-[#e3ddcd] bg-[#f3efe4] px-2 py-0.5 font-mono text-xs">{f}</span>)}
              </div>
            </div>
            {agente.skills.length ? (
              <div>
                <p className={rotulo}>Skills</p>
                <div className="flex flex-wrap gap-1.5">
                  {agente.skills.map(s => <span key={s} className="rounded-md bg-zinc-900 px-2 py-0.5 font-mono text-xs text-gold">/{s}</span>)}
                </div>
              </div>
            ) : null}
            {agente.personalidade ? <div><p className={rotulo}>Como ele fala</p><p className="text-[13px] leading-relaxed">{agente.personalidade}</p></div> : null}
            {agente.instrucoes ? <div><p className={rotulo}>Instruções</p><p className="whitespace-pre-wrap text-[13px] leading-relaxed">{agente.instrucoes}</p></div> : null}
            <div><p className={rotulo}>Cérebro</p><p className="text-[13px]">{cerebroEmTexto(agente)}</p>
              {agente.cerebro.se_cair ? <p className="text-xs text-zinc-500">Se cair: {agente.cerebro.se_cair === 'parar' ? 'para e te avisa' : 'segue com o RobinBandit'}</p> : null}</div>
            {agente.canais.length ? <div><p className={rotulo}>Canais</p><p className="text-[13px] capitalize">{agente.canais.join(', ')}</p></div> : null}
          </section>
          <section aria-label="Memória" className="rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] p-4">
            <div className="mb-2 flex items-center gap-2"><BookOpen className="h-4 w-4 text-gold-ink" /><h2 className="text-[13px] font-semibold">O que ele anotou</h2></div>
            {agente.memoria?.trim()
              ? <div className="prose prose-sm max-w-none text-[13px] leading-relaxed text-zinc-700 prose-headings:text-zinc-900 prose-headings:font-semibold prose-h3:text-sm prose-li:my-1 prose-ul:pl-4"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(agente.memoria.trim()) }} />
              : <p className="text-[13px] text-zinc-500">Nada ainda.</p>}
          </section>
        </aside>
      </div>

      {acessorios && catalogo ? (
        <FolhaDeAcessorios agente={agente} catalogo={catalogo} onFechar={() => setAcessorios(false)}
          onSalvo={salvo => { setAgente({ ...agente, ...salvo }); setAcessorios(false); onMudou(); }} />
      ) : null}
      {editando ? (
        <EditarManifesto agente={agente} onFechar={() => setEditando(false)}
          onSalvo={salvo => { setAgente({ ...agente, ...salvo }); setEditando(false); onMudou(); }} />
      ) : null}
      <ConfirmDialog open={aposentar} title={`Aposentar ${agente.nome}?`}
        description="Ele sai da HQ e para de receber tarefas. A pasta dele continua guardada."
        confirmLabel="Aposentar" destructive
        onConfirm={() => { setAposentar(false); void mudar('aposentar'); }} onCancel={() => setAposentar(false)} />
    </div>
  );
};

export const HQView: React.FC<{ abrir?: { nome: string | null; vez: number }; onConversar?: (nome: string) => void; visivel?: boolean }> = ({ abrir, onConversar, visivel = true }) => {
  const [agentes, setAgentes] = useState<Agente[]>([]);
  const [esperando, setEsperando] = useState<Tarefa[]>([]);
  const [catalogo, setCatalogo] = useState<Catalogo | null>(null);
  const [onde, setOnde] = useState('local');
  const [aberto, setAberto] = useState<string | null>(abrir?.nome ?? null);
  // A sidebar manda abrir um residente (ou a lista, sem nome).
  useEffect(() => { if (abrir?.vez) setAberto(abrir.nome); }, [abrir?.vez, abrir?.nome]);
  const [erro, setErro] = useState('');
  const [carregou, setCarregou] = useState(false);
  const [vista, setVista] = useState<Vista>(vistaGuardada);
  // A sala nasce na primeira visita e fica montada: fora de vista ela se pausa
  // sozinha e, na volta, continua do ponto em que estava, sem refazer a cena.
  const [salaMontada, setSalaMontada] = useState(vista === 'escritorio');
  useEffect(() => { if (vista === 'escritorio') setSalaMontada(true); }, [vista]);
  const visivelRef = useRef(visivel);
  visivelRef.current = visivel;
  const escolherVista = (nova: Vista) => {
    setVista(nova);
    try { localStorage.setItem(CHAVE_DA_VISTA, nova); } catch { /* sem armazenamento: vale só nesta visita */ }
  };

  const carregar = useCallback(async () => {
    try {
      const [lista, pendentes] = await Promise.all([residentes.listar(), residentes.esperando()]);
      setAgentes(lista.agentes);
      setOnde(lista.hq);
      setEsperando(pendentes);
      setErro('');
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'a HQ não respondeu');
    } finally {
      setCarregou(true);
    }
  }, []);

  useEffect(() => {
    void carregar();
    void residentes.catalogo().then(setCatalogo).catch(() => setCatalogo(null));
    const intervalo = window.setInterval(() => { if (visivelRef.current) void carregar(); }, 5000);
    return () => window.clearInterval(intervalo);
  }, [carregar]);

  const porNome = useMemo(() => Object.fromEntries(agentes.map(a => [a.nome, a])), [agentes]);
  const trabalhando = agentes.filter(a => a.estado === 'trabalhando').length;
  const gasto = agentes.reduce((total, a) => total + a.uso_de_hoje.usd, 0);

  return (
    <div className="h-full overflow-y-auto px-6 py-8">
      {aberto ? (
        <PaginaDoAgente nome={aberto} catalogo={catalogo} esperando={esperando} onVoltar={() => setAberto(null)} onMudou={() => { void carregar(); atualizarHQ(); }} onConversar={onConversar} />
      ) : null}
        <div className={aberto ? 'hidden' : 'mx-auto flex w-full max-w-[1040px] flex-col gap-6'}>
          <header className="flex flex-wrap items-end gap-4">
            <div className="min-w-[240px] flex-1">
              <h1 className="text-[28px] font-semibold tracking-tight">Sentury HQ</h1>
              <p className="mt-1.5 text-sm text-zinc-600">Os residentes que o Sentury criou. Eles dormem até chegar tarefa.</p>
            </div>
            <span className="inline-flex items-center gap-2 rounded-full border border-[#ded7c6] bg-[#fffdf8] px-3 py-1.5 text-xs text-zinc-700">
              <span className={`h-2 w-2 rounded-full ${erro ? 'bg-red-500' : 'bg-emerald-500'}`} />
              {onde === 'local' ? 'HQ local' : `HQ em ${onde}`} · {erro ? 'sem resposta' : 'conectada'}
            </span>
          </header>
          {erro ? <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{erro}</p> : null}

          <div className="grid grid-cols-3 gap-3.5">
            {[['Residentes', String(agentes.length)], ['Trabalhando agora', String(trabalhando)], ['Gasto hoje', dinheiro(gasto)]].map(([rotulo, valor]) => (
              <div key={rotulo} className="rounded-xl border border-[#e3ddcd] bg-[#fffdf8] px-4 py-3.5">
                <p className="text-xs text-zinc-600">{rotulo}</p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">{valor}</p>
              </div>
            ))}
          </div>

          {esperando.length ? (
            <section aria-label="Esperando você" className="overflow-hidden rounded-2xl border border-[#d8cfbd] bg-[#fffdf8]">
              <header className="flex items-center gap-2.5 border-b border-[#ebe5d8] px-5 py-3.5">
                <ShieldAlert className="h-4 w-4 text-gold-ink" />
                <h2 className="text-[11px] font-bold uppercase tracking-[0.15em] text-gold-ink">Esperando você</h2>
              </header>
              {esperando.map(tarefa => (
                <div key={tarefa.id} className="border-b border-[#ebe5d8] last:border-b-0">
                  <Esperando tarefa={tarefa} agente={porNome[tarefa.agente]} onRespondida={() => { void carregar(); atualizarHQ(); }} />
                </div>
              ))}
            </section>
          ) : null}

          <div role="tablist" aria-label="Como ver os residentes" className="flex w-fit gap-1 rounded-xl border border-[#e3ddcd] bg-[#f3efe4] p-1">
            {([['residentes', 'Residentes'], ['escritorio', 'Escritório'], ['mesa', 'Mesa'], ['decisoes', 'Decisões']] as const).map(([id, nome]) => (
              <button key={id} type="button" role="tab" aria-selected={vista === id} onClick={() => escolherVista(id)}
                className={`h-9 rounded-lg px-4 text-sm transition ${vista === id ? 'bg-[#fffdf8] font-semibold text-zinc-950 shadow-sm' : 'text-zinc-600 hover:text-zinc-900'}`}>
                {nome}
              </button>
            ))}
          </div>

          {vista === 'mesa' ? (
            <div className="h-[640px] overflow-hidden rounded-2xl border border-[#e3ddcd] bg-[#fffdf8]">
              <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-zinc-500">Abrindo a Mesa…</div>}>
                <MesaView embutida />
              </Suspense>
            </div>
          ) : vista === 'decisoes' ? (
            <Suspense fallback={<div className="text-sm text-zinc-500">Abrindo as decisões…</div>}>
              <DecisoesView agentes={agentes} />
            </Suspense>
          ) : vista === 'escritorio' ? null : (
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))' }}>
            {agentes.map(agente => {
              const estado = estadoDaCoruja(agente, esperando);
              const pendente = esperando.find(t => t.agente === agente.nome);
              const balao = pendente ? (pendente.pendente ? `Preciso rodar ${pendente.pendente}. Posso?` : 'Te fiz uma pergunta.') : undefined;
              return <CardDoAgente key={agente.nome} agente={agente} estado={estado} balao={balao} onAbrir={() => setAberto(agente.nome)} />;
            })}
            <div className="flex min-h-[220px] flex-col gap-2.5 rounded-2xl border border-dashed border-[#c9c0ac] p-3.5">
              <div className="flex h-[140px] items-end justify-center rounded-xl bg-[#faf7ef] leading-none"><CorujaVazia tamanho={110} /></div>
              <p className="px-1 text-[15px] font-semibold">O próximo</p>
              <p className="px-1 text-[13px] leading-relaxed text-zinc-600">
                {carregou && !agentes.length ? 'Ainda não há residentes. ' : ''}Descreva o trabalho na conversa: o Sentury propõe o residente e você aprova.
              </p>
            </div>
          </div>
          )}
          {salaMontada ? (
            <div className={vista === 'escritorio' && !aberto ? '' : 'hidden'}>
              <Suspense fallback={<div className="flex h-[420px] items-center justify-center rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] text-sm text-zinc-500">Abrindo o Escritório…</div>}>
                <EscritorioView agentes={agentes} esperando={esperando} onAbrir={setAberto} />
              </Suspense>
            </div>
          ) : null}
        </div>
    </div>
  );
};


/** O balão da coruja é fala, não relatório: o começo da resposta, sem as marcas
 * de markdown, que no balão apareciam cruas (###, **, tabela em barras). A
 * resposta inteira fica na lista de tarefas, renderizada. */
function resumoDaFala(texto: string): string {
  const linhas = texto.split('\n').map(linha => linha.replace(/^#+\s*|^[-*]\s+|\*\*|`|^\|.*\|$/g, '').trim()).filter(Boolean);
  const primeira = linhas[0] || '';
  return primeira.length > 180 ? `${primeira.slice(0, 177).trimEnd()}…` : primeira;
}
