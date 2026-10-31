import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { MessageBubble } from '../chat/MessageBubble';
import { getRuntimeConfig } from '../../runtime/config';
import { Coruja } from './Coruja';
import { Esperando } from './Esperando';
import { atualizarHQ, coresDoAgente } from './useEsperando';
import { estadoDaCoruja, NOME_DO_ESTADO, nomeVisivel, residentes } from './api';
import { CampoDoResidente, type DestinoNaMesa } from './CampoDoResidente';
import type { Anexo } from '../chat/anexos';
import { EncaminhadoAMesa } from '../chat/EncaminhadoAosResidentes';
import { atualizarMesa } from './useMesa';
import { Digitando } from './Digitando';

type Conversa = Awaited<ReturnType<typeof residentes.conversa>>;

function tituloDaMesa(texto: string): string {
  const linha = texto.replace(/(?:^|\s)@[a-z][a-z0-9-]*/gi, ' ').trim().split('\n')[0].trim() || 'Assunto da conversa';
  return linha.length <= 80 ? linha : `${linha.slice(0, 79).trimEnd()}…`;
}

export default function ConversaDoResidente({ nome, onVoltar }: { nome: string; onVoltar?: () => void }) {
  const [dados, setDados] = useState<Conversa | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState('');
  // O pedido aparece na hora; antes ele só surgia depois da resposta, e parecia perdido.
  const [enviado, setEnviado] = useState<string | null>(null);
  // O que foi para a Mesa daqui: a conversa segue lá, e a linha leva até ela.
  const [naMesa, setNaMesa] = useState<{ id: string; titulo: string; acao: string }[]>([]);
  const feed = useRef<HTMLDivElement>(null);
  const carregar = useCallback(async () => {
    const nova = await residentes.conversa(nome);
    setDados(nova);
    setErro('');
  }, [nome]);
  useEffect(() => {
    let vivo = true;
    let ocupado = false;
    const ler = async () => {
      if (ocupado) return;
      ocupado = true;
      try {
        const nova = await residentes.conversa(nome);
        if (vivo) { setDados(nova); setErro(''); }
      } catch (e) {
        if (vivo) setErro(e instanceof Error ? e.message : 'Não consegui abrir a conversa.');
      } finally { ocupado = false; }
    };
    void ler();
    const timer = window.setInterval(() => void ler(), 3000);
    return () => { vivo = false; window.clearInterval(timer); };
  }, [nome]);
  const ultima = dados?.mensagens.at(-1)?.id;
  const trabalhando = Boolean(dados?.trabalhando) || Boolean(enviado);
  // A conversa desce também quando a pessoa envia e quando ele começa a escrever,
  // não só quando chega resposta: a mensagem dela não pode ficar fora da vista.
  useEffect(() => { feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: 'smooth' }); }, [ultima, enviado, trabalhando]);
  const enviar = async (texto: string, destino: DestinoNaMesa, anexos: Anexo[]): Promise<DestinoNaMesa | void> => {
    setEnviando(true);
    try {
      if (destino) {
        // Na Mesa, ele entra chamado: a conversa nasceu no chat dele.
        const fala = `@${nome} ${texto}`;
        const assunto = 'nova' in destino
          ? await residentes.abrirAssunto(tituloDaMesa(texto), fala)
          : await residentes.falarNoAssunto(destino.id, fala);
        setNaMesa(atual => [...atual, { id: assunto.id, titulo: assunto.titulo, acao: 'nova' in destino ? 'Abri' : 'Falei' }]);
        setErro('');
        void atualizarMesa();
        return { id: assunto.id, titulo: assunto.titulo };
      }
      setEnviado(texto);
      await residentes.pedirNaConversa(nome, texto, getRuntimeConfig().userId,
        anexos.map(anexo => ({ nome: anexo.nome, data_url: anexo.dataUrl! })));
      await carregar();
      atualizarHQ();
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'Não consegui enviar.');
      setEnviado(null);
      throw e;
    } finally { setEnviando(false); }
  };
  const agente = dados?.agente;
  // Quando o servidor já devolve o pedido, a cópia local sai.
  const enviadoNaLista = Boolean(enviado && dados?.mensagens.some(m => m.role === 'user' && (m.pedido_original ?? m.content).trim() === enviado));
  useEffect(() => { if (enviadoNaLista) setEnviado(null); }, [enviadoNaLista]);
  const estado = agente ? estadoDaCoruja(agente, dados.esperando) : 'dormindo';
  return <section className="flex h-full min-h-0 flex-col">
    <header className="flex shrink-0 items-center gap-3 border-b border-stone-200 px-6 py-3">
      {onVoltar ? <button type="button" onClick={onVoltar} aria-label="Voltar para a HQ"
        className="rounded-md p-1.5 text-zinc-500 hover:bg-stone-200 hover:text-zinc-900"><ArrowLeft className="h-4 w-4" /></button> : null}
      <Coruja tamanho={38} cores={coresDoAgente(agente)} acessorios={agente?.aparencia.acessorios} estado={estado} rotulo={nome} />
      <div className="min-w-0 flex-1"><h1 className="font-semibold">{nomeVisivel(nome)}</h1>
        <p className="truncate text-xs text-zinc-500">{agente?.papel}</p></div>
      <span className="text-xs text-zinc-500">{NOME_DO_ESTADO[estado]}</span>
    </header>
    <div ref={feed} className="min-h-0 flex-1 overflow-y-auto px-5 py-8">
      <div className="mx-auto max-w-4xl space-y-7">
        {dados?.mensagens.map(message => <MessageBubble key={message.id} message={message} naConversaDe={nome} />)}
        {enviado && !enviadoNaLista ? <MessageBubble message={{ id: 'enviado-agora', sessionId: '', role: 'user', content: enviado, timestamp: '' }} /> : null}
        {trabalhando ? <Digitando nome={nome} agente={agente} /> : null}
        {dados && !dados.mensagens.length && !enviado ? <p className="text-sm text-zinc-500">Peça uma tarefa a {nomeVisivel(nome)}.</p> : null}
        {naMesa.map((item, i) => (
          <EncaminhadoAMesa key={`${item.id}:${i}`} id={item.id} titulo={item.titulo}
            texto={`${item.acao} na Mesa: ${item.titulo}. A conversa segue por lá, e o resumo fica no assunto.`} />
        ))}
        {dados?.esperando.map(tarefa => <div key={tarefa.id} className="rounded-xl border border-amber-200 bg-amber-50">
          <Esperando tarefa={tarefa} agente={agente} onRespondida={() => { void carregar().catch(e => setErro(String(e))); atualizarHQ(); }} />
        </div>)}
      </div>
    </div>
    <div className="mx-auto mb-5 w-[calc(100%-2.5rem)] max-w-4xl shrink-0">
      {erro ? <p role="alert" className="mb-2 text-sm text-red-700">{erro}</p> : null}
      <CampoDoResidente nome={nome} skillsDele={agente?.skills || []} enviando={enviando} onEnviar={enviar}
        podeAnexar={Boolean(agente?.ferramentas.includes('ler_arquivo'))} mostrarAvisoDeAnexo={Boolean(agente)} onErro={setErro} />
    </div>
  </section>;
}
