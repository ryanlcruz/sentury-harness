import React, { useEffect, useState } from 'react';
import { Check, ChevronDown, ChevronRight, Circle, ExternalLink, Globe, Hand, LoaderCircle, Power, TriangleAlert } from 'lucide-react';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { useChatStore } from '../../stores/chat-store';
import { CartaoNavegador, PassoNavegador, duracao } from './navegador';
import { SetaDoAgente } from './SetaDoAgente';
import { encerrarSuperficie, superficieAberta } from './superficie';

/**
 * O que o navegador está fazendo, no chat — sem tela.
 *
 * A tela é a própria janela do navegador, aberta ao lado, com a borda e a
 * seta da Sentury. Aqui fica o que ajuda a acompanhar e decidir: a ação de
 * agora, o roteiro (feito, fazendo, falta), quantas leituras foram texto e
 * quantas foram print, e os botões Mostrar janela e Assumir.
 *
 * Ao vivo durante o turno; depois, compacto na mensagem, com "Ver passos".
 */

async function mostrarJanela(sessionId: string): Promise<boolean> {
  const config = getRuntimeConfig();
  apiClient.setBaseUrl(config.apiUrl);
  try {
    const r = await apiClient.post<{ ok: boolean }>('/sentury/navegador/mostrar', { session_id: sessionId }, { headers: authHeaders() });
    return Boolean(r.ok);
  } catch {
    return false;
  }
}

function IconeDoPasso({ status }: { status: string }) {
  if (status === 'ok') return <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />;
  if (status === 'running') return <LoaderCircle className="h-3.5 w-3.5 shrink-0 animate-spin text-gold-ink" />;
  if (status === 'error') return <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-amber-600" />;
  return <Circle className="h-2.5 w-2.5 shrink-0 text-zinc-300" />;
}

function Passos({ passos }: { passos: PassoNavegador[] }) {
  return (
    <ol className="space-y-0.5 px-3 py-2">
      {passos.map((p, i) => {
        const [acao, ...resto] = p.rotulo.split(' · ');
        const ativo = p.status === 'running';
        return (
          <li key={i} className={`flex items-center gap-2.5 rounded-md px-2 py-1 text-xs ${ativo ? 'bg-gold-soft' : ''}`}>
            <IconeDoPasso status={p.status} />
            <span className={`w-16 shrink-0 font-mono ${p.status === 'pendente' ? 'text-zinc-400' : 'text-zinc-700'} ${ativo ? 'font-semibold' : ''}`}>{acao}</span>
            <span className={`min-w-0 flex-1 truncate ${p.status === 'pendente' ? 'text-zinc-400' : 'text-zinc-700'}`}>{resto.join(' · ')}</span>
            {p.leitura ? <span className="shrink-0 font-mono text-[10px] text-zinc-400">{p.leitura}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}

const ROTULO_DO_ESTADO: Record<string, { texto: string; classe: string }> = {
  rodando: { texto: 'rodando', classe: 'bg-emerald-50 text-emerald-700' },
  ok: { texto: 'etapa concluída', classe: 'text-emerald-700' },
  parou: { texto: 'parou', classe: 'bg-amber-50 text-amber-800' },
  erro: { texto: 'falhou', classe: 'bg-amber-50 text-amber-800' },
};

export const NavegadorCard: React.FC<{ cartao: CartaoNavegador; sessionId: string; aoVivo?: boolean; latest?: boolean }> = ({ cartao, sessionId, aoVivo = false, latest = false }) => {
  const [aberto, setAberto] = useState(false);
  const [semJanela, setSemJanela] = useState(false);
  const [sessaoAberta, setSessaoAberta] = useState<boolean | null>(null);
  const [chromeConectado, setChromeConectado] = useState(false);
  const [erroAoEncerrar, setErroAoEncerrar] = useState(false);
  const [erroAoReabrir, setErroAoReabrir] = useState(false);
  const [, tique] = useState(0);
  const abortStreaming = useChatStore(state => state.abortStreaming);
  const rodando = aoVivo && cartao.status === 'rodando';

  // Relógio ao vivo: o cartão re-renderiza a cada segundo enquanto roda.
  useEffect(() => {
    if (!rodando) return;
    const id = window.setInterval(() => tique(n => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [rodando]);

  useEffect(() => {
    if (!latest || aoVivo) return;
    let ativo = true;
    apiClient.setBaseUrl(getRuntimeConfig().apiUrl);
    const atualizar = () => {
      void superficieAberta('navegador', sessionId)
        .then(valor => { if (ativo) setSessaoAberta(valor); })
        .catch(() => { if (ativo) setSessaoAberta(null); });
      void apiClient.get<{ conectada: boolean }>('/sentury/navegador/extensao/estado', { headers: authHeaders() })
        .then(valor => { if (ativo) setChromeConectado(valor.conectada); })
        .catch(() => { if (ativo) setChromeConectado(false); });
    };
    atualizar();
    const timer = window.setInterval(atualizar, 5000);
    return () => { ativo = false; window.clearInterval(timer); };
  }, [latest, aoVivo, sessionId]);

  const passos = cartao.passos || [];
  const atual = passos.find(p => p.status === 'running') || null;
  const feitos = passos.filter(p => p.status === 'ok' || p.status === 'error').length;
  const tempo = rodando && cartao.inicio ? Date.now() - cartao.inicio : cartao.duracao_ms;
  const estado = ROTULO_DO_ESTADO[cartao.status] || ROTULO_DO_ESTADO.ok;
  const mostrar = async () => setSemJanela(!(await mostrarJanela(sessionId)));
  const encerrar = async () => {
    if (!window.confirm('Encerrar este navegador? Abas e dados não salvos nesta sessão serão perdidos.')) return;
    try {
      await encerrarSuperficie('navegador', sessionId);
      setSessaoAberta(false);
      setErroAoEncerrar(false);
    } catch {
      setErroAoEncerrar(true);
    }
  };
  const reabrir = async () => {
    try {
      await apiClient.post('/sentury/navegador/extensao/nova-aba', { session_id: sessionId }, { headers: authHeaders() });
      setSessaoAberta(true);
      setErroAoReabrir(false);
    } catch {
      setErroAoReabrir(true);
    }
  };
  const botao = 'inline-flex h-8 items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 text-xs font-medium text-zinc-800 hover:bg-stone-100';

  if (!aoVivo) {
    return (
      <section aria-label="Execução no navegador" className="mb-3 max-w-3xl overflow-hidden rounded-xl border border-stone-300 bg-[#fffdf8]">
        <button type="button" onClick={() => setAberto(v => !v)} className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left">
          {aberto ? <ChevronDown className="h-3.5 w-3.5 text-zinc-400" /> : <ChevronRight className="h-3.5 w-3.5 text-zinc-400" />}
          <Globe className="h-4 w-4 text-gold-ink" />
          <span className="text-[13px] font-semibold text-zinc-900">Navegador</span>
          {cartao.site ? <span className="rounded-md bg-stone-100 px-2 py-0.5 font-mono text-[11px] text-zinc-600">{cartao.site}</span> : null}
          {cartao.retomada ? <span className="text-[11px] text-zinc-500">continuação</span> : null}
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${estado.classe}`}>
            {cartao.status === 'ok' ? `etapa concluída em ${duracao(cartao.duracao_ms)}` : estado.texto}
          </span>
          <span className="flex-1" />
          <span className="text-[11px] text-zinc-500">
            {passos.length} {passos.length === 1 ? 'ação' : 'ações'} · {cartao.textos} em texto · {cartao.prints} {cartao.prints === 1 ? 'leitura visual' : 'leituras visuais'}
          </span>
        </button>
        {cartao.motivo && cartao.status !== 'ok' ? (
          <p className="border-t border-stone-200 px-3.5 py-2 text-xs text-amber-800">{cartao.motivo}</p>
        ) : null}
        {latest ? (
          <div className="flex items-center gap-2 border-t border-stone-200 px-3.5 py-2 text-xs text-zinc-600">
            <span>{sessaoAberta === false ? 'Sessão não está aberta' : sessaoAberta ? 'Sessão disponível para continuar nesta conversa' : 'Verificando sessão…'}</span>
            <span className="flex-1" />
            {sessaoAberta ? (
              <>
                <button type="button" onClick={mostrar} className={botao}><ExternalLink className="h-3.5 w-3.5" />Mostrar</button>
                <button type="button" onClick={() => void encerrar()} className={botao}><Power className="h-3.5 w-3.5" />Encerrar</button>
              </>
            ) : null}
            {sessaoAberta === false && chromeConectado ? (
              <button type="button" onClick={() => void reabrir()} className={botao}>Abrir nova aba do Sentury</button>
            ) : null}
          </div>
        ) : null}
        {erroAoReabrir ? <p role="alert" className="px-3.5 pb-2 text-xs text-red-700">Não consegui abrir uma nova aba. Confira a conexão com a extensão.</p> : null}
        {erroAoEncerrar ? <p role="alert" className="px-3.5 pb-2 text-xs text-red-700">Não consegui encerrar a sessão. Tente novamente.</p> : null}
        {semJanela ? <p className="px-3.5 pb-2 text-xs text-zinc-500">A janela não está visível nesta máquina.</p> : null}
        {aberto ? <div className="border-t border-stone-200"><Passos passos={passos} /></div> : null}
      </section>
    );
  }

  return (
    <section aria-label="Execução no navegador" className="mb-5 max-w-3xl overflow-hidden rounded-xl border border-stone-300 bg-[#fffdf8] shadow-[0_10px_28px_rgba(24,24,27,.07)]">
      <header className="flex flex-wrap items-center gap-2.5 border-b border-stone-200 px-4 py-2.5">
        <Globe className="h-4 w-4 text-gold-ink" />
        <span className="text-[13px] font-semibold text-zinc-900">Navegador</span>
        {cartao.site ? <span className="rounded-md bg-stone-100 px-2 py-0.5 font-mono text-[11px] text-zinc-600">{cartao.site}</span> : null}
        {cartao.retomada ? <span className="text-[11px] text-zinc-500">continuação</span> : null}
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${estado.classe}`}>
          {rodando ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" /> : null}{estado.texto}
        </span>
        <span className="flex-1" />
        <span className="font-mono text-[11px] text-zinc-500">{duracao(tempo)}</span>
        <button type="button" onClick={mostrar} className={botao} title="Traz a janela do navegador para a frente">
          <ExternalLink className="h-3.5 w-3.5" />Mostrar janela
        </button>
        <button type="button" onClick={() => { abortStreaming(sessionId); void mostrar(); }} className={botao}
          title="Para o turno e deixa o navegador com você">
          <Hand className="h-3.5 w-3.5" />Assumir
        </button>
      </header>
      {semJanela ? (
        <p className="border-b border-stone-200 px-4 py-1.5 text-[11px] text-zinc-500">
          O navegador está rodando escondido nesta máquina (sem tela). Para ver a janela: SENTURY_BROWSER_VISIVEL=sim.
        </p>
      ) : null}
      {atual ? (
        <div className="flex items-center gap-3 border-b border-[#f3e8b0] bg-[#fffbe6] px-4 py-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-zinc-900">
            <SetaDoAgente tamanho={16} />
          </span>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-gold-ink">Agora</p>
            <p className="truncate text-sm font-semibold text-zinc-900">{atual.rotulo}</p>
          </div>
        </div>
      ) : null}
      <Passos passos={passos} />
      <footer className="flex items-center gap-4 border-t border-stone-200 bg-[#fbfaf6] px-4 py-2 text-[11px] text-zinc-600">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-emerald-600" />{cartao.textos} leituras em texto</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-amber-500" />{cartao.prints} {cartao.prints === 1 ? 'leitura visual' : 'leituras visuais'}</span>
        <span className="flex-1" />
        <span className="h-1.5 w-32 overflow-hidden rounded-full bg-stone-200">
          <span className="block h-1.5 bg-gold transition-[width] duration-500" style={{ width: `${passos.length ? Math.round((feitos / passos.length) * 100) : 0}%` }} />
        </span>
        <span className="font-mono text-zinc-500">{feitos} de {passos.length}</span>
      </footer>
    </section>
  );
};
