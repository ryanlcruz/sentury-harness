import { useCallback, useEffect, useRef, useState } from 'react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';

const Estado = z.object({
  estado: z.string().optional(), detalhe: z.string().optional(), configurada: z.boolean().default(false),
  instalado: z.boolean().optional(), disponivel: z.boolean().optional(), instalacao_url: z.string().optional(),
  metodo: z.enum(['direto', 'cli']).optional(),
  ativa: z.string().optional(), tentativa: z.string().optional(),
  contas: z.array(z.object({ id: z.string(), label: z.string(), email: z.string().default(''), configurada: z.boolean() })).default([]),
});

async function api(caminho: string, method = 'GET', conta?: string, metodo?: string) {
  const config = getRuntimeConfig();
  const resposta = await fetch(config.apiUrl.replace(/\/$/, '') + '/sentury/robinbandit' + caminho, {
    method, headers: { ...authHeaders(), 'Content-Type': 'application/json', 'X-RobinBandit-Login': '1' },
    ...(method === 'POST' ? { body: JSON.stringify({ conta: conta || '', metodo: metodo || '' }) } : {}), signal: AbortSignal.timeout(25000),
  });
  const dado: unknown = await resposta.json();
  if (!resposta.ok) {
    const erro = z.object({ detail: z.string() }).safeParse(dado);
    throw new Error(erro.success ? erro.data.detail : 'Não foi possível conectar.');
  }
  return dado;
}

export function ConectarConta({ provedor, tipo, loginDireto = false, onConnected }: { provedor: string; tipo: string; loginDireto?: boolean; onConnected: () => Promise<void> }) {
  const [status, setStatus] = useState<z.infer<typeof Estado> | null>(null);
  const [tentativa, setTentativa] = useState<string | null>(null);
  const [mensagem, setMensagem] = useState('Verificando conexão…');
  const [ocupado, setOcupado] = useState(false);
  const [rever, setRever] = useState(0);
  const vivo = useRef(true);
  const direto = tipo === 'chatgpt_oauth' || loginDireto;
  const base = '/login/' + encodeURIComponent(provedor);

  const carregar = useCallback(async () => {
    const estado = Estado.parse(await api(base));
    if (!vivo.current) return;
    setStatus(estado);
    if (estado.tentativa) setTentativa(estado.tentativa);
    setMensagem(estado.configurada ? (estado.metodo === 'cli' ? 'ChatGPT conectado pelo Codex CLI.' : 'Conta conectada.') : direto
      ? 'Entre pelo navegador com um plano elegível. Não precisa instalar Codex.'
      : estado.instalado ? 'CLI instalado, falta entrar na conta.' : 'Instale o CLI oficial. Desktop não é obrigatório.');
  }, [base, direto]);

  useEffect(() => {
    vivo.current = true;
    void carregar().catch(() => { if (vivo.current) setMensagem('Não foi possível verificar a conexão.'); });
    return () => { vivo.current = false; };
  }, [carregar]);

  useEffect(() => {
    if (!tentativa) return;
    let ativo = true;
    let timer: ReturnType<typeof setTimeout>;
    async function conferir() {
      try {
        const estado = Estado.parse(await api('/login/tentativas/' + encodeURIComponent(tentativa!)));
        if (!ativo) return;
        setMensagem(estado.detalhe || ({ aguardando: 'Conclua o login no navegador aberto.', validando: 'Validando a autorização.',
          conectado: 'Conta conectada.', cancelado: 'Login cancelado.', expirado: 'O login expirou. Tente novamente.',
          falhou: 'Login não foi concluído. Tente novamente ou use o comando oficial no terminal.' }[estado.estado || ''] || 'Verificando conexão…'));
        if (['aguardando', 'validando'].includes(estado.estado || '')) timer = setTimeout(conferir, 2000);
        else {
          setTentativa(null);
          if (estado.configurada) await onConnected();
          await carregar();
          if (!estado.configurada) setMensagem(estado.detalhe || 'O login não foi concluído. Tente novamente.');
        }
      } catch {
        if (ativo) setMensagem('A consulta falhou. Verifique novamente ou cancele o login.');
      }
    }
    void conferir();
    return () => { ativo = false; clearTimeout(timer); };
  }, [tentativa, rever, carregar, onConnected]);

  async function acao(executar: () => Promise<void>) {
    setOcupado(true);
    try { await executar(); }
    catch (erro) { if (vivo.current) setMensagem(erro instanceof Error ? erro.message : 'Não foi possível conectar.'); }
    finally { if (vivo.current) setOcupado(false); }
  }

  async function iniciar(conta = '', metodo = '') {
    const dado = z.object({ id: z.string() }).parse(await api(base, 'POST', conta, metodo));
    if (vivo.current) setTentativa(dado.id);
  }

  const classe = 'rounded-lg border border-stone-300 px-3 py-2 text-xs font-medium hover:border-gold disabled:opacity-40';
  return <div className="mt-2 w-full space-y-2">
    <p role="status" aria-live="polite" className="text-xs leading-5 text-zinc-600">{mensagem}</p>
    <div className="flex flex-wrap items-center gap-2">
      {tentativa ? <>
        <button type="button" className={classe} onClick={() => setRever(n => n + 1)}>Verificar novamente</button>
        <button type="button" className={classe} disabled={ocupado} onClick={() => void acao(async () => {
          await api('/login/tentativas/' + tentativa, 'DELETE'); setTentativa(null); await carregar();
        })}>Cancelar login</button>
      </> : direto ? <>
        <button type="button" className={classe} disabled={ocupado || !status?.disponivel} onClick={() => void acao(() => iniciar())}>Continuar com ChatGPT</button>
        {loginDireto && (status?.instalado
          ? <button type="button" className={classe} disabled={ocupado} onClick={() => void acao(() => iniciar('', 'cli'))}>Usar Codex CLI</button>
          : status?.instalacao_url && <a href={status.instalacao_url} target="_blank" rel="noopener noreferrer" className={classe}>Alternativa: instalar Codex CLI</a>)}
        {status && !status.disponivel && <span className="text-xs text-zinc-500">Instale a opção auth do RB da pasta local para habilitar.</span>}
        {status?.contas.map(conta => <div key={conta.id} className="flex flex-wrap items-center gap-2">
          <button type="button" className={classe} disabled={ocupado} onClick={() => void acao(async () => {
            if (!conta.configurada) { await iniciar(conta.id); return; }
            await api(base + '/selecionar', 'POST', conta.id); await onConnected(); await carregar();
          })}>{conta.label}{conta.email ? ` (${conta.email})` : ''}{status.ativa === conta.id && status.metodo !== 'cli' ? ' · ativa' : ''}</button>
          {conta.configurada && <button type="button" className={classe} disabled={ocupado} onClick={() => void acao(async () => {
            const r = z.object({ revogacao_confirmada: z.boolean() }).parse(await api(base + '/sair', 'POST', conta.id));
            await onConnected(); await carregar();
            if (!r.revogacao_confirmada) setMensagem('Desconectado aqui. Confirme a remoção em Configurações do ChatGPT.');
          })}>Desconectar {conta.label}</button>}
        </div>)}
      </> : status?.instalado ? <>
        <button type="button" className={classe} disabled={ocupado} onClick={() => void acao(() => iniciar())}>Entrar pelo CLI oficial</button>
        <button type="button" className={classe} disabled={ocupado} onClick={() => void acao(async () => { await carregar(); await onConnected(); })}>Verificar conexão</button>
        <code className="text-xs text-zinc-500">{tipo === 'claude_cli' ? 'claude auth login' : 'codex login'}</code>
      </> : <>
        {status?.instalacao_url && <a href={status.instalacao_url} target="_blank" rel="noopener noreferrer" className={classe}>Como instalar</a>}
        <button type="button" className={classe} disabled={ocupado} onClick={() => void acao(carregar)}>Já instalei, verificar</button>
      </>}
    </div>
    {direto && <a href="https://chatgpt.com/#settings/Usage" target="_blank" rel="noopener noreferrer" className="text-xs text-zinc-500 underline">Uso e permissões no ChatGPT</a>}
  </div>;
}
