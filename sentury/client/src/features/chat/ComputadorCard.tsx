import { useEffect, useState } from 'react';
import { Check, Flag, Hand, KeyRound, LoaderCircle, Monitor, Octagon, Power, TriangleAlert, Undo2 } from 'lucide-react';
import { useChatStore } from '../../stores/chat-store';
import { CartaoComputador, GESTOS_VISIVEIS, GestoComputador, VezDoComputador, teclasRecentes } from './computador';
import { SetaDoAgente } from './SetaDoAgente';
import { assumirComputador, devolverComputador, encerrarSuperficie, estadoDoComputador } from './superficie';

/**
 * O que a Sentury está fazendo no computador, mostrado no chat.
 *
 * A tela de verdade é o próprio computador, com a moldura: borda, pílula,
 * caixinha das mensagens e o balão ao lado do mouse. Aqui fica o
 * acompanhamento: o aviso de que ela está com o mouse e o teclado, o que está
 * fazendo agora (com as teclas recentes), os passos, quantos prints ela olhou,
 * e o Parar — o mesmo que Ctrl+Alt+Shift+S.
 *
 * Login, senha, código e CAPTCHA são da pessoa: a vez passa para ela quando a
 * Sentury pede ou quando ela aperta Assumir. Com a vez dela, a faixa diz o que
 * falta e oferece Devolver (tools/computador_vez.py).
 */

const ATALHO = 'Ctrl+Alt+Shift+S';
// Ler a tela ou a árvore de acessibilidade: usa o computador sem mexer nele.
const LEITURAS = new Set(['ver', 'elementos', 'janelas']);

function Icone({ status }: { status: string }) {
  if (status === 'ok') return <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />;
  if (status === 'rodando') return <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin text-gold-ink" />;
  if (status === 'parado') return <Octagon className="h-3.5 w-3.5 shrink-0 text-amber-700" />;
  return <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-amber-600" />;
}

function Passo({ gesto, atual }: { gesto: GestoComputador; atual: boolean }) {
  return (
    <li className={`flex items-center gap-2.5 rounded-lg px-2 py-1.5 ${atual ? 'bg-[#fff4b8]' : ''}`}>
      <span className="flex h-4 w-4 shrink-0 items-center justify-center"><Icone status={gesto.status} /></span>
      <span className={`w-40 shrink-0 truncate font-mono text-xs text-zinc-800 ${atual ? 'font-semibold' : 'font-medium'}`}>{gesto.titulo}</span>
      <span className="min-w-0 flex-1 truncate text-[12.5px] text-zinc-700">{gesto.detalhe}</span>
    </li>
  );
}

const ESTADOS: Record<string, { texto: string; classe: string }> = {
  rodando: { texto: 'em uso', classe: 'bg-emerald-50 text-emerald-800' },
  observando: { texto: 'observando', classe: 'bg-sky-50 text-sky-800' },
  pronta: { texto: 'pronto para continuar', classe: 'bg-sky-50 text-sky-800' },
  recibo: { texto: 'etapa concluída', classe: 'bg-stone-100 text-zinc-600' },
  parada: { texto: 'interrompido', classe: 'bg-amber-50 text-amber-800' },
  encerrada: { texto: 'sessão encerrada', classe: 'bg-stone-100 text-zinc-600' },
  vez: { texto: 'sua vez', classe: 'bg-amber-50 text-amber-900' },
};

const CONTINUAR = 'Pronto, devolvi o computador. Pode continuar.';

export function ComputadorCard({ cartao, sessionId, aoVivo = false, latest = false }: { cartao: CartaoComputador; sessionId: string; aoVivo?: boolean; latest?: boolean }) {
  const abortStreaming = useChatStore(state => state.abortStreaming);
  const sendMessage = useChatStore(state => state.sendMessage);
  const turnoRodando = useChatStore(state => Boolean(state.streams[sessionId]?.running));
  const [sessaoAberta, setSessaoAberta] = useState<boolean | null>(null);
  const [erroAoEncerrar, setErroAoEncerrar] = useState(false);
  // A vez que o servidor informou (ou que um clique acabou de mudar) vale
  // mais que a do cartão: o cartão guardado é de quando o turno acabou.
  const [vezAgora, setVezAgora] = useState<VezDoComputador | null>(null);
  const [erroNaVez, setErroNaVez] = useState(false);
  useEffect(() => {
    if (!latest || aoVivo) return;
    let ativo = true;
    void estadoDoComputador(sessionId)
      .then(estado => { if (ativo) { setSessaoAberta(estado.aberta); setVezAgora(estado.vez); } })
      .catch(() => { if (ativo) setSessaoAberta(null); });
    return () => { ativo = false; };
  }, [latest, aoVivo, sessionId]);
  const vez = vezAgora || cartao.vez || null;
  const daPessoa = (latest || aoVivo) && vez?.com === 'pessoa';
  const assumir = async () => {
    try {
      setVezAgora(await assumirComputador(sessionId));
      setErroNaVez(false);
    } catch {
      setErroNaVez(true);
    }
  };
  const devolver = async (continuar: boolean) => {
    try {
      setVezAgora(await devolverComputador(sessionId));
      setErroNaVez(false);
      if (continuar) await sendMessage(sessionId, CONTINUAR, [], ['computador']);
    } catch {
      setErroNaVez(true);
    }
  };
  const encerrar = async () => {
    try {
      await encerrarSuperficie('computador', sessionId);
      setSessaoAberta(false);
      setErroAoEncerrar(false);
    } catch {
      setErroAoEncerrar(true);
    }
  };
  const recentes = cartao.gestos.slice(-GESTOS_VISIVEIS);
  const escondidos = cartao.gestos.length - recentes.length;
  const atual = cartao.gestos[cartao.gestos.length - 1];
  const teclas = teclasRecentes(cartao);
  // Observando é o turno com @computador que ainda não leu nem mexeu: a moldura já está na tela.
  const rodando = aoVivo && (cartao.status === 'rodando' || cartao.status === 'observando') && !cartao.parado && !daPessoa;
  const soOlhando = !atual || LEITURAS.has(atual.acao);
  const gestos = cartao.gestos.filter(g => !LEITURAS.has(g.acao)).length;
  const statusDoCard = daPessoa ? 'vez' : !aoVivo && cartao.status === 'pronta'
    ? (latest && sessaoAberta === true ? 'pronta' : latest && sessaoAberta === false ? 'encerrada' : 'recibo')
    : rodando ? (soOlhando ? 'observando' : 'rodando') : cartao.status;
  const estado = ESTADOS[statusDoCard] || ESTADOS.recibo;
  const botao = 'inline-flex h-8 items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 text-xs font-medium text-zinc-800 hover:bg-stone-100';

  return (
    <section aria-label="Execução no computador" className="mb-5 max-w-3xl overflow-hidden rounded-[14px] border border-stone-300 bg-[#fffdf8] shadow-[0_10px_28px_rgba(24,24,27,.07)]">
      {rodando ? (
        <div className="flex items-center gap-2.5 bg-zinc-900 px-4 py-2 text-xs text-stone-50">
          <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-[#f5c400]" />
          <span>{soOlhando ? 'Estou olhando a sua tela, sem mexer em nada.' : 'Estou usando o seu mouse e o seu teclado.'}</span>
          <span className="flex-1" />
          <span className="text-stone-300">Aperte</span>
          <kbd className="rounded border border-zinc-600 px-1.5 py-px font-mono text-[11px] text-stone-50">{ATALHO}</kbd>
          <span className="text-stone-300">para parar</span>
        </div>
      ) : null}

      <header className="flex flex-wrap items-center gap-2.5 border-b border-stone-200 px-4 py-3">
        <Monitor className="h-4 w-4 text-gold-ink" />
        <span className="text-[13px] font-semibold text-zinc-900">Computador</span>
        {cartao.retomada ? <span className="text-[11px] text-zinc-500">continuação</span> : null}
        {cartao.janela ? (
          <span className="max-w-[18rem] truncate rounded-md bg-stone-100 px-2 py-0.5 font-mono text-xs text-zinc-600">janela: {cartao.janela}</span>
        ) : null}
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${estado.classe}`}>
          {rodando ? <span className="h-[7px] w-[7px] animate-pulse rounded-full bg-emerald-600" /> : null}
          {estado.texto}
        </span>
        <span className="flex-1" />
        {rodando ? (
          <>
            <button type="button" onClick={() => void assumir()} className={botao}
              title="Para o turno e deixa o computador com você: a Sentury não vê nem mexe até você devolver">
              <KeyRound className="h-3.5 w-3.5" />Assumir
            </button>
            <button type="button" onClick={() => abortStreaming(sessionId)} className={botao}
              title="Para o turno: nenhum gesto roda depois, e a moldura sai da tela">
              <Hand className="h-3.5 w-3.5" />Parar
            </button>
          </>
        ) : null}
        {latest && !aoVivo && sessaoAberta ? (
          <button type="button" onClick={() => void encerrar()} className={botao}
            title="Libera o computador para outra conversa; não fecha os aplicativos abertos">
            <Power className="h-3.5 w-3.5" />Liberar sessão
          </button>
        ) : null}
      </header>

      {erroAoEncerrar ? <p role="alert" className="px-4 py-2 text-xs text-red-700">Não consegui liberar a sessão. Tente novamente.</p> : null}

      {daPessoa ? (
        <div data-testid="vez-da-pessoa" className="flex flex-wrap items-center gap-3 border-b border-amber-200 bg-amber-50 px-4 py-3">
          <span className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[9px] bg-amber-100">
            <KeyRound className="h-4 w-4 text-amber-800" />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-[11px] font-semibold uppercase tracking-[.06em] text-amber-800">Sua vez</span>
            <span className="text-[13.5px] font-semibold text-zinc-900">{vez?.motivo || 'o computador está com você'}</span>
            <span className="text-xs text-zinc-600">A Sentury não vê nem mexe na tela até você devolver.</span>
          </div>
          {turnoRodando ? (
            <button type="button" onClick={() => void devolver(false)} className={botao}>
              <Undo2 className="h-3.5 w-3.5" />Devolver
            </button>
          ) : (
            <>
              <button type="button" onClick={() => void devolver(false)} className={botao}
                title="A vez volta para a Sentury, sem mandar mensagem">
                Só devolver
              </button>
              <button type="button" onClick={() => void devolver(true)}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-zinc-900 px-3 text-xs font-medium text-white hover:bg-zinc-800"
                title="A vez volta para a Sentury e ela continua de onde parou">
                <Undo2 className="h-3.5 w-3.5" />Devolver e continuar
              </button>
            </>
          )}
        </div>
      ) : null}
      {erroNaVez ? <p role="alert" className="px-4 py-2 text-xs text-red-700">Não consegui trocar a vez. Tente novamente.</p> : null}

      {cartao.objetivo ? (
        <div className="flex items-center gap-2.5 border-b border-stone-200 bg-[#fbfaf6] px-4 py-2 text-xs text-zinc-600">
          <Flag className="h-3.5 w-3.5 text-gold-ink" />
          <span className="font-semibold text-zinc-900">Objetivo: {cartao.objetivo}</span>
          {cartao.turno ? <span>turno {cartao.turno}{cartao.limite ? ` de ${cartao.limite}` : ''}</span> : null}
        </div>
      ) : null}

      {atual ? (
        <div className="flex items-center gap-3 border-b border-[#f3e8b0] bg-[#fffbe6] px-4 py-3.5">
          <span className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[9px] bg-zinc-900"><SetaDoAgente /></span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-[11px] font-semibold uppercase tracking-[.06em] text-gold-ink">{rodando ? 'Agora' : 'Último passo'}</span>
            <span className="truncate text-[15px] font-semibold text-zinc-900">{atual.titulo}</span>
            {atual.detalhe ? <span className="truncate text-xs text-zinc-600">{atual.detalhe}</span> : null}
          </div>
          {teclas.length ? (
            <div className="flex items-center gap-1.5">
              {teclas.map((t, i) => (
                <kbd key={i} className={`inline-flex h-7 min-w-[28px] items-center justify-center rounded-md border border-b-[3px] px-1.5 font-mono text-xs font-medium text-zinc-800 ${t.agora ? 'border-[#c99f00] bg-[#fff4b8]' : 'border-zinc-300 bg-white'}`}>{t.nome}</kbd>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <ol className="flex flex-col gap-0.5 px-3 py-2.5">
        {escondidos > 0 ? (
          <li className="px-2 py-1 text-[11px] text-zinc-400">{escondidos} gesto{escondidos > 1 ? 's' : ''} antes</li>
        ) : null}
        {recentes.map((gesto, i) => (
          <Passo key={escondidos + i} gesto={gesto} atual={escondidos + i === cartao.gestos.length - 1 && gesto.status === 'rodando'} />
        ))}
      </ol>

      <footer className="flex items-center gap-4 border-t border-stone-200 bg-[#fbfaf6] px-4 py-2.5 text-xs text-zinc-600">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-emerald-600" />{cartao.leituras || 0} leitura{cartao.leituras === 1 ? '' : 's'} em texto</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-amber-500" />{cartao.prints} {cartao.prints === 1 ? 'leitura visual' : 'leituras visuais'}</span>
        <span className="text-zinc-400">texto quando basta</span>
        <span className="flex-1" />
        <span className="font-mono text-[11px] text-zinc-500">{gestos} gesto{gestos === 1 ? '' : 's'}</span>
      </footer>
    </section>
  );
}
