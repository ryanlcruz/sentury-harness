import React, { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, Folder, Loader2 } from 'lucide-react';
import { apiClient } from '../../transport/http-client';
import { authHeaders } from '../../runtime/config';

/**
 * Escolher a pasta de trabalho sem sair da conversa.
 *
 * Quem lista é o servidor: o navegador do browser não entrega o caminho
 * absoluto de uma pasta escolhida, por segurança dele. Aqui só se anda pela
 * árvore e se confirma — o Harness continua existindo para o resto (liberar
 * pastas extras, ver o que está valendo).
 */

interface Navegacao {
  atual: string;
  pai: string;
  pastas: { nome: string; caminho: string }[];
}

interface Props {
  /** Onde a navegação começa: a pasta de trabalho de hoje. */
  inicial?: string;
  onEscolher: (caminho: string) => void | Promise<void>;
  onCancelar: () => void;
}

export const SeletorDePasta: React.FC<Props> = ({ inicial, onEscolher, onCancelar }) => {
  const [nav, setNav] = useState<Navegacao | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState('');

  const navegar = useCallback((caminho: string) => {
    setCarregando(true);
    setErro('');
    apiClient
      .get<Navegacao>(`/sentury/pastas/navegar?caminho=${encodeURIComponent(caminho)}`, { headers: authHeaders() })
      .then(setNav)
      .catch(() => setErro('não consegui abrir esta pasta'))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => { navegar(inicial || ''); }, [inicial, navegar]);

  return (
    <div className="px-1.5 pb-1.5">
      <div className="flex items-center gap-1.5 px-1.5 pb-1.5">
        <button
          type="button"
          onClick={() => (nav?.pai ? navegar(nav.pai) : onCancelar())}
          className="rounded-lg p-1 text-zinc-500 transition-colors hover:bg-stone-200 hover:text-zinc-800"
          aria-label={nav?.pai ? 'Subir uma pasta' : 'Voltar'}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <span className="min-w-0 flex-1 truncate text-[10px] text-zinc-500" title={nav?.atual}>
          {carregando ? 'abrindo…' : nav?.atual}
        </span>
        <button
          type="button"
          disabled={!nav?.atual || carregando}
          onClick={() => nav?.atual && void onEscolher(nav.atual)}
          className="rounded-lg bg-gold px-2.5 py-1 text-[10px] font-semibold text-zinc-900 transition-colors hover:bg-gold-hover disabled:opacity-50"
        >
          Trabalhar aqui
        </button>
      </div>

      <div className="max-h-56 overflow-y-auto">
        {carregando ? (
          <p className="flex items-center gap-2 px-3 py-2 text-[10px] text-zinc-400">
            <Loader2 className="h-3 w-3 animate-spin" /> lendo as pastas
          </p>
        ) : erro ? (
          <p className="px-3 py-2 text-[10px] text-red-600">{erro}</p>
        ) : nav && nav.pastas.length === 0 ? (
          <p className="px-3 py-2 text-[10px] text-zinc-400">Nenhuma subpasta aqui — dá para trabalhar nesta mesma.</p>
        ) : (
          nav?.pastas.map(pasta => (
            <button
              key={pasta.caminho}
              type="button"
              onClick={() => navegar(pasta.caminho)}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left transition-colors hover:bg-stone-100"
            >
              <Folder className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
              <span className="truncate text-[11px] text-zinc-700">{pasta.nome}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
};
