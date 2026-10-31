import React, { useEffect, useState } from 'react';
import { Check, CircleAlert, RefreshCw } from 'lucide-react';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import { ChromeDoAgente } from './ChromeDoAgente';

/** A porta da API que esta tela usa, ou "" quando não dá para saber. */
function portaDaApi(): string {
  try {
    const url = new URL(apiClient.getBaseUrl() || window.location.origin);
    return url.port || (url.protocol === 'https:' ? '443' : '80');
  } catch { return ''; }
}

export const BrowserConnectionSection: React.FC = () => {
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    const check = () => {
      void apiClient.get<{ conectada: boolean }>('/sentury/navegador/extensao/estado', { headers: authHeaders() })
        .then(result => {
          if (!active) return;
          setConnected(result.conectada);
        })
        .catch(() => { if (active) setConnected(null); });
    };
    check();
    const timer = window.setInterval(check, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  // A extensão procura o Sentury na porta 8000: outra porta nunca é encontrada por ela.
  const porta = portaDaApi();

  return (
    <section aria-label="Conexão do navegador">
      <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Navegador</p>
      <h2 className="mt-1 text-3xl font-semibold tracking-tight">Navegador do agente</h2>
      <p className="mt-2 max-w-2xl text-sm text-zinc-500">O Sentury abre e controla somente as abas que sua extensão criar. Fechar uma aba interrompe o acesso a ela; suas outras abas não são adotadas.</p>
      <div className="mt-7 max-w-2xl rounded-2xl border border-stone-200 bg-white/80 p-5 shadow-sm">
        <div className="flex items-center gap-2 text-sm font-semibold">
          {connected === true ? <Check className="h-4 w-4 text-emerald-600" /> : connected === false ? <CircleAlert className="h-4 w-4 text-amber-600" /> : <RefreshCw className="h-4 w-4 animate-spin text-zinc-400" />}
          {connected === true ? 'Chrome conectado' : connected === false ? 'Extensão não conectada' : 'Verificando conexão…'}
        </div>
        {connected !== true ? (
          <div className="mt-4 space-y-3 text-xs leading-5 text-zinc-600">
            <p>1. Em <code className="rounded bg-stone-100 px-1">chrome://extensions</code>, carregue a pasta <code className="rounded bg-stone-100 px-1">sentury/browser_extension</code> sem compactação e deixe a extensão ativada.</p>
            <p>2. A extensão se conecta sozinha, sem código. Se não aparecer conectada em alguns segundos, clique no ícone do Tato na barra do Chrome e em “Tentar de novo”.</p>
            {porta && porta !== '8000' ? <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">Este Sentury está na porta {porta}, e a extensão procura o Sentury na 8000. Para usar o navegador, abra o Sentury na porta 8000.</p> : null}
            <p>A permissão de depuração do Chrome é ampla; o código da extensão limita as ações às abas que ela própria abre. Sem conexão, o Sentury não muda silenciosamente para outro navegador.</p>
          </div>
        ) : <p className="mt-2 text-xs text-zinc-500">Pronto para usar <code>@navegador</code>. Uma nova aba do Sentury trará o Chrome para a frente; as ações seguintes continuarão nela.</p>}
      </div>
      <ChromeDoAgente />
    </section>
  );
};
