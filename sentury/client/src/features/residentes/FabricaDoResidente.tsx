import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { getRuntimeConfig } from '../../runtime/config';
import { Coruja, type CoresCoruja } from './Coruja';
import { CerebroCampos, esforcoDe, type Cerebro } from './CerebroCampos';
import { PECAS, edicao, residentes } from './api';
import { atualizarHQ } from './useEsperando';

/** O cartão da fábrica: o Sentury propõe o residente, a pessoa ajusta, cria ou não.
 * Aparece no lugar do cartão de permissão quando a ferramenta é `criar_agente`. */

const CINZA: CoresCoruja = { penas: '#76767e', asas: '#55555c', barriga: '#b4b4bb' };

interface Props {
  sessionId: string;
  argumentos: Record<string, unknown>;
  enviando: boolean;
  erro: string;
  onCriar: () => void;
  onNaoCriar: () => void;
  onFechar: () => void;
}

const texto = (valor: unknown) => (typeof valor === 'string' ? valor : '');
const lista = (valor: unknown) => (Array.isArray(valor) ? valor.map(String) : []);
const objeto = (valor: unknown) => (valor && typeof valor === 'object' && !Array.isArray(valor) ? valor as Record<string, unknown> : {});

function cerebroInicial(valor: unknown): Cerebro | null {
  const c = objeto(valor);
  if (!texto(c.provedor) || !texto(c.modelo)) return null;
  return { provedor: texto(c.provedor), modelo: texto(c.modelo), se_cair: texto(c.se_cair) === 'robinbandit' ? 'robinbandit' : 'parar',
    ...(esforcoDe(c.esforco) ? { esforco: esforcoDe(c.esforco) } : {}) };
}

export const FabricaDoResidente: React.FC<Props> = ({ sessionId, argumentos, enviando, erro, onCriar, onNaoCriar, onFechar }) => {
  const [previa, setPrevia] = useState<{ cores: CoresCoruja; acessorios: Record<string, string>; plumagem: string } | null>(null);
  const [ajustando, setAjustando] = useState(false);
  const [papel, setPapel] = useState(texto(argumentos.papel));
  const [objetivo, setObjetivo] = useState(texto(argumentos.objetivo));
  const orcamentoProposto = objeto(argumentos.orcamento);
  const [usd, setUsd] = useState(Number(orcamentoProposto.usd_por_dia ?? 1));
  const [turnos, setTurnos] = useState(Number(orcamentoProposto.turnos_por_dia ?? 60));
  const [cerebro, setCerebro] = useState<Cerebro | null>(cerebroInicial(argumentos.cerebro));
  const [falha, setFalha] = useState('');
  const [salvando, setSalvando] = useState(false);
  const nome = texto(argumentos.nome) || 'residente';
  const Nome = nome[0].toUpperCase() + nome.slice(1);
  // O servidor monta a coruja: a do cartão é a mesma que vai nascer.
  useEffect(() => {
    void residentes.previa(nome, texto(argumentos.familia))
      .then(dados => setPrevia({ cores: dados.cores, acessorios: dados.aparencia.acessorios, plumagem: dados.aparencia.plumagem }))
      .catch(() => setPrevia(null));
  }, [nome, argumentos.familia]);
  const cores: CoresCoruja = previa?.cores.penas ? previa.cores : CINZA;
  const pedidos = objeto(argumentos.acessorios);
  const acessorios: Record<string, string> = Object.keys(pedidos).length
    ? Object.fromEntries(Object.entries(pedidos).map(([k, v]) => [k, String(v)]))
    : previa?.acessorios || {};

  const mudou = papel !== texto(argumentos.papel) || objetivo !== texto(argumentos.objetivo)
    || usd !== Number(orcamentoProposto.usd_por_dia ?? 1) || turnos !== Number(orcamentoProposto.turnos_por_dia ?? 60)
    || JSON.stringify(cerebro) !== JSON.stringify(cerebroInicial(argumentos.cerebro));

  const criar = async () => {
    setFalha('');
    if (mudou) {
      setSalvando(true);
      try {
        await edicao.ajustarProposta(sessionId, getRuntimeConfig().userId, {
          papel, objetivo, orcamento: { usd_por_dia: usd, turnos_por_dia: turnos }, cerebro: cerebro || {},
        });
      } catch (e) {
        setFalha(e instanceof Error ? e.message : 'não consegui ajustar a proposta');
        setSalvando(false);
        return;
      }
      setSalvando(false);
    }
    onCriar();
    // A HQ e a sidebar passam a mostrar o residente assim que a retomada o cria.
    window.setTimeout(atualizarHQ, 4000);
  };

  const rotulo = 'mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#7a7263]';
  const campo = 'w-full rounded-lg border border-[#d8cfbd] bg-white px-2.5 py-2 text-sm text-zinc-900 outline-none focus:border-gold-hover';

  return (
    <section aria-label={`Proposta de residente: ${Nome}`} className="overflow-hidden">
      <header className="flex items-center gap-4 border-b border-[#ebe5d8] px-5 py-4">
        <div className="relative flex h-[112px] w-[116px] shrink-0 items-end justify-center overflow-hidden rounded-xl bg-[#f3efe4]">
          <div className="absolute inset-x-0 bottom-0 h-7 bg-[#ebe5d8]" />
          <div className="relative mb-0.5 leading-none"><Coruja cores={cores} acessorios={acessorios} estado="esperando" tamanho={100} rotulo={Nome} /></div>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-gold-ink">Novo residente</p>
          <h2 className="mt-1 text-[22px] font-semibold tracking-tight">{Nome}</h2>
          {ajustando
            ? <input aria-label="Papel" className={`${campo} mt-1`} value={papel} onChange={event => setPapel(event.target.value)} />
            : <p className="text-[13px] text-zinc-600">{papel}</p>}
        </div>
        <button type="button" onClick={onFechar} aria-label="Fechar sem decidir"
          className="self-start rounded-md p-1 text-zinc-400 transition hover:bg-stone-100 hover:text-zinc-700">
          <X className="h-4 w-4" strokeWidth={1.8} />
        </button>
      </header>

      <div className="grid max-h-[50vh] gap-4 overflow-y-auto px-5 py-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <p className={rotulo}>Objetivo</p>
          {ajustando
            ? <textarea aria-label="Objetivo" rows={2} className={campo} value={objetivo} onChange={event => setObjetivo(event.target.value)} />
            : <p className="text-sm leading-relaxed">{objetivo}</p>}
        </div>
        {texto(argumentos.personalidade) ? (
          <div className="sm:col-span-2"><p className={rotulo}>Como ele fala</p><p className="text-sm leading-relaxed">{texto(argumentos.personalidade)}</p></div>
        ) : null}
        <div>
          <p className={rotulo}>Ferramentas</p>
          <div className="flex flex-wrap gap-1.5">
            {lista(argumentos.ferramentas).map(f => <span key={f} className="rounded-md border border-[#e3ddcd] bg-[#f3efe4] px-2 py-0.5 font-mono text-xs">{f}</span>)}
          </div>
          <p className="mt-1.5 text-xs text-zinc-500">Fora desta lista ele não usa nada.</p>
          {lista(argumentos.skills).length ? <>
            <p className={`${rotulo} mt-3`}>Skills</p>
            <div className="flex flex-wrap gap-1.5">
              {lista(argumentos.skills).map(s => <span key={s} className="rounded-md bg-zinc-900 px-2 py-0.5 font-mono text-xs text-gold">/{s}</span>)}
            </div>
            <p className="mt-1.5 text-xs text-zinc-500">Entram carregadas em toda tarefa dele.</p>
          </> : null}
        </div>
        <div className="flex flex-col gap-3">
          <div>
            <p className={rotulo}>Orçamento por dia</p>
            {ajustando ? (
              <div className="flex gap-2">
                <label className="flex flex-1 flex-col gap-1 text-xs text-zinc-600">US$
                  <input type="number" min={0.1} step={0.1} className={campo} value={usd} onChange={event => setUsd(Number(event.target.value))} /></label>
                <label className="flex flex-1 flex-col gap-1 text-xs text-zinc-600">Turnos
                  <input type="number" min={1} step={1} className={campo} value={turnos} onChange={event => setTurnos(Number(event.target.value))} /></label>
              </div>
            ) : <p className="text-sm tabular-nums">US$ {usd.toFixed(2).replace('.', ',')} · {turnos} turnos</p>}
          </div>
          {lista(argumentos.canais).length ? <div><p className={rotulo}>Canais</p><p className="text-sm capitalize">{lista(argumentos.canais).join(', ')}</p></div> : null}
        </div>
        <div className="sm:col-span-2">
          <p className={rotulo}>Cérebro</p>
          <CerebroCampos valor={cerebro} onMudar={setCerebro} />
        </div>
        <div className="sm:col-span-2">
          <p className={rotulo}>Aparência</p>
          <div className="flex flex-wrap items-center gap-1.5">
            {previa?.plumagem ? <span className="rounded-full border border-[#e3ddcd] bg-[#f3efe4] px-2.5 py-1 text-xs">Plumagem {previa.plumagem}</span> : null}
            {Object.values(acessorios).map(peca => <span key={peca} className="rounded-full border border-[#e3ddcd] bg-[#f3efe4] px-2.5 py-1 text-xs">{PECAS[peca] || peca}</span>)}
            <span className="text-xs text-zinc-500">O Sentury montou esta coruja só para ele. Os acessórios você troca depois, na HQ.</span>
          </div>
        </div>
      </div>

      {erro || falha ? <p className="px-5 pb-2 text-xs text-red-600">{falha || erro}</p> : null}
      <footer className="flex flex-wrap items-center gap-2.5 border-t border-[#ebe5d8] bg-[#fbf9f3] px-5 py-3.5">
        <button type="button" disabled={enviando || salvando} onClick={() => void criar()}
          className="h-11 rounded-lg bg-gold px-5 text-sm font-semibold text-zinc-950 transition hover:bg-gold-hover disabled:cursor-wait disabled:opacity-50">Criar {Nome}</button>
        <button type="button" disabled={enviando || salvando} onClick={() => setAjustando(atual => !atual)} aria-pressed={ajustando}
          className="h-11 rounded-lg border border-[#d8cfbd] bg-white px-4 text-sm text-zinc-900 transition hover:border-zinc-400 disabled:opacity-50">{ajustando ? 'Pronto' : 'Ajustar'}</button>
        <button type="button" disabled={enviando || salvando} onClick={onNaoCriar}
          className="h-11 px-3 text-[13px] text-zinc-600 underline underline-offset-2 disabled:opacity-50">Não criar</button>
        <span className="ml-auto text-xs text-zinc-500">Criar residente vale só desta vez: "permitir tudo" não cobre.</span>
      </footer>
    </section>
  );
};
