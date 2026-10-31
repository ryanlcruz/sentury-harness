import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Circle, Flag, LoaderCircle, OctagonPause, Play, X } from 'lucide-react';
import { useChatStore } from '../../stores/chat-store';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

/**
 * O goal da conversa: um objetivo que o agente persegue sozinho até cumprir.
 *
 * Três decisões são da pessoa, e só este card as oferece:
 * - **começar.** O agente propõe; nada roda sozinho antes do "Começar".
 * - **pausar e continuar.** O executor também para sozinho (limite, pedido de
 *   autorização, pergunta, falhas, turnos sem agir) e diz por quê.
 * - **cumpriu?** O agente declara com evidência; a palavra final é daqui.
 *   "Ainda não" volta ao trabalho com a nota como instrução.
 */

interface Marco { titulo: string; feito: boolean; evidencia?: unknown }

interface Goal {
  id: string;
  objetivo: string;
  criterio: string;
  marcos: Marco[];
  marcos_feitos: number;
  estado: 'proposto' | 'ativo' | 'pausado' | 'aguardando_confirmacao' | 'cumprido' | 'abandonado';
  motivo: string;
  pausado_por: string;
  turnos: number;
  limite_turnos: number;
  limite_horas: number;
  modo: string;
  evidencia_final: unknown;
  nota_do_dono: string;
  atualizado_em: number;
  rodando: boolean;
}

const MODOS: Array<{ valor: string; rotulo: string }> = [
  { valor: 'router', rotulo: 'Router' },
  { valor: 'ultra', rotulo: 'Reforçado' },
  { valor: 'ultra_max', rotulo: 'Dedicado' },
];

function rotuloDoModo(modo: string): string {
  return MODOS.find(m => m.valor === modo)?.rotulo || 'Router';
}

function Evidencia({ valor }: { valor: unknown }) {
  const texto = typeof valor === 'string' ? valor : JSON.stringify(valor, null, 1);
  if (!texto) return null;
  if (/^https?:\/\/\S+$/.test(texto.trim())) {
    return <a href={texto.trim()} target="_blank" rel="noreferrer" className="break-all text-indigo-700 underline">{texto.trim()}</a>;
  }
  return <span className="whitespace-pre-wrap break-words">{texto}</span>;
}

async function chamar(path: string, corpo: unknown = {}): Promise<Goal | null> {
  const config = getRuntimeConfig();
  apiClient.setBaseUrl(config.apiUrl);
  const r = await apiClient.post<{ goal: Goal }>(path, corpo, { headers: authHeaders() });
  return r.goal;
}

export const GoalCard: React.FC<{ sessionId: string; conversando: boolean }> = ({ sessionId, conversando }) => {
  const [goal, setGoal] = useState<Goal | null>(null);
  const [modo, setModo] = useState<string>(() => getRuntimeConfig().mode || 'router');
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState('');
  const [recusando, setRecusando] = useState(false);
  const [nota, setNota] = useState('');
  const [verMarcos, setVerMarcos] = useState(false);
  const turnosVistos = useRef<number | null>(null);

  const buscar = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    try {
      const r = await apiClient.get<{ goal: Goal | null }>(
        `/sentury/goals?session_id=${encodeURIComponent(sessionId)}`, { headers: authHeaders() });
      setGoal(r.goal);
      // Turno automático novo: a conversa recarrega para mostrar o que ele fez.
      const turnos = r.goal ? r.goal.turnos : null;
      if (turnosVistos.current !== null && turnos !== null && turnos !== turnosVistos.current) {
        useChatStore.getState().loadSession(sessionId);
      }
      turnosVistos.current = turnos;
    } catch {
      // Sem o endpoint de objetivos, o card permanece oculto.
    }
  }, [sessionId]);

  useEffect(() => { turnosVistos.current = null; setGoal(null); setRecusando(false); }, [sessionId]);

  // Ao terminar uma mensagem da pessoa, o agente pode ter proposto um goal.
  useEffect(() => { if (!conversando) buscar(); }, [conversando, buscar]);

  useEffect(() => {
    const rodando = goal?.estado === 'ativo';
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') buscar();
    }, rodando ? 3000 : 15000);
    return () => window.clearInterval(id);
  }, [goal?.estado, buscar]);

  const agir = async (acao: string, corpo: unknown = {}) => {
    if (!goal) return;
    setOcupado(true);
    setErro('');
    try {
      const novo = await chamar(`/sentury/goals/${goal.id}/${acao}`, corpo);
      const encerrado = novo && (novo.estado === 'cumprido' || novo.estado === 'abandonado');
      setGoal(encerrado ? null : novo);
      setRecusando(false);
      setNota('');
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui falar com o servidor.');
    } finally {
      setOcupado(false);
    }
  };

  if (!goal) return null;

  const marcos = goal.marcos || [];
  const cabecalho: Record<Goal['estado'], string> = {
    proposto: 'Objetivo proposto',
    ativo: 'Perseguindo o objetivo',
    pausado: 'Objetivo pausado',
    aguardando_confirmacao: 'O agente diz que cumpriu',
    cumprido: 'Objetivo cumprido',
    abandonado: 'Objetivo encerrado',
  };
  const botao = 'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:opacity-50';

  return (
    <section className="mb-6 max-w-3xl rounded-xl border border-stone-300 bg-[#fffdf8] p-4 shadow-sm" aria-label="Objetivo da conversa">
      <header className="flex items-start gap-2">
        <Flag className="mt-0.5 h-4 w-4 shrink-0 text-gold-ink" />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
            {cabecalho[goal.estado]}
            {goal.estado === 'ativo' && goal.rodando ? <LoaderCircle className="ml-1.5 inline h-3 w-3 animate-spin text-indigo-500" /> : null}
          </p>
          <p className="mt-0.5 text-sm font-semibold text-zinc-900">{goal.objetivo}</p>
          <p className="mt-1 text-xs text-zinc-600"><span className="text-zinc-400">Pronto quando:</span> {goal.criterio}</p>
        </div>
      </header>

      {goal.estado !== 'proposto' ? (
        <p className="mt-3 text-xs tabular-nums text-zinc-500">
          Turno {goal.turnos} de {goal.limite_turnos}
          {marcos.length ? ` · ${goal.marcos_feitos}/${marcos.length} marcos` : ''}
          {' · '}{rotuloDoModo(goal.modo)}
        </p>
      ) : null}

      {marcos.length ? (
        <div className="mt-2">
          {goal.estado !== 'proposto' ? (
            <button type="button" className="text-[11px] text-zinc-500 underline-offset-2 hover:underline" onClick={() => setVerMarcos(v => !v)}>
              {verMarcos ? 'Esconder marcos' : 'Ver marcos'}
            </button>
          ) : null}
          {goal.estado === 'proposto' || verMarcos ? (
            <ul className="mt-1 space-y-0.5">
              {marcos.map((m, i) => (
                <li key={`${m.titulo}-${i}`} className="flex items-start gap-2 text-xs leading-5">
                  {m.feito ? <Check className="mt-1 h-3.5 w-3.5 shrink-0 text-emerald-600" /> : <Circle className="mt-1.5 h-2.5 w-2.5 shrink-0 text-zinc-300" />}
                  <span className={m.feito ? 'text-zinc-400 line-through' : 'text-zinc-700'}>{m.titulo}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {goal.estado === 'pausado' && goal.motivo ? (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">Parou: {goal.motivo}</p>
      ) : null}

      {goal.estado === 'aguardando_confirmacao' ? (
        <div className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
          <p className="mb-1 font-medium">Evidência</p>
          <Evidencia valor={goal.evidencia_final} />
        </div>
      ) : null}

      {erro ? <p className="mt-2 text-xs text-red-600">{erro}</p> : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {goal.estado === 'proposto' ? (
          <>
            <label className="text-xs text-zinc-500">
              Modelo{' '}
              <select value={modo} onChange={e => setModo(e.target.value)} className="rounded border border-stone-300 bg-white px-1.5 py-1 text-xs text-zinc-800">
                {MODOS.map(m => <option key={m.valor} value={m.valor}>{m.rotulo}</option>)}
              </select>
            </label>
            <span className="text-[11px] text-zinc-400">até {goal.limite_turnos} turnos · {goal.limite_horas} h</span>
            <div className="flex-1" />
            <button type="button" disabled={ocupado} onClick={() => agir('abandonar')} className={`${botao} text-zinc-600 hover:bg-stone-100`}>
              <X className="h-3.5 w-3.5" />Descartar
            </button>
            <button type="button" disabled={ocupado} onClick={() => agir('aprovar', { modo })} className={`${botao} bg-zinc-900 text-white hover:bg-zinc-800`}>
              <Play className="h-3.5 w-3.5" />Começar
            </button>
          </>
        ) : null}

        {goal.estado === 'ativo' ? (
          <>
            <div className="flex-1" />
            <button type="button" disabled={ocupado} onClick={() => agir('abandonar')} className={`${botao} text-zinc-600 hover:bg-stone-100`}>
              <X className="h-3.5 w-3.5" />Encerrar
            </button>
            <button type="button" disabled={ocupado} onClick={() => agir('pausar')} className={`${botao} border border-stone-300 text-zinc-800 hover:bg-stone-100`}
              title="Para depois do turno em curso">
              <OctagonPause className="h-3.5 w-3.5" />Pausar
            </button>
          </>
        ) : null}

        {goal.estado === 'pausado' ? (
          <>
            <div className="flex-1" />
            <button type="button" disabled={ocupado} onClick={() => agir('abandonar')} className={`${botao} text-zinc-600 hover:bg-stone-100`}>
              <X className="h-3.5 w-3.5" />Encerrar
            </button>
            <button type="button" disabled={ocupado} onClick={() => agir('retomar')} className={`${botao} bg-zinc-900 text-white hover:bg-zinc-800`}>
              <Play className="h-3.5 w-3.5" />Continuar
            </button>
          </>
        ) : null}

        {goal.estado === 'aguardando_confirmacao' && !recusando ? (
          <>
            <div className="flex-1" />
            <button type="button" disabled={ocupado} onClick={() => setRecusando(true)} className={`${botao} border border-stone-300 text-zinc-800 hover:bg-stone-100`}>
              Ainda não
            </button>
            <button type="button" disabled={ocupado} onClick={() => agir('confirmar', { cumprido: true })} className={`${botao} bg-emerald-700 text-white hover:bg-emerald-800`}>
              <Check className="h-3.5 w-3.5" />Cumprido
            </button>
          </>
        ) : null}
      </div>

      {goal.estado === 'aguardando_confirmacao' && recusando ? (
        <div className="mt-3">
          <textarea
            value={nota}
            onChange={e => setNota(e.target.value)}
            rows={2}
            maxLength={1000}
            placeholder="O que ainda falta? O agente lê isto e continua."
            className="w-full resize-none rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs text-zinc-800 outline-none focus:border-gold"
          />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" disabled={ocupado} onClick={() => setRecusando(false)} className={`${botao} text-zinc-600 hover:bg-stone-100`}>Voltar</button>
            <button type="button" disabled={ocupado || !nota.trim()} onClick={() => agir('confirmar', { cumprido: false, nota })}
              className={`${botao} bg-zinc-900 text-white hover:bg-zinc-800`}>
              <Play className="h-3.5 w-3.5" />Continuar trabalhando
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
};
