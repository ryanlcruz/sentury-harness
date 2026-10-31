import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { PastaAtiva } from './PastaAtiva';
import { CampoComTokens, type CampoComTokensHandle } from './CampoComTokens';
import { ChevronDown, ChevronRight, ChevronUp, Hand, ListPlus, Mic, Paperclip, PhoneCall, Plus, Send, SlidersHorizontal, Square, Users, X, Zap } from 'lucide-react';
import {
  authHeaders,
  getRuntimeConfig,
  SenturyEffort,
  SenturyMode,
  setRuntimeEffort,
  setRuntimeMode,
} from '../../runtime/config';
import { useChatStore } from '../../stores/chat-store';
import { useSessionStore } from '../../stores/session-store';
import { apiClient } from '../../transport/http-client';
import { ContextGauge } from './ContextGauge';
import { IconeModo, IconeEsforco } from '../../components/ModeEffortIcons';
import { QuickCommandSheet } from '../../components/QuickCommandSheet';
import { Dictation, dictationSupported } from '../../runtime/dictation';
import { useVoiceCallEnabled } from '../../runtime/preferences';
import { CallOverlay } from './CallOverlay';
import { FUNCOES_NATIVAS, funcaoPorId, funcoesDoEnvio, lerAcessos, salvarAcessos, type FuncaoNativa } from '../../runtime/funcoes-nativas';
import { IconeDaFuncao } from './IconeDaFuncao';
import { Coruja } from '../residentes/Coruja';
import { lerAnexos, type Anexo } from './anexos';
import { coresDoAgente } from '../residentes/useEsperando';
import { residentes, nomeVisivel, type Agente, type Assunto } from '../residentes/api';
import { abrirAssuntoDaMesa } from '../residentes/abrirConversa';
import { seloDaSkill, seloDoResidente } from '../residentes/selos';
import { lerInterlocutores, lerMesaDaConversa, mencoesIniciais, salvarInterlocutores, salvarMesaDaConversa,
  type MesaDaConversa } from '../../runtime/interlocutores';

// Com quem a pessoa falou por último, para o `@` sozinho mostrar só esses.
const CHAVE_RECENTES = 'sentury_residentes_recentes';
const RESIDENTES_SEM_BUSCA = 3;

function lerRecentes(): string[] {
  try {
    const bruto = JSON.parse(window.localStorage.getItem(CHAVE_RECENTES) || '[]') as unknown;
    return Array.isArray(bruto) ? bruto.filter((nome): nome is string => typeof nome === 'string') : [];
  } catch {
    return [];
  }
}

function marcarRecentes(nomes: string[]): void {
  if (!nomes.length) return;
  try {
    const resto = lerRecentes().filter(nome => !nomes.includes(nome));
    window.localStorage.setItem(CHAVE_RECENTES, JSON.stringify([...nomes, ...resto].slice(0, 20)));
  } catch {
    // Sem storage o `@` mostra os primeiros da lista.
  }
}

interface SkillSuggestion {
  name: string;
  description: string;
  family?: string;
}

interface ComposerProps {
  hasConversation: boolean;
  onOpenQuickSheet?: () => void;
  isQuickSheetOpen?: boolean;
  onCloseQuickSheet?: () => void;
  /** Leva para o Harness, onde a pasta de trabalho de fato se escolhe. */
  onOpenHarness?: () => void;
  onOpenBrowserSettings?: () => void;
  /** Mantem o feed e o atalho de rolagem acima da altura real do composer. */
  onHeightChange?: (height: number) => void;
}

interface EstadoPermissoes {
  permitir_tudo: boolean;
}

export const Composer: React.FC<ComposerProps> = ({
  hasConversation,
  onOpenQuickSheet,
  isQuickSheetOpen = false,
  onCloseQuickSheet = () => undefined,
  onOpenHarness,
  onOpenBrowserSettings,
  onHeightChange,
}) => {
  const [input, setInput] = useState('');
  const initialRuntime = getRuntimeConfig();
  const [mode, setMode] = useState<SenturyMode>(initialRuntime.mode);
  const [effort, setEffort] = useState<SenturyEffort>(initialRuntime.effort);
  const [openPicker, setOpenPicker] = useState<'add' | 'intelligence' | 'permission' | 'contexto' | 'navegador' | 'enviar' | null>(null);
  const [menuMaxHeight, setMenuMaxHeight] = useState(360);
  const [permissionMode, setPermissionMode] = useState<'manual' | 'auto'>('manual');
  const [permissionSaving, setPermissionSaving] = useState(false);
  const [permissionError, setPermissionError] = useState('');
  const [skills, setSkills] = useState<SkillSuggestion[]>([]);
  const [skillIndex, setSkillIndex] = useState(0);
  const [arrobaIndex, setArrobaIndex] = useState(0);
  const [gravando, setGravando] = useState(false);
  const [segundos, setSegundos] = useState(0);
  const [parcial, setParcial] = useState('');
  const [erroVoz, setErroVoz] = useState('');
  const [emChamada, setEmChamada] = useState(false);
  const [anexos, setAnexos] = useState<Anexo[]>([]);
  const [acessos, setAcessos] = useState<string[]>([]);
  const [interlocutores, setInterlocutores] = useState<string[]>([]);
  const [mesaDaConversa, setMesaDaConversa] = useState<MesaDaConversa | null>(null);
  // Com dois ou mais no chip, a próxima mensagem pode abrir um assunto na Mesa com eles.
  const [levarAMesa, setLevarAMesa] = useState(false);
  const [mesasAbertas, setMesasAbertas] = useState<Assunto[]>([]);
  const [chromeConectado, setChromeConectado] = useState<boolean | null>(null);
  const [arrastando, setArrastando] = useState(false);
  const inputArquivoRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const [vozDisponivel, setVozDisponivel] = useState(false);
  const ditadoRef = useRef<Dictation | null>(null);
  const campoRef = useRef<CampoComTokensHandle>(null);
  const sendMessage = useChatStore(state => state.sendMessage);
  const abortStreaming = useChatStore(state => state.abortStreaming);
  const orientar = useChatStore(state => state.orientar);
  const enfileirar = useChatStore(state => state.enfileirar);
  const removerDaFila = useChatStore(state => state.removerDaFila);
  const enviarProximoDaFila = useChatStore(state => state.enviarProximoDaFila);
  const pararEEnviar = useChatStore(state => state.pararEEnviar);
  const appendLocalMessages = useChatStore(state => state.appendLocalMessages);
  const loadSession = useChatStore(state => state.loadSession);
  const [residentesConhecidos, setResidentesConhecidos] = useState<Agente[]>([]);
  // O texto antes do cursor: o `@` e o `/` abrem o menu ali, não só no fim.
  const [cursorAntes, setCursorAntes] = useState('');
  const activeSessionId = useSessionStore(state => state.activeSessionId);
  // O acesso é da conversa: trocar de conversa troca o que está ligado.
  useEffect(() => { setAcessos(lerAcessos(activeSessionId)); }, [activeSessionId]);
  useEffect(() => {
    setInterlocutores(lerInterlocutores(activeSessionId));
    setMesaDaConversa(lerMesaDaConversa(activeSessionId));
    setLevarAMesa(false);
  }, [activeSessionId]);
  const fila = useChatStore(state => activeSessionId ? state.filas[activeSessionId] : undefined) || [];
  const parando = useChatStore(state => activeSessionId ? state.streams[activeSessionId]?.parando ?? null : null);
  const createSession = useSessionStore(state => state.createSession);
  const isStreaming = useChatStore(state => activeSessionId ? Boolean(state.streams[activeSessionId]?.running) : false);
  const modeLabel = mode === 'ultra' ? 'Reforçado' : mode === 'ultra_max' ? 'Dedicado' : 'Router';
  const effortLabel = ({ auto: 'Automático', low: 'Leve', medium: 'Médio', high: 'Profundo' } as const)[effort];
  const antesDoCursor = input ? cursorAntes : '';
  const slashMatch = antesDoCursor.match(/(?:^|\s)\/([a-z0-9-]*)$/i);
  // `@` abre a lista de funções nativas e de residentes; escolher põe o selo no texto.
  const arrobaMatch = antesDoCursor.match(/(?:^|\s)@([a-z0-9-]*)$/i);
  const funcoesSugeridas = useMemo(() => {
    if (!arrobaMatch) return [];
    const termo = arrobaMatch[1].toLowerCase();
    // Na ordem dos grupos da lista (intenção, depois acesso): as setas andam como se vê.
    const grupo = (item: FuncaoNativa) => (item.tipo === 'intencao' ? 0 : 1);
    return FUNCOES_NATIVAS.filter(item => !termo || item.id.includes(termo)).sort((a, b) => grupo(a) - grupo(b));
  }, [arrobaMatch?.[1]]);
  // O `@` também chama um residente pelo nome: o pedido vai para a fila dele.
  const procurandoArroba = Boolean(arrobaMatch);
  useEffect(() => {
    void residentes.listar().then(lista => setResidentesConhecidos(atual =>
      atual.map(a => a.nome).join() === lista.agentes.map(a => a.nome).join() ? atual : lista.agentes)).catch(() => undefined);
    if (procurandoArroba) {
      void residentes.assuntos().then(lista => setMesasAbertas(lista.filter(a => a.estado === 'aberto'))).catch(() => undefined);
    }
  }, [procurandoArroba]);
  // Põe o token onde o `@` ou o `/` foi digitado, e o cursor logo depois dele.
  const inserirToken = (token: string) => campoRef.current?.inserirToken(token);
  const residentesSugeridos = useMemo(() => {
    if (!arrobaMatch) return [];
    const termo = arrobaMatch[1].toLowerCase();
    // Digitando, aparecem todos os que batem; sem termo, só os mais recentes,
    // porque com muitos residentes a lista inteira esconderia as funções.
    if (termo) return residentesConhecidos.filter(agente => agente.nome.includes(termo));
    const recentes = lerRecentes();
    const posicao = (nome: string) => { const i = recentes.indexOf(nome); return i < 0 ? Infinity : i; };
    return [...residentesConhecidos].sort((a, b) => posicao(a.nome) - posicao(b.nome)).slice(0, RESIDENTES_SEM_BUSCA);
  }, [arrobaMatch?.[1], residentesConhecidos]);
  const mencionar = (nome: string) => inserirToken(`@${nome}`);
  // O `@` também acha as Mesas abertas, pelo título ou pela palavra "mesa".
  const mesasSugeridas = useMemo(() => {
    if (!arrobaMatch) return [];
    const termo = arrobaMatch[1].toLowerCase();
    return mesasAbertas.filter(a => !termo || 'mesa'.startsWith(termo) || a.titulo.toLowerCase().includes(termo)).slice(0, 4);
  }, [arrobaMatch?.[1], mesasAbertas]);
  const ligarMesa = (mesa: MesaDaConversa | null) => {
    if (activeSessionId) {
      salvarMesaDaConversa(activeSessionId, mesa);
      if (mesa) salvarInterlocutores(activeSessionId, []);
    }
    setMesaDaConversa(mesa);
    if (mesa) { setInterlocutores([]); setLevarAMesa(false); }
  };
  const escolherMesa = (assunto: Assunto) => {
    campoRef.current?.apagarGatilho();
    ligarMesa({ id: assunto.id, titulo: assunto.titulo });
  };
  // A fala vai para a Mesa: num assunto aberto ou num novo com os residentes do chip.
  const enviarAMesa = async (sessionId: string, texto: string, destino: { assunto_id?: string; nomes?: string[] }) => {
    try {
      const { assunto } = await apiClient.post<{ assunto: { id: string; titulo: string } }>('/sentury/residentes/_levar_a_mesa',
        { session_id: sessionId, user_id: getRuntimeConfig().userId, texto, nomes: destino.nomes || [], assunto_id: destino.assunto_id || '' },
        { headers: authHeaders() });
      if (sessionId === useSessionStore.getState().activeSessionId) ligarMesa({ id: assunto.id, titulo: assunto.titulo });
      else salvarMesaDaConversa(sessionId, { id: assunto.id, titulo: assunto.titulo });
    } catch (e) {
      appendLocalMessages(sessionId, [
        { role: 'user', content: texto },
        { role: 'assistant', content: `Não consegui levar à Mesa: ${e instanceof Error ? e.message : 'a HQ não respondeu'}.` },
      ]);
    }
    await loadSession(sessionId);
  };
  // A lista muda a cada letra: o destaque volta para o primeiro.
  useEffect(() => { setArrobaIndex(0); }, [arrobaMatch?.[1]]);
  // Cada residente recebe a própria tarefa; a resposta de cada um volta aqui.
  const enviarAosResidentes = async (sessionId: string, nomes: string[], texto: string) => {
    // Uma ida só: o servidor grava a fala da pessoa uma vez, com todos os nomes.
    try {
      await apiClient.post('/sentury/residentes/_mencao',
        { session_id: sessionId, user_id: getRuntimeConfig().userId, texto, nomes },
        { headers: authHeaders() });
    } catch (e) {
      appendLocalMessages(sessionId, [
        { role: 'user', content: `${nomes.map(nome => `@${nome}`).join(' ')} ${texto}` },
        { role: 'assistant', content: `Não consegui mandar para ${nomes.map(nomeVisivel).join(', ')}: ${e instanceof Error ? e.message : 'a HQ não respondeu'}.` },
      ]);
    }
    await loadSession(sessionId);
  };
  const fecharInterlocutor = (nome: string | null) => {
    if (!activeSessionId) return;
    const proximo = nome ? interlocutores.filter(item => item !== nome) : [];
    salvarInterlocutores(activeSessionId, proximo);
    setInterlocutores(proximo);
    if (proximo.length < 2) setLevarAMesa(false);
  };

  const desligarAcesso = (id: string) => {
    if (!activeSessionId) return;
    const proximo = acessos.filter(item => item !== id);
    salvarAcessos(activeSessionId, proximo);
    setAcessos(proximo);
  };

  useEffect(() => {
    if (openPicker !== 'navegador') return;
    let ativo = true;
    const consultar = () => {
      void apiClient.get<{ conectada: boolean }>('/sentury/navegador/extensao/estado', { headers: authHeaders() })
        .then(estado => { if (ativo) setChromeConectado(estado.conectada); })
        .catch(() => { if (ativo) setChromeConectado(null); });
    };
    consultar();
    const timer = window.setInterval(consultar, 3000);
    return () => { ativo = false; window.clearInterval(timer); };
  }, [openPicker]);

  // Escolher no menu põe o selo no texto; o que ele liga é decidido no envio.
  const ligarFuncao = (id: string) => inserirToken(`@${id}`);
  const skillMatches = useMemo(() => {
    if (!slashMatch) return [];
    const query = slashMatch[1].toLowerCase();
    return skills.filter(skill => !query || skill.name.toLowerCase().includes(query) || skill.description.toLowerCase().includes(query)).slice(0, 6);
  }, [skills, slashMatch?.[1]]);

  // O composer pode subir quando a mensagem cresce. Limitar o menu pela altura
  // da janela (vh) nao basta: o topo da lista acabava fora da tela.
  useLayoutEffect(() => {
    if (!openPicker && !skillMatches.length && !funcoesSugeridas.length) return;
    const medir = () => {
      const topo = formRef.current?.getBoundingClientRect().top ?? window.innerHeight;
      const altura = Math.max(40, Math.floor(Math.min(window.innerHeight * 0.7, topo - 24)));
      setMenuMaxHeight(atual => atual === altura ? atual : altura);
    };
    medir();
    window.addEventListener('resize', medir);
    window.addEventListener('scroll', medir, true);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(medir);
    if (formRef.current) observer?.observe(formRef.current);
    return () => {
      window.removeEventListener('resize', medir);
      window.removeEventListener('scroll', medir, true);
      observer?.disconnect();
    };
  }, [openPicker, skillMatches.length, funcoesSugeridas.length, hasConversation]);

  useEffect(() => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    void apiClient.get<{ skills?: unknown[] }>('/sentury/skills', { headers: authHeaders() }).then(result => {
      const parsed = (result.skills || []).flatMap(value => {
        if (!value || typeof value !== 'object') return [];
        const record = value as Record<string, unknown>;
        if (typeof record.name !== 'string' || typeof record.description !== 'string') return [];
        return [{ name: record.name, description: record.description, family: typeof record.family === 'string' ? record.family : undefined }];
      });
      setSkills(parsed);
    }).catch(() => setSkills([]));
  }, []);

  useEffect(() => {
    let active = true;
    const carregarPermissao = () => {
      void apiClient.get<EstadoPermissoes>('/sentury/permissoes', { headers: authHeaders() })
        .then(estado => {
          if (active) setPermissionMode(estado.permitir_tudo ? 'auto' : 'manual');
        })
        .catch(() => undefined);
    };
    carregarPermissao();
    window.addEventListener('focus', carregarPermissao);
    return () => {
      active = false;
      window.removeEventListener('focus', carregarPermissao);
    };
  }, []);

  useEffect(() => {
    const form = formRef.current;
    if (!form || !onHeightChange) return;
    const report = () => onHeightChange(Math.ceil(form.getBoundingClientRect().height));
    report();
    const observer = new ResizeObserver(report);
    observer.observe(form);
    return () => observer.disconnect();
  }, [onHeightChange]);

  useEffect(() => setSkillIndex(0), [slashMatch?.[1]]);

  const chamadaLigada = useVoiceCallEnabled();

  // O botao de ligacao so existe se o servidor tiver um modelo de voz de fato.
  useEffect(() => {
    if (!chamadaLigada) { setVozDisponivel(false); return; }
    void apiClient.get<{ available?: boolean }>('/sentury/live/status', { headers: authHeaders() })
      .then(resultado => setVozDisponivel(Boolean(resultado.available)))
      .catch(() => setVozDisponivel(false));
  }, [chamadaLigada]);

  useEffect(() => {
    if (!gravando) return;
    const id = window.setInterval(() => setSegundos(valor => valor + 1), 1000);
    return () => window.clearInterval(id);
  }, [gravando]);

  const iniciarDitado = () => {
    setErroVoz('');
    const ditado = new Dictation({
      onStart: () => { setSegundos(0); setGravando(true); },
      onEnd: () => { setGravando(false); setParcial(''); ditadoRef.current = null; },
      onError: setErroVoz,
      onText: (final, interim) => {
        setParcial(interim);
        if (final) setInput(valor => (valor ? `${valor.trimEnd()} ` : '') + final.trim());
      },
    });
    ditadoRef.current = ditado;
    ditado.start();
  };

  // 8 MB por arquivo: cobre captura de tela e planilha sem virar deposito.

  // Imagem vai para quem enxerga. Todo o resto (PDF, DOCX, planilha, texto)
  // sobe como arquivo: o servidor grava no rascunho e o agente le pelo caminho.

  const anexar = async (arquivos: FileList | File[] | null) => {
    const { lidos, grandes } = await lerAnexos(arquivos);
    if (grandes) setErroVoz('Ignorei arquivo acima de 8 MB.');
    setAnexos(atual => [...atual, ...lidos].slice(0, 6));
  };

  const descartarDitado = () => {
    ditadoRef.current?.cancel();
    ditadoRef.current = null;
    setGravando(false);
    setParcial('');
  };

  const pickSkill = (skill: SkillSuggestion) => inserirToken(`/${skill.name}`);

  const chooseMode = (nextMode: SenturyMode) => {
    setMode(nextMode);
    setRuntimeMode(nextMode);
  };

  const chooseEffort = (nextEffort: SenturyEffort) => {
    setEffort(nextEffort);
    setRuntimeEffort(nextEffort);
  };

  const choosePermissionMode = async (nextMode: 'manual' | 'auto') => {
    if (permissionSaving || nextMode === permissionMode) {
      setOpenPicker(null);
      return;
    }
    const previous = permissionMode;
    setPermissionMode(nextMode);
    setPermissionSaving(true);
    setPermissionError('');
    try {
      const estado = await apiClient.post<EstadoPermissoes>(
        '/sentury/permissoes/permitir-tudo',
        { ligado: nextMode === 'auto' },
        { headers: authHeaders() },
      );
      setPermissionMode(estado.permitir_tudo ? 'auto' : 'manual');
      setOpenPicker(null);
    } catch (reason) {
      setPermissionMode(previous);
      setPermissionError(reason instanceof Error ? reason.message : 'Nao consegui mudar o modo de execucao.');
    } finally {
      setPermissionSaving(false);
    }
  };

  // Como cada token aparece no campo: a coruja do residente, a skill e a função.
  const desenharToken = useCallback((token: string): HTMLElement | null => {
    const nome = token.slice(1).toLowerCase();
    const badge = document.createElement('span');
    badge.contentEditable = 'false';
    badge.dataset.token = token;
    badge.title = token;
    if (token.startsWith('@')) {
      const agente = residentesConhecidos.find(item => item.nome === nome);
      if (agente) return seloDoResidente(agente, token);
      const funcao = funcaoPorId(nome);
      if (funcao) {
        // Dourado vale só para esta mensagem; escuro é acesso que fica na conversa.
        badge.className = funcao.tipo === 'acesso'
          ? 'mx-0.5 inline-flex select-none items-center gap-1 rounded-md bg-zinc-900 px-1.5 py-px align-middle text-[12px] font-semibold leading-5 text-white'
          : 'mx-0.5 inline-flex select-none items-center gap-1 rounded-md border border-[#ecd98a] bg-[#fbf3d0] px-1.5 align-middle text-[12px] font-semibold leading-5 text-[#4d4000]';
        badge.title = funcao.descricao;
        badge.innerHTML = renderToStaticMarkup(
          <IconeDaFuncao id={funcao.id} className={`h-3 w-3 ${funcao.tipo === 'acesso' ? 'text-gold' : ''}`} />);
        badge.append(document.createTextNode(`@${funcao.rotulo}`));
        return badge;
      }
      return null;
    }
    if (skills.some(skill => skill.name.toLowerCase() === nome)) return seloDaSkill(nome);
    return null;
  }, [residentesConhecidos, skills]);

  // Com o turno rodando: `orientar` (Enter) vai para ele no proximo ponto
  // seguro; `fila` (Alt+Enter) espera ele acabar; `parar` para e manda como
  // turno novo. Anexo não vai por orientação: fica na fila.
  const handleSubmit = (event?: React.FormEvent, modo: 'orientar' | 'fila' | 'parar' = 'orientar') => {
    event?.preventDefault();
    setOpenPicker(current => current === 'enviar' ? null : current);
    // Enviar durante a gravacao para o ditado: nao existe botao de "aprovar".
    if (gravando) { ditadoRef.current?.stop(); ditadoRef.current = null; setGravando(false); setParcial(''); }
    const trimmed = input.trim();
    if (!trimmed) return;
    const sessionId = activeSessionId || createSession(undefined, 'Nova conversa').id;
    // Começar com menções (`@alfa @nina faça X`) manda a tarefa a cada um e abre
    // o chip "Falando com"; com chip aberto, a mensagem sem `@` vai para os
    // residentes dele. Menção no meio da frase é fala sobre o residente: vai ao
    // Sentury. Anexo também vai ao Sentury, porque a tarefa do residente leva só texto.
    const conhecido = (nome: string) => residentesConhecidos.some(agente => agente.nome === nome.toLowerCase());
    const citados = [...trimmed.matchAll(/(?:^|\s)@([a-z][a-z0-9-]{1,30})/gi)].map(m => m[1]).filter(conhecido);
    marcarRecentes(citados.map(nome => nome.toLowerCase()));
    const { nomes: iniciais, pedido } = mencoesIniciais(trimmed, conhecido);
    // Chip da Mesa: a fala vai para o assunto, e as menções viram chamados lá.
    if (mesaDaConversa && !isStreaming && !anexos.length) {
      setInput('');
      void enviarAMesa(sessionId, trimmed, { assunto_id: mesaDaConversa.id });
      return;
    }
    if (levarAMesa && interlocutores.length > 1 && pedido && !isStreaming && !anexos.length) {
      const nomes = [...new Set([...interlocutores, ...iniciais])];
      setInput('');
      void enviarAMesa(sessionId, pedido, { nomes });
      return;
    }
    const alvos = iniciais.length ? iniciais : (citados.length ? [] : interlocutores);
    if (alvos.length && pedido && !isStreaming && !anexos.length) {
      const abertos = [...new Set([...interlocutores, ...iniciais])];
      salvarInterlocutores(sessionId, abertos);
      setInterlocutores(abertos);
      if (abertos.length < 2) setLevarAMesa(false);
      setInput('');
      void enviarAosResidentes(sessionId, alvos, pedido);
      return;
    }
    // Os acessos da conversa mais o que o texto cita; acesso citado fica ligado.
    const funcoesEnviadas = funcoesDoEnvio(sessionId, trimmed);
    setAcessos(lerAcessos(sessionId));
    const imagens = anexos
      .filter(anexo => anexo.dataUrl && anexo.tipo.startsWith('image/'))
      .map(anexo => ({ nome: anexo.nome, dataUrl: anexo.dataUrl as string }));
    // Colar o texto no corpo estourava o teto de 2.000 caracteres da mensagem.
    const arquivos = anexos
      .filter(anexo => anexo.dataUrl && !anexo.tipo.startsWith('image/'))
      .map(anexo => ({ nome: anexo.nome, dataUrl: anexo.dataUrl as string }));
    setInput('');
    setAnexos([]);
    if (isStreaming && modo === 'parar') {
      pararEEnviar(sessionId, { texto: trimmed, imagens, arquivos, funcoes: funcoesEnviadas });
    } else if (isStreaming && (modo === 'fila' || imagens.length || arquivos.length)) {
      enfileirar(sessionId, { texto: trimmed, imagens, arquivos, funcoes: funcoesEnviadas });
    } else if (isStreaming) {
      void orientar(sessionId, trimmed);
    } else {
      void sendMessage(sessionId, trimmed, imagens, funcoesEnviadas, arquivos);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (skillMatches.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      setSkillIndex(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + skillMatches.length) % skillMatches.length);
      return;
    }
    if (skillMatches.length && event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      pickSkill(skillMatches[skillIndex] || skillMatches[0]);
      return;
    }
    if (event.key === 'Escape' && skillMatches.length) {
      campoRef.current?.apagarGatilho();
      return;
    }
    // Na lista do `@`, setas andam e Enter ou Tab escolhem, como no `/` das
    // skills. Sem Tab, a pessoa ficava presa com a lista aberta.
    const opcoesDoArroba = [
      ...residentesSugeridos.map(agente => () => mencionar(agente.nome)),
      ...mesasSugeridas.map(assunto => () => escolherMesa(assunto)),
      ...funcoesSugeridas.map(item => () => ligarFuncao(item.id)),
    ];
    if (opcoesDoArroba.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      setArrobaIndex(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + opcoesDoArroba.length) % opcoesDoArroba.length);
      return;
    }
    if (opcoesDoArroba.length && (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey))) {
      event.preventDefault();
      (opcoesDoArroba[arrobaIndex] || opcoesDoArroba[0])();
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSubmit(undefined, event.altKey ? 'fila' : 'orientar');
    } else if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
      event.preventDefault();
      onOpenQuickSheet?.();
    }
  };

  return (
    <div className={`pointer-events-none absolute inset-x-0 z-20 px-3 transition-[bottom,padding] duration-500 ease-[cubic-bezier(.22,1,.36,1)] sm:px-5 ${hasConversation
      ? 'bottom-0 bg-gradient-to-t from-canvas via-canvas/95 to-transparent pb-5 pt-12'
      : 'bottom-[clamp(100px,18vh,190px)] pb-0 pt-0'}`}>
      <form
        ref={formRef}
        onSubmit={handleSubmit}
        onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); setArrastando(true); } }}
        onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setArrastando(false); }}
        onDrop={event => { event.preventDefault(); setArrastando(false); void anexar(event.dataTransfer.files); }}
        className={`pointer-events-auto relative mx-auto w-full rounded-[22px] border bg-[#fffdf8] px-3 pb-2.5 pt-2.5 shadow-[0_18px_46px_rgba(22,22,22,0.12)] transition-[max-width,border-color,box-shadow] duration-500 focus-within:border-gold focus-within:shadow-[0_18px_46px_rgba(22,22,22,0.16)] ${arrastando ? 'border-gold bg-gold-soft/40' : 'border-[#d8cfbd]'} ${hasConversation ? 'max-w-[920px]' : 'max-w-[820px]'}`}
      >
        <QuickCommandSheet isOpen={isQuickSheetOpen} onClose={onCloseQuickSheet} />
        {skillMatches.length > 0 && !openPicker && (
          <div style={{ maxHeight: menuMaxHeight }} className="absolute bottom-[calc(100%+8px)] left-0 flex w-full max-w-lg flex-col overflow-hidden rounded-xl border border-[#d8cfbd] bg-[#fffdf8] p-1.5 shadow-[0_18px_46px_rgba(22,22,22,.16)]">
            <p className="shrink-0 px-2 py-1 text-[10px] font-bold uppercase tracking-[.13em] text-zinc-400">Inserir skill</p>
            <div className="min-h-0 overflow-y-auto overscroll-contain">
              {skillMatches.map((skill, index) => <button key={skill.name} type="button" onMouseDown={event => event.preventDefault()} onClick={() => pickSkill(skill)} className={`flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left ${index === skillIndex ? 'bg-gold-soft' : 'hover:bg-stone-100'}`}><span className="mt-0.5 rounded-md bg-zinc-900 px-1.5 py-0.5 text-[10px] font-bold text-gold">/{skill.name}</span><span className="min-w-0"><span className="line-clamp-2 text-xs leading-4 text-zinc-600">{skill.description}</span>{skill.family && <span className="mt-0.5 block text-[9px] uppercase tracking-wider text-zinc-400">{skill.family}</span>}</span></button>)}
            </div>
          </div>
        )}
        {(funcoesSugeridas.length > 0 || residentesSugeridos.length > 0 || mesasSugeridas.length > 0) && !openPicker && (
          <div style={{ maxHeight: menuMaxHeight }} className="absolute bottom-[calc(100%+8px)] left-0 z-20 flex w-full max-w-lg flex-col overflow-hidden rounded-xl border border-[#d8cfbd] bg-[#fffdf8] p-1.5 shadow-[0_18px_46px_rgba(22,22,22,.16)]">
            <div className="min-h-0 overflow-y-auto overscroll-contain">
            {residentesSugeridos.length > 0 && (
              <>
                <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-[.13em] text-zinc-500">{arrobaMatch?.[1] ? 'Residentes' : 'Residentes recentes'}</p>
                {residentesSugeridos.map((agente, indice) => (
                  <button key={agente.nome} type="button" onMouseDown={event => event.preventDefault()} onClick={() => mencionar(agente.nome)}
                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left ${indice === arrobaIndex ? 'bg-gold-soft' : 'hover:bg-stone-100'}`}>
                    <Coruja cores={coresDoAgente(agente)}
                      acessorios={agente.aparencia.acessorios} tamanho={30} rotulo={agente.nome} />
                    <span className="min-w-0">
                      <span className="block text-xs font-semibold text-zinc-900">@{agente.nome}</span>
                      <span className="block truncate text-xs text-zinc-600">{agente.papel}</span>
                    </span>
                  </button>
                ))}
                {!arrobaMatch?.[1] && residentesConhecidos.length > residentesSugeridos.length ? (
                  <p className="px-3 pb-1 text-[11px] text-zinc-500">Digite o nome para achar os outros {residentesConhecidos.length - residentesSugeridos.length}.</p>
                ) : null}
              </>
            )}
            {mesasSugeridas.length > 0 && (
              <>
                <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-[.13em] text-zinc-500">Mesas abertas</p>
                {mesasSugeridas.map((assunto, indice) => (
                  <button key={assunto.id} type="button" onMouseDown={event => event.preventDefault()} onClick={() => escolherMesa(assunto)}
                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left ${residentesSugeridos.length + indice === arrobaIndex ? 'bg-gold-soft' : 'hover:bg-stone-100'}`}>
                    <Users className="h-4 w-4 shrink-0 text-gold-ink" />
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-semibold text-zinc-900">{assunto.titulo}</span>
                      <span className="block truncate text-xs text-zinc-600">{assunto.participantes.map(nomeVisivel).join(', ') || 'sem participantes ainda'} · {assunto.falas.length} falas</span>
                    </span>
                  </button>
                ))}
              </>
            )}
              {(['intencao', 'acesso'] as const).map(tipo => {
                const doTipo = funcoesSugeridas.filter((item: FuncaoNativa) => item.tipo === tipo);
                if (!doTipo.length) return null;
                return (
                  <div key={tipo}>
                    <p className="px-2 py-1 text-[10px] font-bold uppercase tracking-[.13em] text-zinc-500">{tipo === 'intencao' ? 'Para esta mensagem' : 'Acesso nesta conversa'}</p>
                    {doTipo.map((item: FuncaoNativa) => (
                      <button key={item.id} type="button" onMouseDown={event => event.preventDefault()} onClick={() => ligarFuncao(item.id)} title={item.descricao} className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-1.5 text-left ${residentesSugeridos.length + mesasSugeridas.length + funcoesSugeridas.indexOf(item) === arrobaIndex ? 'bg-gold-soft' : 'hover:bg-stone-100'}`}>
                        <IconeDaFuncao id={item.id} className={`h-4 w-4 shrink-0 ${tipo === 'acesso' ? 'text-zinc-900' : 'text-gold-ink'}`} />
                        <span className="w-24 shrink-0 text-xs font-semibold text-zinc-900">@{item.rotulo}</span>
                        <span className="min-w-0 truncate text-xs text-zinc-600">{item.resumo}</span>
                        {tipo === 'acesso' && acessos.includes(item.id) ? <span className="ml-auto shrink-0 text-[9px] font-semibold uppercase tracking-wider text-emerald-700">ligado</span> : null}
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {openPicker ? (
          <button
            type="button"
            className="fixed inset-0 z-10 cursor-default bg-transparent"
            onClick={() => setOpenPicker(null)}
            aria-label="Fechar menu do composer"
          />
        ) : null}
        {openPicker === 'add' ? (
          <div style={{ maxHeight: menuMaxHeight }} className="absolute bottom-[calc(100%+10px)] left-0 z-20 w-[min(22rem,calc(100vw-1.5rem))] overflow-y-auto overscroll-contain rounded-2xl border border-[#d8cfbd] bg-[#fffdf8] p-1.5 shadow-[0_20px_55px_rgba(22,22,22,0.18)]">
            <p className="sticky top-0 z-10 bg-[#fffdf8] px-3 pb-1 pt-1.5 text-[10px] font-bold uppercase tracking-[.14em] text-zinc-400">Adicionar</p>
            <button
              type="button"
              onClick={() => { setOpenPicker(null); inputArquivoRef.current?.click(); }}
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-zinc-700 hover:bg-stone-100"
            >
              <Paperclip className="h-4 w-4 shrink-0" />
              <span><strong className="block text-xs font-semibold text-zinc-900">Arquivos e pastas</strong><small className="mt-0.5 block text-[10px] text-zinc-500">Anexe ou arraste para a conversa</small></span>
            </button>
            <div className="my-1 border-t border-stone-200" />
            <button
              type="button"
              onClick={() => { setOpenPicker(null); onOpenQuickSheet?.(); }}
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-zinc-700 hover:bg-stone-100"
            >
              <SlidersHorizontal className="h-4 w-4 shrink-0" />
              <span><strong className="block text-xs font-semibold text-zinc-900">Configuração do motor</strong><small className="mt-0.5 block text-[10px] text-zinc-500">Processo, tools e recuperação</small></span>
            </button>
          </div>
        ) : null}
        {openPicker === 'intelligence' ? (
          <div style={{ maxHeight: menuMaxHeight }} className="absolute bottom-[calc(100%+10px)] left-0 z-20 flex w-[min(24rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl border border-[#d8cfbd] bg-[#fffdf8] p-1.5 shadow-[0_20px_55px_rgba(22,22,22,0.18)]">
            <div className="flex shrink-0 items-center justify-between px-3 pb-1 pt-1.5">
              <p className="text-[10px] font-bold uppercase tracking-[.14em] text-zinc-400">Modelo</p>
              <button type="button" onClick={() => setOpenPicker('add')} className="text-[10px] font-medium text-zinc-500 hover:text-zinc-900">Voltar</button>
            </div>
            <div className="min-h-0 overflow-y-auto overscroll-contain">
            {([
              ['router', 'Router', 'RobinBandit escolhe a melhor cadeia disponível.'],
              ['ultra', 'Reforçado', 'Começa no provedor escolhido e usa fallback se necessário.'],
              ['ultra_max', 'Dedicado', 'Fica no provedor escolhido; se falhar, o turno termina.'],
            ] as const).map(([value, label, description]) => (
              <button key={value} type="button" onClick={() => chooseMode(value)} className={`flex w-full items-start gap-2.5 rounded-xl px-3 py-2 text-left hover:bg-stone-100 ${mode === value ? 'bg-gold-soft' : ''}`}>
                <IconeModo mode={value} className="mt-0.5 h-4 w-4 shrink-0 text-zinc-700" />
                <span className="min-w-0"><span className="block text-xs font-semibold text-zinc-900">{label}</span><span className="mt-0.5 block text-[10px] leading-4 text-zinc-500">{description}</span></span>
              </button>
            ))}
            <div className="mx-2 my-1.5 border-t border-stone-200" />
            <p className="px-3 pb-1 pt-1 text-[10px] font-bold uppercase tracking-[.14em] text-zinc-400">Esforço</p>
            {([
              ['auto', 'Automático', 'Usa o padrão do provedor, o mesmo no turno inteiro.'],
              ['low', 'Leve', 'Respostas mais diretas.'],
              ['medium', 'Médio', 'Equilíbrio entre análise e velocidade.'],
              ['high', 'Profundo', 'Mais investigação quando a tarefa exige.'],
            ] as const).map(([value, label, description]) => (
              <button key={value} type="button" onClick={() => chooseEffort(value)} className={`flex w-full items-start gap-2.5 rounded-xl px-3 py-2 text-left hover:bg-stone-100 ${effort === value ? 'bg-gold-soft' : ''}`}>
                <IconeEsforco effort={value} className="mt-0.5 h-4 w-4 shrink-0 text-zinc-700" />
                <span className="min-w-0"><span className="block text-xs font-semibold text-zinc-900">{label}</span><span className="mt-0.5 block text-[10px] leading-4 text-zinc-500">{description}</span></span>
              </button>
            ))}
            </div>
          </div>
        ) : null}
        {openPicker === 'navegador' ? (
          <div style={{ maxHeight: menuMaxHeight }} className="absolute bottom-[calc(100%+10px)] left-10 z-20 w-[min(22rem,calc(100vw-1.5rem))] overflow-y-auto overscroll-contain rounded-2xl border border-[#d8cfbd] bg-[#fffdf8] p-3 shadow-[0_20px_55px_rgba(22,22,22,0.18)]">
            <h3 className="text-sm font-semibold text-zinc-900">Navegador do usuário</h3>
            <p className="mt-1 text-xs text-zinc-600">{chromeConectado === true ? 'Chrome conectado · somente abas criadas pelo Sentury.' : chromeConectado === false ? 'Extensão desconectada. O Sentury não troca de navegador sozinho.' : 'Verificando conexão com o Chrome…'}</p>
            {chromeConectado === false ? <p className="mt-2 text-xs text-zinc-600">A extensão do Tato se conecta sozinha, sem código. Se não conectar, clique no ícone dela no Chrome e em “Tentar de novo”.</p> : null}
            <button type="button" onClick={() => { setOpenPicker(null); onOpenBrowserSettings?.(); }} className="mt-3 flex w-full items-center justify-between border-t border-stone-200 pt-3 text-left text-xs font-medium text-zinc-700 hover:text-zinc-950">Abrir Configurações do navegador <ChevronRight className="h-4 w-4" /></button>
          </div>
        ) : null}
        {openPicker === 'permission' ? (
          <div style={{ maxHeight: menuMaxHeight }} className="absolute bottom-[calc(100%+10px)] left-10 z-20 w-[min(22rem,calc(100vw-1.5rem))] overflow-y-auto overscroll-contain rounded-2xl border border-[#d8cfbd] bg-[#fffdf8] p-1.5 shadow-[0_20px_55px_rgba(22,22,22,0.18)]">
            <p className="sticky top-0 z-10 bg-[#fffdf8] px-3 pb-1 pt-1.5 text-[10px] font-bold uppercase tracking-[.14em] text-zinc-400">Modo de execução</p>
            <button type="button" disabled={permissionSaving} onClick={() => void choosePermissionMode('manual')} className={`flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-stone-100 ${permissionMode === 'manual' ? 'bg-gold-soft' : ''}`}>
              <Hand className="mt-0.5 h-4 w-4 shrink-0" />
              <span><strong className="block text-xs font-semibold text-zinc-900">Solicitar aprovação</strong><small className="mt-0.5 block text-[10px] leading-4 text-zinc-500">Pergunta antes de executar ações que alteram algo.</small></span>
            </button>
            <button type="button" disabled={permissionSaving} onClick={() => void choosePermissionMode('auto')} className={`flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-stone-100 ${permissionMode === 'auto' ? 'bg-amber-50' : ''}`}>
              <Zap className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <span><strong className="block text-xs font-semibold text-zinc-900">Tudo liberado</strong><small className="mt-0.5 block text-[10px] leading-4 text-zinc-500">Executa sem interromper para pedir autorização.</small></span>
            </button>
            <div className="my-1 border-t border-stone-200" />
            <p className="px-3 pb-1 pt-1.5 text-[10px] font-bold uppercase tracking-[.14em] text-zinc-400">Onde ele pode mexer</p>
            <PastaAtiva onAbrirHarness={() => { setOpenPicker(null); onOpenHarness?.(); }} />
          </div>
        ) : null}
        {anexos.length > 0 ? (
          <div className="mx-1 mb-2 flex flex-wrap gap-2">
            {anexos.map((anexo, indice) => (
              <span
                key={`${anexo.nome}-${indice}`}
                className="group relative flex items-center gap-2 rounded-lg border border-stone-300 bg-white/80 py-1.5 pl-1.5 pr-2.5"
              >
                {anexo.dataUrl && anexo.tipo.startsWith('image/') ? (
                  <img src={anexo.dataUrl} alt="" className="h-9 w-9 rounded-md object-cover" />
                ) : (
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-stone-100 text-zinc-500">
                    <Paperclip className="h-3.5 w-3.5" />
                  </span>
                )}
                <span className="min-w-0">
                  <span className="block max-w-40 truncate text-[11px] font-medium text-zinc-700">{anexo.nome}</span>
                  <span className="block text-[9px] uppercase tracking-wider text-zinc-400">
                    {anexo.tipo.startsWith('image/') ? 'imagem' : anexo.dataUrl ? 'arquivo' : 'nao lido'}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => setAnexos(atual => atual.filter((_, i) => i !== indice))}
                  className="rounded-full p-0.5 text-zinc-400 hover:bg-stone-200 hover:text-zinc-700"
                  aria-label={`Remover ${anexo.nome}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        ) : null}

        {fila.length && activeSessionId ? (
          <div className="mx-1 mb-1.5 flex flex-col gap-1" aria-label="Mensagens na fila">
            {fila.map(item => (
              <div key={item.id} className="flex items-center gap-2 rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1.5 text-xs text-zinc-700">
                <ListPlus className="h-3.5 w-3.5 shrink-0 text-gold-ink" />
                <span className="shrink-0 font-semibold text-zinc-500">Na fila</span>
                <span className="min-w-0 flex-1 truncate">{item.texto}</span>
                {item.imagens?.length || item.arquivos?.length ? <span className="shrink-0 text-zinc-400">+ anexo</span> : (
                  <button type="button" className="shrink-0 rounded px-1.5 py-0.5 text-zinc-500 hover:bg-stone-200 hover:text-zinc-800"
                    onClick={() => { setInput(item.texto); removerDaFila(activeSessionId, item.id); window.setTimeout(() => campoRef.current?.focar(), 0); }}>
                    editar
                  </button>
                )}
                <button type="button" className="shrink-0 rounded p-0.5 text-zinc-400 hover:bg-stone-200 hover:text-zinc-700"
                  onClick={() => removerDaFila(activeSessionId, item.id)} aria-label="Tirar da fila" title="Tirar da fila">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {!isStreaming ? (
              // Turno parado ou com erro: a fila nao sai sozinha, a pessoa decide.
              <div className="flex items-center gap-2 px-1 text-[11px] text-zinc-500">
                <span>O turno parou antes de acabar; a fila espera você.</span>
                <button type="button" className="font-semibold text-gold-ink hover:underline" onClick={() => enviarProximoDaFila(activeSessionId)}>
                  Enviar a próxima
                </button>
              </div>
            ) : null}
          </div>
        ) : null}

        {isStreaming && parando !== null ? (
          // A parada espera uma escrita em curso terminar.
          <p className="mx-2 mb-1 flex items-center gap-1.5 text-[11px] text-amber-800">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
            {parando
              ? <span>Parando depois que <code className="font-mono">{parando}</code> terminar, para não deixar nada pela metade. Clique no quadrado de novo para cortar já.</span>
              : <span>Parando…</span>}
          </p>
        ) : null}

        {acessos.length > 0 || interlocutores.length > 0 || mesaDaConversa ? (
          <div className="mx-1 mb-1.5 flex flex-wrap gap-2">
            {mesaDaConversa ? (
              <span className="inline-flex h-7 items-center gap-1 rounded-full border border-gold bg-gold-soft/60 pr-1 text-xs font-medium text-zinc-900">
                <button type="button" onClick={() => abrirAssuntoDaMesa(mesaDaConversa.id)} title="Abrir o assunto na Mesa"
                        className="inline-flex h-7 max-w-[320px] items-center gap-1.5 rounded-full pl-2.5 pr-1 hover:text-gold-ink">
                  <Users className="h-3.5 w-3.5 shrink-0 text-gold-ink" />
                  <span className="truncate">Na Mesa: {mesaDaConversa.titulo}</span>
                </button>
                <button type="button" onClick={() => ligarMesa(null)} aria-label="Sair da Mesa" title="Voltar ao Sentury" className="flex h-5 w-5 items-center justify-center rounded-full hover:bg-gold-soft">
                  <X className="h-3 w-3" />
                </button>
              </span>
            ) : null}
            {interlocutores.map(nome => {
              const agente = residentesConhecidos.find(item => item.nome === nome);
              return (
                <span key={`com-${nome}`} className="inline-flex h-7 items-center gap-1.5 rounded-full border border-gold bg-gold-soft/60 pl-1 pr-1 text-xs font-medium text-zinc-900">
                  {agente ? <Coruja cores={coresDoAgente(agente)} acessorios={agente.aparencia.acessorios} tamanho={22} rotulo={nome} /> : null}
                  <span>Falando com {nomeVisivel(nome)}</span>
                  <button type="button" onClick={() => fecharInterlocutor(nome)} aria-label={`Parar de falar com ${nomeVisivel(nome)}`} title="Voltar ao Sentury" className="flex h-5 w-5 items-center justify-center rounded-full hover:bg-gold-soft">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              );
            })}
            {interlocutores.length > 1 ? (
              <button type="button" aria-pressed={levarAMesa} onClick={() => setLevarAMesa(atual => !atual)}
                      title="A próxima mensagem abre um assunto na Mesa com eles, em vez de uma tarefa para cada um"
                      className={`inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium ${levarAMesa ? 'border-gold bg-zinc-900 text-white' : 'border-stone-300 text-zinc-600 hover:border-gold hover:text-zinc-900'}`}>
                <Users className="h-3.5 w-3.5" />
                {levarAMesa ? 'Vai para a Mesa' : 'Levar para a Mesa'}
              </button>
            ) : null}
            {interlocutores.length > 1 ? (
              <button type="button" onClick={() => fecharInterlocutor(null)} className="h-7 rounded-full px-2.5 text-[11px] font-medium text-zinc-500 hover:bg-stone-100 hover:text-zinc-800">Voltar ao Sentury</button>
            ) : null}
            {acessos.map(id => {
              const funcao = funcaoPorId(id);
              if (!funcao) return null;
              const rotulo = <><IconeDaFuncao id={id} className="h-3.5 w-3.5 text-gold" />{funcao.ligado || `@${funcao.rotulo}`}</>;
              return (
                <span key={id} className="inline-flex h-7 items-center gap-1 rounded-full bg-zinc-900 pr-1 text-xs font-medium text-white">
                  {id === 'navegador'
                    ? <button type="button" onClick={() => setOpenPicker(atual => atual === 'navegador' ? null : 'navegador')} title="Configuração rápida do navegador" aria-expanded={openPicker === 'navegador'} className="inline-flex h-7 items-center gap-1.5 rounded-full pl-2.5 pr-1 hover:text-gold">{rotulo}</button>
                    : <span className="inline-flex items-center gap-1.5 pl-2.5 pr-1">{rotulo}</span>}
                  <button type="button" onClick={() => desligarAcesso(id)} aria-label={`Desligar: ${funcao.ligado || funcao.rotulo}`} title="Desligar" className="flex h-5 w-5 items-center justify-center rounded-full bg-zinc-700 hover:bg-zinc-600">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              );
            })}
          </div>
        ) : null}

        <CampoComTokens
          ref={campoRef}
          valor={input}
          onMudar={setInput}
          onCursor={setCursorAntes}
          onKeyDown={handleKeyDown}
          onColarArquivos={arquivos => void anexar(arquivos)}
          desenhar={desenharToken}
          placeholder={isStreaming ? 'Orientar a Sentury… (Alt+Enter deixa na fila)'
            : mesaDaConversa ? `Falar na Mesa: ${mesaDaConversa.titulo}…`
            : levarAMesa && interlocutores.length > 1 ? `Abrir na Mesa com ${interlocutores.map(nomeVisivel).join(' e ')}…`
            : interlocutores.length ? `Mensagem para ${interlocutores.map(nomeVisivel).join(' e ')}…`
            : 'Pergunte algo, @ para residentes e funções, / para skills'}
        />

        {gravando ? (
          <div className="mx-2 mb-1 flex items-center gap-2.5 rounded-lg bg-stone-100/80 px-3 py-2">
            <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
            <span className="text-[11px] font-medium tabular-nums text-zinc-600">
              {Math.floor(segundos / 60)}:{String(segundos % 60).padStart(2, '0')}
            </span>
            <span className="min-w-0 flex-1 truncate text-[11px] italic text-zinc-400">{parcial || 'ouvindo…'}</span>
            <button type="button" onClick={descartarDitado} className="rounded-md p-1 text-zinc-400 hover:bg-stone-200 hover:text-zinc-700" title="Descartar gravação" aria-label="Descartar gravação">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}
        {erroVoz ? <p className="mx-2 mb-1 text-[11px] text-amber-700">{erroVoz}</p> : null}

        {permissionError ? <p className="mx-2 mb-1 text-[11px] text-red-600">{permissionError}</p> : null}

        <input
          ref={inputArquivoRef}
          type="file"
          multiple
          hidden
          onChange={event => { void anexar(event.target.files); event.target.value = ''; }}
        />

        <div className="relative z-20 mt-0.5 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1">
            <button
              type="button"
              onClick={() => setOpenPicker(current => current === 'add' ? null : 'add')}
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors ${openPicker === 'add' ? 'bg-zinc-900 text-white' : 'text-zinc-700 hover:bg-stone-100'}`}
              title="Adicionar arquivo, pasta ou configuração"
              aria-label="Adicionar"
              aria-expanded={openPicker === 'add'}
            >
              <Plus className={`h-[18px] w-[18px] transition-transform ${openPicker === 'add' ? 'rotate-45' : ''}`} />
            </button>
            <button
              type="button"
              onClick={() => setOpenPicker(current => current === 'permission' ? null : 'permission')}
              className={`flex h-8 min-w-0 items-center gap-1.5 rounded-lg px-2 text-xs font-medium transition-colors hover:bg-stone-100 ${permissionMode === 'auto' ? 'text-amber-700' : 'text-zinc-600'}`}
              title="Modo de execução"
              aria-expanded={openPicker === 'permission'}
            >
              {permissionMode === 'auto' ? <Zap className="h-4 w-4 shrink-0" /> : <Hand className="h-4 w-4 shrink-0" />}
              <span className="truncate">{permissionMode === 'auto' ? 'Tudo liberado' : 'Solicitar aprovação'}</span>
              <ChevronDown className="h-3 w-3 shrink-0 text-zinc-400" />
            </button>
            <ContextGauge
              aberto={openPicker === 'contexto'}
              onAlternar={valor => setOpenPicker(valor ? 'contexto' : null)}
            />
          </div>

          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={() => setOpenPicker(current => current === 'intelligence' ? null : 'intelligence')}
              className="flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-zinc-600 hover:bg-stone-100"
              title={`Modelo: ${modeLabel}. Esforço: ${effortLabel}`}
              aria-expanded={openPicker === 'intelligence'}
            >
              <IconeModo mode={mode} className="h-4 w-4" />
              <span className="hidden max-w-44 truncate sm:inline">{modeLabel} · {effortLabel}</span>
              <ChevronDown className="hidden h-3 w-3 text-zinc-400 sm:block" />
            </button>
            {dictationSupported() ? (
              <button
                type="button"
                onClick={() => (gravando ? ditadoRef.current?.stop() : iniciarDitado())}
                className={`flex h-8 w-8 items-center justify-center rounded-full transition-colors ${gravando ? 'bg-red-50 text-red-600' : 'text-zinc-700 hover:bg-stone-100'}`}
                title={gravando ? 'Parar de ditar' : 'Ditar mensagem'}
                aria-pressed={gravando}
              >
                <Mic className="h-4 w-4" />
              </button>
            ) : null}
            {vozDisponivel ? (
              <button
                type="button"
                onClick={() => setEmChamada(true)}
                className="flex h-8 w-8 items-center justify-center rounded-full text-zinc-700 hover:bg-stone-100"
                title="Ligar para o Sentury"
              >
                <PhoneCall className="h-4 w-4" />
              </button>
            ) : null}
            {isStreaming ? (
              <>
                {input.trim() ? (
                  <div className="relative flex items-center">
                    <button type="submit" className="flex h-9 items-center gap-1.5 rounded-l-xl bg-gold pl-2.5 pr-2 text-xs font-semibold text-zinc-950 hover:bg-gold-hover"
                      title="Orientar: entra no próximo passo deste turno (Enter)">
                      <Send className="h-4 w-4" />Orientar
                    </button>
                    <button type="button" onClick={() => setOpenPicker(current => current === 'enviar' ? null : 'enviar')}
                      className="flex h-9 w-6 items-center justify-center rounded-r-xl border-l border-zinc-950/15 bg-gold text-zinc-950 hover:bg-gold-hover"
                      aria-label="Outras formas de enviar" aria-expanded={openPicker === 'enviar'}>
                      <ChevronUp className="h-3.5 w-3.5" />
                    </button>
                    {openPicker === 'enviar' ? (
                      <div style={{ maxHeight: menuMaxHeight }} className="absolute bottom-[calc(100%+8px)] right-0 z-20 w-64 overflow-y-auto overscroll-contain rounded-xl border border-[#d8cfbd] bg-[#fffdf8] p-1.5 shadow-[0_18px_46px_rgba(22,22,22,.16)]">
                        {([
                          ['orientar', 'Orientar agora', 'Entra no próximo passo deste turno', 'Enter'],
                          ['fila', 'Deixar na fila', 'Vai quando este turno acabar', 'Alt+Enter'],
                          ['parar', 'Parar e enviar', 'Para o turno e começa outro com ela', ''],
                        ] as const).map(([modo, rotulo, descricao, tecla]) => (
                          <button key={modo} type="button" onClick={() => handleSubmit(undefined, modo)}
                            className="flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left hover:bg-stone-100">
                            <span className="min-w-0 flex-1">
                              <span className="block text-xs font-semibold text-zinc-800">{rotulo}</span>
                              <span className="block text-[11px] leading-4 text-zinc-500">{descricao}</span>
                            </span>
                            {tecla ? <kbd className="mt-0.5 rounded border border-stone-300 px-1 font-mono text-[10px] text-zinc-500">{tecla}</kbd> : null}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <button type="button" onClick={() => activeSessionId && abortStreaming(activeSessionId)} className="flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-900 text-red-300" title={parando !== null ? 'Parar já, mesmo no meio' : 'Parar (a escrita em curso termina antes)'}>
                  <Square className="h-3.5 w-3.5 fill-current" />
                </button>
              </>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className={`flex h-9 w-9 items-center justify-center rounded-xl transition-colors ${input.trim() ? 'bg-gold text-zinc-950 hover:bg-gold-hover' : 'bg-[#e9e4d8] text-zinc-400'}`}
                title="Enviar mensagem (Enter)"
              >
                <Send className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </form>
      {emChamada ? (
        <div className="pointer-events-auto">
          <CallOverlay
            onClose={() => setEmChamada(false)}
            onEnd={transcricao => {
              if (!transcricao.length || !activeSessionId) return;
              appendLocalMessages(activeSessionId, transcricao.map(item => ({
                role: item.role,
                content: item.role === 'user' ? `(na ligação) ${item.text}` : item.text,
              })));
            }}
          />
        </div>
      ) : null}
    </div>
  );
};
