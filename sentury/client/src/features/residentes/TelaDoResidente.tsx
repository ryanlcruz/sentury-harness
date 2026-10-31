import React, { useEffect, useRef, useState } from 'react';
import { Hand, Play } from 'lucide-react';
import { getRuntimeConfig } from '../../runtime/config';

export const TelaDoResidente: React.FC<{ nome: string }> = ({ nome }) => {
  const conexao = useRef<WebSocket | null>(null);
  const imagem = useRef<HTMLImageElement | null>(null);
  const [quadro, setQuadro] = useState('');
  const [pessoa, setPessoa] = useState(false);
  const [ligada, setLigada] = useState(false);
  const [erro, setErro] = useState('');

  useEffect(() => {
    const config = getRuntimeConfig();
    const url = new URL(`${config.apiUrl || window.location.origin}/sentury/residentes/${encodeURIComponent(nome)}/tela`);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(url);
    conexao.current = socket;
    socket.onopen = () => {
      socket.send(JSON.stringify({ token: config.token }));
      setLigada(true);
      if (document.hidden) socket.send(JSON.stringify({ tipo: 'visibilidade', visivel: false }));
    };
    socket.onmessage = event => {
      try {
        const dados = JSON.parse(String(event.data)) as { tipo?: string; dados?: string; pessoa?: boolean; mensagem?: string };
        if (dados.tipo === 'quadro' && dados.dados) setQuadro(`data:image/jpeg;base64,${dados.dados}`);
        if (dados.tipo === 'controle') { setPessoa(Boolean(dados.pessoa)); setErro(''); }
        if (dados.tipo === 'erro') setErro(dados.mensagem || 'Não consegui abrir a tela.');
      } catch { setErro('A HQ enviou uma atualização de tela inválida.'); }
    };
    socket.onclose = () => setLigada(false);
    socket.onerror = () => setErro('Não consegui conectar à tela da HQ.');
    const visibilidade = () => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ tipo: 'visibilidade', visivel: !document.hidden }));
    };
    document.addEventListener('visibilitychange', visibilidade);
    return () => {
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
      socket.close();
      document.removeEventListener('visibilitychange', visibilidade);
      conexao.current = null;
    };
  }, [nome]);

  const enviar = (dados: Record<string, unknown>) => {
    if (conexao.current?.readyState === WebSocket.OPEN) conexao.current.send(JSON.stringify(dados));
  };
  const posicao = (event: React.MouseEvent | React.WheelEvent) => {
    const caixa = imagem.current?.getBoundingClientRect();
    return caixa ? { x: Math.max(0, Math.min(1280, (event.clientX - caixa.left) * 1280 / caixa.width)),
      y: Math.max(0, Math.min(800, (event.clientY - caixa.top) * 800 / caixa.height)) } : { x: 0, y: 0 };
  };

  return (
    <section aria-label={`Tela de ${nome}`} className="overflow-hidden rounded-2xl border border-[#e3ddcd] bg-[#fffdf8]">
      <header className="flex flex-wrap items-center gap-3 border-b border-[#e3ddcd] px-4 py-3">
        <p className="flex-1 text-sm">{pessoa ? 'Você está no controle. A tarefa espera.' : 'Navegador próprio do residente'}</p>
        <button type="button" disabled={!ligada} onClick={() => enviar({ tipo: pessoa ? 'devolver' : 'assumir' })}
          className="flex h-11 items-center gap-2 rounded-lg border border-[#d8cfbd] bg-white px-3 text-sm disabled:opacity-40">
          {pessoa ? <Play className="h-4 w-4" /> : <Hand className="h-4 w-4" />}{pessoa ? 'Devolver ao residente' : 'Assumir'}
        </button>
      </header>
      {erro ? <p role="alert" className="px-4 py-3 text-sm text-red-700">{erro}</p> : null}
      <div role="group" aria-label="Navegador: clique e teclado quando você assumir" tabIndex={pessoa ? 0 : -1}
        className="relative aspect-[16/10] bg-zinc-950 outline-none focus-visible:ring-2 focus-visible:ring-gold"
        onClick={event => {
          if (!pessoa) return;
          event.currentTarget.focus();
          enviar({ tipo: 'clicar', ...posicao(event) });
        }}
        onWheel={event => { if (pessoa) enviar({ tipo: 'rolar', ...posicao(event), delta: Math.max(-3000, Math.min(3000, event.deltaY)) }); }}
        onKeyDown={event => {
          if (!pessoa) return;
          if (event.key === 'Escape') { event.currentTarget.blur(); return; }
          event.preventDefault();
          if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) enviar({ tipo: 'texto', texto: event.key });
          else {
            const modificadores = (event.altKey ? 1 : 0) | (event.ctrlKey ? 2 : 0) | (event.metaKey ? 4 : 0) | (event.shiftKey ? 8 : 0);
            enviar({ tipo: 'pressionar', tecla: event.key, codigo: event.code, modificadores });
            enviar({ tipo: 'soltar', tecla: event.key, codigo: event.code, modificadores });
          }
        }}>
        {quadro ? <img ref={imagem} src={quadro} alt={`Navegador de ${nome}`} draggable={false} className="h-full w-full object-contain" />
          : <p className="absolute inset-0 flex items-center justify-center text-sm text-zinc-400">{ligada ? 'Esperando a imagem do navegador…' : 'Tela desconectada'}</p>}
      </div>
      <p className="px-4 py-2 text-xs text-zinc-500">Escape tira o foco do navegador. A tela para de transmitir quando esta aba fica invisível. Fechar a tela não devolve o controle.</p>
    </section>
  );
};
