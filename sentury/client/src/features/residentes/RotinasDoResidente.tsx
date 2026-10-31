import { useEffect, useState } from 'react';
import { Pause, Play, Trash2 } from 'lucide-react';
import { residentes, type Agente, type NovaRotina, type Rotina } from './api';
import { ConfirmDialog } from '../../components/ConfirmDialog';

const dataLegivel = (iso: string | null, fuso: string) => {
  if (!iso) return 'Pausada';
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? 'Horário indisponível' : data.toLocaleString('pt-BR', { timeZone: fuso });
};

export function RotinasDoResidente({ agente }: { agente: Agente }) {
  const [lista, setLista] = useState<Rotina[]>([]);
  const [erro, setErro] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const [pedido, setPedido] = useState('');
  const [tipo, setTipo] = useState('cron');
  const [quando, setQuando] = useState('0 9 * * 1');
  const [dia, setDia] = useState('1');
  const [hora, setHora] = useState('09:00');
  const [cronLivre, setCronLivre] = useState(false);
  const [apagando, setApagando] = useState<Rotina | null>(null);
  useEffect(() => {
    let vivo = true;
    let lendo = false;
    const carregar = async () => {
      if (lendo) return;
      lendo = true;
      try { const novas = await residentes.rotinas(agente.nome); if (vivo) setLista(novas); }
      catch (e) { if (vivo) setErro(e instanceof Error ? e.message : 'Não consegui ler as rotinas.'); }
      finally { lendo = false; }
    };
    void carregar();
    const timer = window.setInterval(() => void carregar(), 10000);
    return () => { vivo = false; window.clearInterval(timer); };
  }, [agente.nome]);
  const executar = async (acao: () => Promise<unknown>) => {
    setOcupado(true);
    setErro('');
    try { await acao(); setLista(await residentes.rotinas(agente.nome)); }
    catch (e) { setErro(e instanceof Error ? e.message : 'Não consegui alterar a rotina.'); }
    finally { setOcupado(false); }
  };
  const criar = async () => {
    const [horas, minutos] = hora.split(':').map(Number);
    const cron = cronLivre ? quando : `${minutos} ${horas} * * ${dia}`;
    const campos: NovaRotina = { pedido: pedido.trim(),
      ...(tipo === 'cron' ? { cron_expr: cron } : tipo === 'interval' ? { interval_sec: Number(quando) } : { run_at: quando }) };
    await residentes.criarRotina(agente.nome, campos);
    setPedido('');
  };
  const bloqueado = agente.estado === 'pausado' || agente.estado === 'aposentado';
  return <section aria-label="Rotinas" className="rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] p-4">
    <h2 className="mb-3 text-[13px] font-semibold">Rotinas</h2>
    {bloqueado ? <p className="mb-3 text-xs text-amber-800">Este residente está {agente.estado}. As rotinas não enfileiram tarefas.</p> : null}
    {lista.map(rotina => <div key={rotina.id} className="mb-3 border-b border-stone-200 pb-3 text-xs">
      <p className="font-medium">{rotina.rotulo}</p>
      <p className="mt-1 break-words text-zinc-700">{rotina.prompt}</p>
      <p className="mt-1 text-zinc-500">Próxima: {dataLegivel(rotina.proxima_execucao, rotina.fuso)} · {rotina.fuso}</p>
      {rotina.bloqueio || rotina.motivo ? <p className="mt-1 text-amber-800">{rotina.bloqueio || rotina.motivo}</p> : null}
      <div className="mt-2 flex gap-2">
        <button type="button" disabled={ocupado} onClick={() => void executar(() => residentes.mudarRotina(agente.nome, rotina.id, !rotina.active))}
          className="inline-flex items-center gap-1 rounded border border-stone-300 px-2 py-1.5 disabled:opacity-40">
          {rotina.active ? <Pause size={13} /> : <Play size={13} />}{rotina.active ? 'Pausar' : 'Retomar'}</button>
        <button type="button" disabled={ocupado} onClick={() => setApagando(rotina)} aria-label={`Apagar rotina: ${rotina.prompt}`}
          className="rounded border border-stone-300 px-2 py-1.5 disabled:opacity-40"><Trash2 size={13} /></button>
      </div>
    </div>)}
    {!lista.length ? <p className="mb-3 text-xs text-zinc-500">Nenhuma rotina agendada.</p> : null}
    {erro ? <p role="alert" className="mb-3 text-xs text-red-700">{erro}</p> : null}
    <details><summary className="cursor-pointer text-xs font-medium">Criar rotina</summary>
      <form className="mt-3 space-y-2" onSubmit={e => { e.preventDefault(); void executar(criar); }}>
        <label className="block text-xs">Tarefa<textarea required value={pedido} onChange={e => setPedido(e.target.value)} rows={2}
          className="mt-1 w-full rounded border border-stone-300 bg-white p-2" /></label>
        <label className="block text-xs">Quando<select value={tipo} onChange={e => { setTipo(e.target.value); setQuando(e.target.value === 'cron' ? '0 9 * * 1' : e.target.value === 'interval' ? '3600' : ''); }}
          className="mt-1 w-full rounded border border-stone-300 bg-white p-2">
          <option value="cron">Dias e horário</option><option value="interval">Intervalo</option><option value="once">Uma vez</option></select></label>
        {tipo === 'cron' && !cronLivre ? <div className="flex gap-2">
          <label className="min-w-0 flex-1 text-xs">Dias<select value={dia} onChange={e => setDia(e.target.value)}
            className="mt-1 w-full rounded border border-stone-300 bg-white p-2">
            <option value="*">Todo dia</option><option value="1">Segunda</option><option value="2">Terça</option>
            <option value="3">Quarta</option><option value="4">Quinta</option><option value="5">Sexta</option>
            <option value="6">Sábado</option><option value="0">Domingo</option></select></label>
          <label className="min-w-0 flex-1 text-xs">Horário<input required type="time" value={hora} onChange={e => setHora(e.target.value)}
            className="mt-1 w-full rounded border border-stone-300 bg-white p-2" /></label>
        </div> : <label className="block text-xs">{tipo === 'cron' ? 'Expressão cron' : tipo === 'interval' ? 'Intervalo em segundos (mínimo 30)' : 'Data e hora no fuso do servidor'}
          <input required type={tipo === 'once' ? 'datetime-local' : tipo === 'interval' ? 'number' : 'text'}
            min={tipo === 'interval' ? 30 : undefined} value={quando} onChange={e => setQuando(e.target.value)}
            className="mt-1 w-full rounded border border-stone-300 bg-white p-2" /></label>}
        {tipo === 'cron' ? <button type="button" className="block text-xs text-zinc-500 underline"
          onClick={() => setCronLivre(atual => !atual)}>{cronLivre ? 'Escolher dias e horário' : 'Usar expressão cron avançada'}</button> : null}
        <button type="submit" disabled={ocupado || !pedido.trim() || agente.estado === 'aposentado'}
          className="rounded bg-zinc-900 px-3 py-2 text-xs text-white disabled:opacity-40">Criar rotina</button>
      </form>
    </details>
    {apagando ? <ConfirmDialog open destructive title="Apagar rotina?" description={apagando.prompt} confirmLabel="Apagar"
      onCancel={() => setApagando(null)} onConfirm={() => { const id = apagando.id; setApagando(null); void executar(() => residentes.apagarRotina(agente.nome, id)); }} /> : null}
  </section>;
}
