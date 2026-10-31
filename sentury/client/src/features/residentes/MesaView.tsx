import { useEffect, useMemo, useRef, useState } from 'react';
import { Users, Plus, SendHorizontal, CheckCircle2, Trash2, Check } from 'lucide-react';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { renderMarkdown } from '../../domain/markdown';
import { Coruja } from './Coruja';
import { atualizarHQ, coresDoAgente, useHQ } from './useEsperando';
import { acompanharAgora, atualizarMesa, useMesa } from './useMesa';
import { nomeVisivel, residentes } from './api';
import { Digitando } from './Digitando';
import { Esperando } from './Esperando';
import { CampoComTokens, type CampoComTokensHandle } from '../chat/CampoComTokens';
import { desenhoDeResidentes } from './selos';

const ESTADO_DO_PASSO: Record<string, { rotulo: string; classe: string }> = {
  na_fila: { rotulo: 'na fila', classe: 'bg-stone-100 text-zinc-600' },
  rodando: { rotulo: 'trabalhando', classe: 'bg-amber-100 text-amber-800' },
  esperando: { rotulo: 'esperando', classe: 'bg-amber-100 text-amber-800' },
  feita: { rotulo: 'feita', classe: 'bg-emerald-100 text-emerald-800' },
  falhou: { rotulo: 'falhou', classe: 'bg-red-100 text-red-700' },
  cancelada: { rotulo: 'cancelada', classe: 'bg-stone-100 text-zinc-500' },
};

export default function MesaView({ embutida = false, inicial = null }: { embutida?: boolean; inicial?: string | null }) {
  const mesa = useMesa();
  const hq = useHQ();
  const [escolhido, escolher] = useState<string | null>(inicial);
  const [fala, setFala] = useState('');
  // O texto antes do cursor: é nele que o `@` digitado abre as sugestões.
  const [antes, setAntes] = useState('');
  const campo = useRef<CampoComTokensHandle>(null);
  const [novo, setNovo] = useState(false);
  const [titulo, setTitulo] = useState('');
  const [texto, setTexto] = useState('');
  const [resumo, setResumo] = useState('');
  const [fechando, setFechando] = useState(false);
  const [ocupada, setOcupada] = useState(false);
  const [erro, setErro] = useState('');
  const [apagando, setApagando] = useState(false);
  const fim = useRef<HTMLDivElement>(null);
  const assunto = mesa.assuntos.find(a => a.id === escolhido);
  const acao = async (executar: () => Promise<void>) => {
    if (ocupada) return;
    setOcupada(true);
    try { await executar(); await atualizarMesa(); setErro(''); }
    catch (e) { setErro(e instanceof Error ? e.message : 'Não consegui atualizar o assunto.'); }
    finally { setOcupada(false); }
  };
  const falas = assunto ? [
    ...assunto.falas.map((f, i) => ({ ...f, passou: false, id: `fala:${i}` })),
    ...mesa.eventos.filter(e => e.assunto === assunto.id && e.tipo === 'mesa_passou')
      .map(e => ({ de: e.agente, para: '', texto: e.motivo, em: e.em, passou: true, id: `passou:${e.em}:${e.agente}` })),
  ].sort((a, b) => a.em - b.em) : [];
  const total = falas.length + (assunto?.estado === 'fechado' ? 1 : 0);
  // Conversa nova chegando desce a tela até ela, como num chat.
  const fechado = assunto?.estado === 'fechado';
  // Quem já pegou a vez escreve; quem está na fila ainda não começou.
  const escrevendo = assunto && !fechado ? assunto.vez.filter(v => v.estado === 'rodando').map(v => v.agente) : [];
  const papelDe = (nome: string) => assunto?.vez.find(v => v.agente === nome)?.papel;
  const desdeDe = (nome: string) => assunto?.vez.find(v => v.agente === nome && v.estado === 'rodando')?.desde;
  const emLista = (nomes: string[]) => nomes.map(nomeVisivel).join(', ').replace(/, ([^,]*)$/, ' e $1');
  const entraram = assunto ? assunto.participantes.filter(n => n !== 'pessoa') : [];
  const deFora = assunto ? assunto.ficaram_de_fora : [];
  const ACAO: Record<string, string> = { mediando: 'mediando a rodada', resumindo: 'escrevendo o resumo' };
  const naFila = assunto && !fechado ? assunto.vez.filter(v => v.estado === 'na_fila').map(v => v.agente) : [];
  // Quem parou pedindo autorização: o cartão aparece aqui, onde a conversa está, e não só na aba da HQ.
  const esperandoAutorizacao = assunto && !fechado ? assunto.vez.filter(v => v.estado === 'esperando') : [];
  const ultimaFala = falas.filter(f => !f.passou).at(-1);
  const esperandoVoce = Boolean(assunto && !fechado && !assunto.fechando && !assunto.vez.length
    && mesa.eventos.filter(e => e.assunto === assunto.id).at(-1)?.tipo === 'mesa_sua_vez');
  const quemResume = assunto ? (assunto.aberto_por !== 'pessoa' ? assunto.aberto_por : assunto.falas.find(f => f.de !== 'pessoa')?.de) : undefined;
  useEffect(() => { fim.current?.scrollIntoView({ block: 'end' }); }, [escolhido, total, escrevendo.join(), naFila.join(), esperandoVoce, esperandoAutorizacao.length]);
  const enviar = () => {
    if (!assunto || !fala.trim()) return;
    void acao(async () => { await residentes.falarNoAssunto(assunto.id, fala.trim()); setFala(''); acompanharAgora(); });
  };
  // `@` antes do cursor abre as sugestões; quem é chamado vira o selo com a coruja.
  const arroba = /(?:^|\s)@([a-z0-9-]*)$/i.exec(antes);
  const sugestoes = arroba ? hq.agentes.filter(a => a.nome.startsWith(arroba[1].toLowerCase())).slice(0, 6) : [];
  const chamar = (nome: string) => campo.current?.inserirToken(`@${nome}`);
  const desenhar = useMemo(() => desenhoDeResidentes(hq.agentes), [hq.agentes]);

  return <section className="flex h-full min-h-0 flex-col">
    <header className="flex shrink-0 items-center gap-3 border-b border-stone-200 px-6 py-4">
      {embutida
        ? <p className="flex-1 text-sm text-zinc-600">O que os residentes conversam entre si. Você lê, fala, abre assunto e fecha.</p>
        : <><Users className="text-gold-ink" size={24} /><div className="flex-1"><h1 className="font-semibold">Mesa</h1><p className="text-xs text-zinc-500">Conversa dos residentes · você fala quando quiser</p></div></>}
      <button type="button" onClick={() => setNovo(true)} className="flex items-center gap-1 rounded-lg border px-3 py-2 text-sm"><Plus size={16} />Novo assunto</button>
    </header>
    <div className="grid min-h-0 flex-1 md:grid-cols-[260px_minmax(0,1fr)]">
      <nav aria-label="Assuntos da Mesa" className="min-h-0 space-y-2 overflow-y-auto border-r border-stone-200 p-4">
        {novo ? <form className="space-y-2 rounded-xl border bg-white p-3" onSubmit={e => {
          e.preventDefault(); void acao(async () => { const criado = await residentes.abrirAssunto(titulo.trim(), texto.trim()); escolher(criado.id); setNovo(false); setTitulo(''); setTexto(''); });
        }}>
          <label className="block text-sm">Título<input required maxLength={200} value={titulo} onChange={e => setTitulo(e.target.value)} className="mt-1 block w-full rounded border p-2" /></label>
          <label className="block text-sm">Texto<textarea maxLength={2000} value={texto} onChange={e => setTexto(e.target.value)} placeholder="Use @nome para chamar um residente." className="mt-1 block w-full rounded border p-2" /></label>
          <button disabled={ocupada || !titulo.trim()} className="rounded bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-40">Abrir assunto</button>
          <button type="button" onClick={() => setNovo(false)} className="ml-3 text-sm">Cancelar</button>
        </form> : null}
        {mesa.assuntos.map(a => <button key={a.id} type="button" aria-pressed={a.id === escolhido} onClick={() => { escolher(a.id); setFechando(false); setResumo(''); }}
          className={`block w-full rounded-xl border p-3 text-left ${a.id === escolhido ? 'border-gold bg-gold-soft' : 'bg-white'}`}>
          <span className="block text-sm font-medium">{a.titulo}</span><span className="text-xs text-zinc-500">{a.estado === 'aberto' ? 'Aberto' : 'Fechado'} · {a.falas.length} falas</span>
        </button>)}
        {!mesa.assuntos.length && !novo && !mesa.erro ? <p className="text-sm text-zinc-500">Nenhum assunto na Mesa.</p> : null}
      </nav>

      {assunto ? <article className="flex min-h-0 min-w-0 flex-col">
        <div className="flex shrink-0 items-start gap-3 border-b border-stone-200 px-6 py-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate font-semibold">{assunto.titulo}</h2>
            <p className="text-xs text-zinc-500">Aberto por {assunto.aberto_por === 'pessoa' ? 'você' : nomeVisivel(assunto.aberto_por)} · {assunto.participantes.map(nomeVisivel).join(', ') || 'chamando os residentes'}
              {assunto.custo.vezes ? <span title="Turnos de fala nesta conversa e o custo deles, somado ao dos próximos passos"> · {assunto.custo.vezes} {assunto.custo.vezes === 1 ? 'vez' : 'vezes'}{assunto.custo.usd ? ` · US$ ${assunto.custo.usd.toFixed(2).replace('.', ',')}` : ''}</span> : null}</p>
          </div>
          {fechado
            ? <span className="flex items-center gap-1 text-xs text-zinc-500"><CheckCircle2 size={14} />Fechado</span>
            : <button type="button" onClick={() => setFechando(f => !f)} className="rounded-lg border px-3 py-1.5 text-sm">Fechar</button>}
          <button type="button" onClick={() => setApagando(true)} aria-label="Apagar assunto" title="Apagar assunto"
            className="rounded-lg border px-2 py-1.5 text-zinc-500 hover:border-red-300 hover:text-red-700"><Trash2 size={16} /></button>
        </div>
        <ConfirmDialog open={apagando} destructive title="Apagar este assunto?"
          description="A conversa sai da Mesa, a fala que esperava a vez é cancelada e a decisão registrada a partir dele é apagada. O que cada residente anotou na própria memória fica."
          confirmLabel="Apagar" onCancel={() => setApagando(false)}
          onConfirm={() => { setApagando(false); void acao(async () => { await residentes.apagarAssunto(assunto.id); escolher(null); }); }} />

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {(erro || mesa.erro) ? <p role="alert" className="mb-4 text-sm text-red-700">{erro || mesa.erro}</p> : null}
          <ol className="mx-auto max-w-3xl space-y-4">
            {assunto.texto ? <li className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl bg-zinc-900 px-4 py-3 text-sm text-white" dangerouslySetInnerHTML={{ __html: renderMarkdown(assunto.texto) }} />
            </li> : null}
            {entraram.length ? <li className="text-center text-xs text-zinc-500">
              {emLista(entraram)} {entraram.length === 1 ? 'entrou' : 'entraram'} na conversa
            </li> : null}
            {deFora.length && !fechado ? <li className="text-center text-xs text-zinc-400">
              {emLista(deFora)} {deFora.length === 1 ? 'ficou' : 'ficaram'} de fora: o assunto não pareceu da área.
              Chame {deFora.map(n => `@${n}`).join(' ')} para trazer.
            </li> : null}
            {falas.map(f => {
              if (f.passou) return <li key={f.id} className="text-center text-xs text-zinc-400">{nomeVisivel(f.de)} passou a vez{f.texto ? ` (${f.texto})` : ''}</li>;
              if (f.de === 'pessoa') return <li key={f.id} className="flex justify-end">
                <div className="max-w-[80%] rounded-2xl bg-zinc-900 px-4 py-3 text-sm text-white" dangerouslySetInnerHTML={{ __html: renderMarkdown(f.texto) }} />
              </li>;
              const agente = hq.agentes.find(a => a.nome === f.de);
              return <li key={f.id} className="flex gap-3">
                <Coruja tamanho={32} rotulo={f.de} cores={coresDoAgente(agente)} acessorios={agente?.aparencia.acessorios} estado="parado" />
                <div className="min-w-0 max-w-[85%]">
                  <p className="text-sm font-medium">{nomeVisivel(f.de)}{f.para ? <span className="font-normal text-zinc-500"> → {nomeVisivel(f.para)}</span> : null}</p>
                  <div className="mt-1 text-sm" dangerouslySetInnerHTML={{ __html: renderMarkdown(f.texto) }} />
                </div>
              </li>;
            })}
            {ultimaFala?.de === 'pessoa' && !fechado ? <li className="-mt-2 flex justify-end">
              <span className="flex items-center gap-1 text-[11px] text-zinc-500">
                <Check size={12} />{escrevendo.length ? `${escrevendo.map(nomeVisivel).join(', ')} pegou e está respondendo`
                  : naFila.length ? `Entregue · na fila de ${naFila.map(nomeVisivel).join(', ')}` : 'Entregue'}
              </span>
            </li> : null}
            {escrevendo.map(nome => <li key={`vez:${nome}`}><Digitando nome={nome} agente={hq.agentes.find(a => a.nome === nome)} acao={ACAO[papelDe(nome) ?? '']} desde={desdeDe(nome)} /></li>)}
            {esperandoAutorizacao.map(v => {
              const tarefa = hq.esperando.find(t => t.id === v.tarefa);
              return <li key={`espera:${v.agente}`}>
                <section aria-label={`${nomeVisivel(v.agente)} espera sua autorização`} className="overflow-hidden rounded-xl border border-amber-200 bg-[#fffbea]">
                  {tarefa
                    ? <Esperando tarefa={tarefa} agente={hq.agentes.find(a => a.nome === v.agente)}
                        onRespondida={() => { atualizarHQ(); acompanharAgora(); void atualizarMesa(); }} />
                    : <p className="px-5 py-4 text-sm">{nomeVisivel(v.agente)} parou e espera sua autorização.</p>}
                </section>
              </li>;
            })}
            {esperandoVoce ? <li className="text-center text-xs text-zinc-500">Todos falaram. A vez é sua: responda, chame alguém com @ ou feche o assunto.</li> : null}
            {fechado ? <li><section aria-label="Decisão do assunto" className="rounded-xl border border-gold bg-gold-soft p-4">
              <h3 className="text-sm font-semibold">Decisão</h3>
              <div className="mt-1 text-sm" dangerouslySetInnerHTML={{ __html: renderMarkdown(assunto.resumo || 'Sem resumo.') }} />
              <p className="mt-2 text-[11px] text-zinc-600">Registrada em Decisões e na memória de quem participou. Falar aqui reabre o assunto.</p>
            </section></li> : null}
            {assunto.encaminhadas.length ? <li><section aria-label="Próximos passos" className="rounded-xl border border-stone-200 bg-white p-4">
              <h3 className="text-sm font-semibold">Próximos passos</h3>
              <ul className="mt-2 divide-y divide-stone-100">
                {assunto.encaminhadas.map(passo => {
                  const agente = hq.agentes.find(a => a.nome === passo.agente);
                  return <li key={passo.id} className="py-2">
                    <details>
                      <summary className="flex cursor-pointer list-none items-center gap-2">
                        <Coruja tamanho={22} rotulo={passo.agente} cores={coresDoAgente(agente)} acessorios={agente?.aparencia.acessorios} estado="parado" />
                        <span className="min-w-0 flex-1 truncate text-sm"><strong className="font-medium">{nomeVisivel(passo.agente)}</strong> · {passo.pedido}</span>
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${ESTADO_DO_PASSO[passo.estado]?.classe ?? 'bg-stone-100 text-zinc-600'}`}>
                          {ESTADO_DO_PASSO[passo.estado]?.rotulo ?? passo.estado}
                        </span>
                      </summary>
                      <p className="mt-2 whitespace-pre-wrap pl-8 text-xs text-zinc-700">{passo.pedido}</p>
                      {passo.resposta ? <div className="mt-2 pl-8 text-xs text-zinc-700" dangerouslySetInnerHTML={{ __html: renderMarkdown(passo.resposta) }} /> : null}
                    </details>
                  </li>;
                })}
              </ul>
            </section></li> : null}
          </ol>
          <div ref={fim} />
        </div>

        <div className="shrink-0 border-t border-stone-200 px-6 py-3">
          {fechando && !fechado ? <form className="mx-auto mb-2 flex max-w-3xl items-end gap-2" onSubmit={e => { e.preventDefault(); void acao(async () => { await residentes.fecharAssunto(assunto.id, resumo); setFechando(false); setResumo(''); }); }}>
            <textarea value={resumo} maxLength={2000} rows={2} onChange={e => setResumo(e.target.value)}
              placeholder={quemResume ? `Resumo do que se concluiu. Vazio, ${nomeVisivel(quemResume)} escreve.` : 'Resumo do que se concluiu'}
              className="block min-w-0 flex-1 rounded-lg border p-2 text-sm" />
            <button disabled={ocupada} className="rounded-lg bg-zinc-900 px-3 py-2 text-sm text-white">Fechar assunto</button>
          </form> : null}
          {/* A fala da pessoa chama quem ela marcou com @, ou a mesa toda; num assunto fechado, ela o retoma. */}
          {sugestoes.length ? <ul role="listbox" aria-label="Chamar na Mesa" className="mx-auto mb-2 flex max-w-3xl flex-wrap gap-1.5">
            {sugestoes.map((a, i) => <li key={a.nome}><button type="button" role="option" aria-selected={i === 0} onClick={() => chamar(a.nome)}
              className={`rounded-full border px-3 py-1 text-xs ${i === 0 ? 'border-gold bg-gold-soft' : 'border-stone-300 bg-white'}`}>@{a.nome} · {a.papel}</button></li>)}
          </ul> : null}
          <form className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-stone-300 bg-white p-2" onSubmit={e => { e.preventDefault(); enviar(); }}>
            <div className="min-w-0 flex-1">
              <CampoComTokens ref={campo} valor={fala} onMudar={setFala} onCursor={setAntes} desenhar={desenhar}
                onColarArquivos={() => setErro('A Mesa recebe só texto; o anexo vai pelo chat do residente.')}
                onKeyDown={e => {
                  if (sugestoes.length && (e.key === 'Tab' || e.key === 'Enter')) { e.preventDefault(); chamar(sugestoes[0].nome); return; }
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(); }
                }}
                placeholder={fechado ? 'Retome o assunto: sua fala reabre a conversa. @nome chama alguém.' : 'Fale na Mesa. @nome chama alguém; sem @, a mesa toda responde.'} />
            </div>
            <button aria-label={fechado ? 'Retomar' : 'Enviar'} disabled={ocupada || !fala.trim()}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-zinc-900 text-white disabled:opacity-30"><SendHorizontal size={18} /></button>
          </form>
        </div>
      </article> : <p className="p-6 text-sm text-zinc-500">Escolha um assunto para acompanhar a conversa.</p>}
    </div>
  </section>;
}
