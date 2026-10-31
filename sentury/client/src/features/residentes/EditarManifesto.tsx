import React, { useState } from 'react';
import { X } from 'lucide-react';
import { CerebroCampos, esforcoDe, type Cerebro } from './CerebroCampos';
import { edicao, type Agente } from './api';

/** O que se edita depois de criado. Ferramentas ficam de fora: dar ferramenta
 * nova a um residente passa pela fábrica, com o cartão. */
export const EditarManifesto: React.FC<{ agente: Agente; onFechar: () => void; onSalvo: (agente: Agente) => void }> = ({ agente, onFechar, onSalvo }) => {
  const [papel, setPapel] = useState(agente.papel);
  const [objetivo, setObjetivo] = useState(agente.objetivo);
  const [personalidade, setPersonalidade] = useState(agente.personalidade);
  const [instrucoes, setInstrucoes] = useState(agente.instrucoes);
  const [usd, setUsd] = useState(agente.orcamento.usd_por_dia ?? 1);
  const [turnos, setTurnos] = useState(agente.orcamento.turnos_por_dia ?? 60);
  const [iniciativas, setIniciativas] = useState(agente.autonomia.iniciativas_por_dia ?? 3);
  const [falas, setFalas] = useState(agente.autonomia.falas_por_assunto ?? 3);
  const [rede, setRede] = useState(agente.rede);
  const [cerebro, setCerebro] = useState<Cerebro | null>(agente.cerebro.modelo
    ? { provedor: agente.cerebro.provedor || '', modelo: agente.cerebro.modelo, se_cair: agente.cerebro.se_cair === 'robinbandit' ? 'robinbandit' : 'parar',
        ...(esforcoDe(agente.cerebro.esforco) ? { esforco: esforcoDe(agente.cerebro.esforco) } : {}) }
    : null);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');

  const salvar = async () => {
    setSalvando(true);
    setErro('');
    try {
      onSalvo(await edicao.editar(agente.nome, {
        papel, objetivo, personalidade, instrucoes, orcamento: { usd_por_dia: usd, turnos_por_dia: turnos },
        autonomia: { iniciativas_por_dia: iniciativas, falas_por_assunto: falas }, cerebro: cerebro || {}, rede,
      }));
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui salvar');
      setSalvando(false);
    }
  };

  const rotulo = 'mb-1 block text-[11px] font-semibold uppercase tracking-[0.08em] text-[#7a7263]';
  const campo = 'w-full rounded-lg border border-[#d8cfbd] bg-white px-2.5 py-2 text-sm text-zinc-900 outline-none focus:border-gold-hover';
  const Nome = agente.nome[0].toUpperCase() + agente.nome.slice(1);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-zinc-950/30 p-4" role="dialog" aria-modal="true" aria-label={`Editar ${Nome}`}>
      <div className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-[#d8cfbd] bg-[#fffdf8] shadow-2xl">
        <header className="flex items-center gap-3 border-b border-[#e3ddcd] px-5 py-4">
          <div className="flex-1">
            <h2 className="text-lg font-semibold">Editar {Nome}</h2>
            <p className="text-[13px] text-zinc-600">Vale a partir da próxima tarefa. Ferramentas novas passam pela fábrica.</p>
          </div>
          <button type="button" onClick={onFechar} aria-label="Fechar" className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-200"><X className="h-4 w-4" /></button>
        </header>
        <div className="flex flex-col gap-4 overflow-y-auto p-5">
          <label><span className={rotulo}>Papel</span><input className={campo} value={papel} onChange={event => setPapel(event.target.value)} /></label>
          <label><span className={rotulo}>Objetivo</span><textarea rows={2} className={campo} value={objetivo} onChange={event => setObjetivo(event.target.value)} /></label>
          <label><span className={rotulo}>Como ele fala</span>
            <textarea rows={3} maxLength={400} className={campo} value={personalidade} placeholder="Duas ou três frases: o jeito de falar, uma convicção do ofício e como reage quando discordam dele."
              onChange={event => setPersonalidade(event.target.value)} /></label>
          <label><span className={rotulo}>Instruções</span>
            <textarea rows={3} className={campo} value={instrucoes} placeholder="Regras de trabalho dele, ditas por você"
              onChange={event => setInstrucoes(event.target.value)} /></label>
          <div>
            <span className={rotulo}>Orçamento por dia</span>
            <div className="flex gap-2">
              <label className="flex flex-1 flex-col gap-1 text-xs text-zinc-600">US$
                <input type="number" min={0.1} step={0.1} className={campo} value={usd} onChange={event => setUsd(Number(event.target.value))} /></label>
              <label className="flex flex-1 flex-col gap-1 text-xs text-zinc-600">Turnos
                <input type="number" min={1} step={1} className={campo} value={turnos} onChange={event => setTurnos(Number(event.target.value))} /></label>
            </div>
          </div>
          <div>
            <span className={rotulo}>Por conta própria</span>
            <div className="flex gap-2">
              <label className="flex flex-1 flex-col gap-1 text-xs text-zinc-600">Assuntos que ele abre na Mesa por dia
                <input type="number" min={0} max={20} step={1} className={campo} value={iniciativas} onChange={event => setIniciativas(Number(event.target.value))} /></label>
              <label className="flex flex-1 flex-col gap-1 text-xs text-zinc-600">Falas dele em cada assunto
                <input type="number" min={0} max={20} step={1} className={campo} value={falas} onChange={event => setFalas(Number(event.target.value))} /></label>
            </div>
          </div>
          <div><span className={rotulo}>Cérebro</span><CerebroCampos valor={cerebro} onMudar={setCerebro} /></div>
          <label><span className={rotulo}>Rede da caixa</span>
            <select className={campo} value={rede} onChange={event => setRede(event.target.value as Agente['rede'])}>
              <option value="nenhuma">Sem rede</option>
              <option value="internet">Internet pelo proxy da HQ</option>
            </select>
            <span className="mt-1 block text-xs text-zinc-600">A internet não dá acesso à HQ nem à rede local. Vale na próxima tarefa.</span>
          </label>
        </div>
        <footer className="flex items-center gap-2 border-t border-[#e3ddcd] px-5 py-3">
          {erro ? <p className="flex-1 text-xs text-red-600">{erro}</p> : <span className="flex-1" />}
          <button type="button" onClick={onFechar} className="h-11 px-3 text-[13px] text-zinc-600 underline underline-offset-2">Cancelar</button>
          <button type="button" disabled={salvando} onClick={() => void salvar()}
            className="h-11 rounded-lg bg-gold px-5 text-sm font-semibold text-zinc-950 hover:bg-gold-hover disabled:opacity-50">Salvar</button>
        </footer>
      </div>
    </div>
  );
};
