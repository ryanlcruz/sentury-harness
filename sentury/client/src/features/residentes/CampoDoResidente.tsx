import React, { useEffect, useMemo, useRef, useState } from 'react';
import { LoaderCircle, Paperclip, Plus, Send, Sparkles, Users, X } from 'lucide-react';
import { lerAnexos, type Anexo } from '../chat/anexos';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { Coruja } from './Coruja';
import { coresDoAgente, useHQ } from './useEsperando';
import { nomeVisivel, residentes, type Agente, type Assunto } from './api';
import { CampoComTokens, type CampoComTokensHandle } from '../chat/CampoComTokens';
import { desenhoDeResidentes } from './selos';

/** Para onde a mensagem vai além do residente: um assunto aberto da Mesa ou uma
 * Mesa nova com ele. Sem destino, é tarefa para ele. */
export type DestinoNaMesa = { id: string; titulo: string } | { nova: true } | null;

interface Skill { name: string; description: string }

interface Opcao {
  chave: string;
  grupo: string;
  titulo: string;
  detalhe: string;
  escolher: () => void;
  agente?: Agente;
  icone?: 'mesa' | 'skill';
}

const GATILHO_ARROBA = /(?:^|\s)@([a-z0-9-]*)$/i;
const GATILHO_BARRA = /(?:^|\s)\/([a-z0-9-]*)$/i;

/** O campo do chat de um residente: `@` chama um colega para dentro do pedido ou
 * leva a conversa para a Mesa, e `/` cita uma skill, com as dele primeiro. */
export const CampoDoResidente: React.FC<{
  nome: string;
  skillsDele: string[];
  enviando: boolean;
  onEnviar: (texto: string, destino: DestinoNaMesa, anexos: Anexo[]) => Promise<DestinoNaMesa | void>;
  /** Ele só lê anexo com `ler_arquivo`; sem a ferramenta, o campo diz isso. */
  podeAnexar: boolean;
  mostrarAvisoDeAnexo: boolean;
  onErro: (mensagem: string) => void;
}> = ({ nome, skillsDele, enviando, onEnviar, podeAnexar, mostrarAvisoDeAnexo, onErro }) => {
  const hq = useHQ();
  const [texto, setTexto] = useState('');
  // O texto antes do cursor, já com os selos escritos como token: é onde o gatilho mora.
  const [antes, setAntes] = useState('');
  const [destino, setDestino] = useState<DestinoNaMesa>(null);
  const [indice, setIndice] = useState(0);
  const [fechado, setFechado] = useState(false);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [mesas, setMesas] = useState<Assunto[]>([]);
  const campo = useRef<CampoComTokensHandle>(null);
  const Nome = nomeVisivel(nome);
  const semLeitura = `${Nome} não lê anexos ainda: libere a ferramenta ler_arquivo na ficha dele.`;
  const [anexos, setAnexos] = useState<Anexo[]>([]);
  const [lendo, setLendo] = useState(false);
  const inputArquivo = useRef<HTMLInputElement>(null);
  const conversaAtual = useRef(nome);
  useEffect(() => { conversaAtual.current = nome; setAnexos([]); setLendo(false); }, [nome]);
  // A Mesa recebe só texto: o anexo vai com a tarefa do residente.
  const aceitaAnexo = podeAnexar && !destino;
  const anexar = async (arquivos: FileList | File[] | null) => {
    // Sem `ler_arquivo` ele não lê o anexo: o aviso vem quando a pessoa tenta, não o tempo todo.
    if (mostrarAvisoDeAnexo && !podeAnexar && arquivos?.length) {
      onErro(semLeitura);
      return;
    }
    if (!aceitaAnexo || enviando || lendo) return;
    const conversa = nome;
    setLendo(true);
    try {
      const { lidos, grandes } = await lerAnexos(arquivos);
      if (conversaAtual.current !== conversa) return;
      const legiveis = lidos.filter(item => Boolean(item.dataUrl));
      setAnexos(atual => [...atual, ...legiveis].slice(0, 6));
      onErro(grandes ? 'O arquivo passa de 8 MB.' : legiveis.length !== lidos.length ? 'Não consegui ler um dos arquivos; selecione-o novamente.' : '');
    } finally { if (conversaAtual.current === conversa) setLendo(false); }
  };

  const arroba = fechado ? null : antes.match(GATILHO_ARROBA);
  const barra = fechado || arroba ? null : antes.match(GATILHO_BARRA);

  useEffect(() => {
    void apiClient.get<{ skills?: unknown[] }>('/sentury/skills', { headers: authHeaders() }).then(resultado => {
      setSkills((resultado.skills || []).flatMap(valor => {
        const r = (valor || {}) as Record<string, unknown>;
        return typeof r.name === 'string' ? [{ name: r.name, description: typeof r.description === 'string' ? r.description : '' }] : [];
      }));
    }).catch(() => setSkills([]));
  }, []);
  const procurandoMesa = Boolean(arroba);
  useEffect(() => {
    if (!procurandoMesa) return;
    void residentes.assuntos().then(lista => setMesas(lista.filter(a => a.estado === 'aberto'))).catch(() => undefined);
  }, [procurandoMesa]);

  // Troca o gatilho digitado (`@ni`, `/gra`) pelo selo do que foi escolhido, ou só o apaga.
  const trocarGatilho = (_gatilho: string, inserido: string) => {
    if (inserido.trim()) campo.current?.inserirToken(inserido.trim());
    else campo.current?.apagarGatilho();
  };
  const desenhar = useMemo(() => desenhoDeResidentes(hq.agentes, skills.map(s => s.name)), [hq.agentes, skills]);
  const gatilhoDe = (achado: RegExpMatchArray) => achado[0].trimStart();

  const opcoes = useMemo((): Opcao[] => {
    if (arroba) {
      const termo = arroba[1].toLowerCase();
      const colegas = hq.agentes.filter(a => a.nome !== nome && a.nome.includes(termo)).slice(0, 6).map(agente => ({
        chave: `colega:${agente.nome}`, grupo: 'Colegas', titulo: `@${agente.nome}`, detalhe: agente.papel, agente,
        escolher: () => trocarGatilho(gatilhoDe(arroba), `@${agente.nome} `),
      }));
      const casaMesa = !termo || 'mesa'.startsWith(termo);
      const abertas = mesas.filter(a => casaMesa || a.titulo.toLowerCase().includes(termo)).slice(0, 4).map(assunto => ({
        chave: `mesa:${assunto.id}`, grupo: 'Mesa', titulo: assunto.titulo, icone: 'mesa' as const,
        detalhe: `${assunto.participantes.map(nomeVisivel).join(', ') || 'sem participantes ainda'} · ${assunto.falas.length} falas`,
        escolher: () => { trocarGatilho(gatilhoDe(arroba), ''); setDestino({ id: assunto.id, titulo: assunto.titulo }); },
      }));
      const nova = casaMesa ? [{
        chave: 'mesa:nova', grupo: 'Mesa', titulo: `Nova Mesa com ${Nome}`, icone: 'mesa' as const,
        detalhe: 'A próxima mensagem abre um assunto; cite colegas com @ para chamá-los',
        escolher: () => { trocarGatilho(gatilhoDe(arroba), ''); setDestino({ nova: true }); },
      }] : [];
      return [...colegas, ...abertas, ...nova];
    }
    if (barra) {
      const termo = barra[1].toLowerCase();
      const batem = skills.filter(s => s.name.includes(termo));
      const dele = batem.filter(s => skillsDele.includes(s.name));
      const outras = batem.filter(s => !skillsDele.includes(s.name));
      const virar = (grupo: string) => (s: Skill) => ({
        chave: `skill:${s.name}`, grupo, titulo: `/${s.name}`, detalhe: s.description, icone: 'skill' as const,
        escolher: () => trocarGatilho(gatilhoDe(barra), `/${s.name} `),
      });
      return [...dele.map(virar(`Skills de ${Nome}`)), ...outras.slice(0, Math.max(0, 8 - dele.length)).map(virar('Outras skills'))];
    }
    return [];
  }, [arroba?.[0], barra?.[0], hq.agentes, mesas, skills, skillsDele, nome, texto, antes]);
  useEffect(() => { setIndice(0); }, [arroba?.[1], barra?.[1]]);

  const enviar = async () => {
    const limpo = texto.trim();
    if (!limpo || enviando || lendo) return;
    const enviados = destino ? [] : anexos;
    setTexto('');
    try {
      const resultado = await onEnviar(limpo, destino, enviados);
      if (enviados.length) setAnexos([]);
      if (resultado !== undefined) setDestino(resultado);
    } catch {
      // O erro aparece acima do campo; o texto e os anexos ficam para não se perderem.
      setTexto(limpo);
    }
  };
  const aoTeclar = (event: React.KeyboardEvent<HTMLElement>) => {
    if (opcoes.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      setIndice(i => (i + (event.key === 'ArrowDown' ? 1 : -1) + opcoes.length) % opcoes.length);
      return;
    }
    if (opcoes.length && (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey))) {
      event.preventDefault();
      (opcoes[indice] || opcoes[0]).escolher();
      return;
    }
    if (opcoes.length && event.key === 'Escape') { setFechado(true); return; }
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void enviar(); }
  };

  const placeholder = destino && 'nova' in destino ? `O assunto da nova Mesa com ${Nome}…`
    : destino ? `Falar na Mesa: ${destino.titulo}…`
    : `Peça uma tarefa a ${Nome}… @ chama colega ou Mesa, / usa skill`;

  return (
    <div className="relative">
      {opcoes.length ? (
        <div className="absolute bottom-[calc(100%+8px)] left-0 z-20 max-h-72 w-full max-w-lg overflow-y-auto rounded-xl border border-[#d8cfbd] bg-[#fffdf8] p-1.5 shadow-[0_18px_46px_rgba(22,22,22,.16)]" role="listbox">
          {opcoes.map((opcao, i) => (
            <React.Fragment key={opcao.chave}>
              {i === 0 || opcoes[i - 1].grupo !== opcao.grupo
                ? <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-[.13em] text-zinc-500">{opcao.grupo}</p> : null}
              <button type="button" role="option" aria-selected={i === indice} onMouseDown={event => event.preventDefault()} onClick={opcao.escolher}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left ${i === indice ? 'bg-gold-soft' : 'hover:bg-stone-100'}`}>
                {opcao.agente ? <Coruja cores={coresDoAgente(opcao.agente)} acessorios={opcao.agente.aparencia.acessorios} tamanho={28} rotulo={opcao.agente.nome} />
                  : opcao.icone === 'mesa' ? <Users className="h-4 w-4 shrink-0 text-gold-ink" />
                  : <Sparkles className="h-4 w-4 shrink-0 text-gold-ink" />}
                <span className="min-w-0">
                  <span className="block truncate text-xs font-semibold text-zinc-900">{opcao.titulo}</span>
                  <span className="block truncate text-xs text-zinc-600">{opcao.detalhe}</span>
                </span>
              </button>
            </React.Fragment>
          ))}
        </div>
      ) : null}
      {destino ? (
        <div className="mb-1.5 flex">
          <span className="inline-flex h-7 items-center gap-1.5 rounded-full border border-gold bg-gold-soft/60 pl-2.5 pr-1 text-xs font-medium text-zinc-900">
            <Users className="h-3.5 w-3.5 text-gold-ink" />
            <span className="max-w-[320px] truncate">{'nova' in destino ? `Nova Mesa com ${Nome}` : `Na Mesa: ${destino.titulo}`}</span>
            <button type="button" onClick={() => setDestino(null)} aria-label="Voltar a falar só com ele" title={`Voltar a falar só com ${Nome}`}
              className="flex h-5 w-5 items-center justify-center rounded-full hover:bg-gold-soft"><X className="h-3 w-3" /></button>
          </span>
        </div>
      ) : null}
      {anexos.length ? <div className="mb-2 flex flex-wrap gap-2">{anexos.map((anexo, i) =>
        <span key={`${anexo.nome}-${i}`} className="flex max-w-full items-center gap-2 rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-xs">
          <Paperclip size={14} /><span className="max-w-48 truncate">{anexo.nome}</span>
          <button type="button" disabled={enviando} aria-label={`Remover ${anexo.nome}`}
            onClick={() => setAnexos(atual => atual.filter((_, j) => j !== i))} className="rounded p-1 hover:bg-stone-100"><X size={12} /></button>
        </span>)}</div> : null}
      <input ref={inputArquivo} type="file" multiple hidden disabled={enviando || lendo || !aceitaAnexo}
        onChange={event => { void anexar(event.target.files); event.target.value = ''; }} />
      <div onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); void anexar(event.dataTransfer.files); }}
        className="flex items-end gap-2 rounded-2xl border border-stone-300 bg-white py-1.5 pl-1.5 pr-1.5">
        <button type="button" aria-label="Anexar arquivos"
          title={destino ? 'Anexo vai com a tarefa do residente, não para a Mesa' : !podeAnexar && mostrarAvisoDeAnexo ? semLeitura : 'Anexar até 6 arquivos, até 8 MB cada'}
          disabled={(podeAnexar ? !aceitaAnexo : !mostrarAvisoDeAnexo) || lendo || enviando}
          onClick={() => (!podeAnexar && mostrarAvisoDeAnexo ? onErro(semLeitura) : inputArquivo.current?.click())}
          className="my-0.5 rounded-full p-2 text-zinc-500 hover:bg-stone-100 disabled:opacity-40">
          {lendo ? <LoaderCircle size={18} className="animate-spin" /> : <Plus size={18} />}
        </button>
        {/* Enter envia, Shift+Enter quebra a linha; @ e / viram selo, como no chat do Sentury. */}
        <div className="min-w-0 flex-1">
          <CampoComTokens ref={campo} valor={texto} desenhar={desenhar} placeholder={placeholder}
            onMudar={valor => { setTexto(valor); setFechado(false); }}
            onCursor={setAntes}
            onColarArquivos={arquivos => void anexar(arquivos)}
            onKeyDown={aoTeclar} />
        </div>
        <button type="button" onClick={() => void enviar()} disabled={enviando || lendo || !texto.trim()} aria-label="Enviar"
          className="shrink-0 rounded-xl bg-zinc-900 p-2.5 text-white disabled:opacity-40"><Send size={16} /></button>
      </div>
    </div>
  );
};
