import React, { useEffect, useState } from 'react';
import { ChevronRight, Folder, FolderOpen, Globe } from 'lucide-react';
import { SeletorDePasta } from './SeletorDePasta';
import { apiClient } from '../../transport/http-client';
import { authHeaders } from '../../runtime/config';

/**
 * Mostra e altera a pasta ativa junto ao chat, onde ela afeta o pedido.
 * A gestão de várias pastas liberadas continua na tela do Harness.
 */

interface Pastas {
  projeto: string;
  extras: string[];
  universal: boolean;
  trabalhando_na_instalacao: boolean;
}

const nomeCurto = (caminho: string): string => {
  const partes = caminho.replace(/[\\/]+$/, '').split(/[\\/]/);
  return partes[partes.length - 1] || caminho;
};

export const PastaAtiva: React.FC<{ onAbrirHarness?: () => void }> = ({ onAbrirHarness }) => {
  const [pastas, setPastas] = useState<Pastas | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [escolhendo, setEscolhendo] = useState(false);

  useEffect(() => {
    let vivo = true;
    apiClient
      .get<Pastas>('/sentury/pastas', { headers: authHeaders() })
      .then(dados => { if (vivo) setPastas(dados); })
      // Falhar aqui não pode tirar o composer do ar: sem o chip a conversa
      // continua, só sem a informação.
      .catch(() => undefined);
    return () => { vivo = false; };
  }, []);

  if (!pastas) return null;

  const liberadas = pastas.extras.length;
  const rotulo = pastas.universal
    ? 'Computador inteiro'
    : pastas.trabalhando_na_instalacao && !liberadas
      ? 'Nenhuma pasta'
      : nomeCurto(pastas.projeto);

  const detalhe = pastas.universal
    ? 'Acesso a arquivos em qualquer pasta'
    : `Trabalho: ${pastas.projeto}${liberadas ? ` · mais ${liberadas} liberada${liberadas > 1 ? 's' : ''}` : ''}`;

  const Icone = pastas.universal ? Globe : liberadas || !pastas.trabalhando_na_instalacao ? FolderOpen : Folder;

  const reler = async () => {
    // Relê em vez de supor: o servidor decide o que cada mudança faz com as
    // pastas extras, e supor aqui deixaria a tela mentindo.
    try {
      setPastas(await apiClient.get<Pastas>('/sentury/pastas', { headers: authHeaders() }));
    } catch {
      // Mantém o que está na tela, que é o último estado real conhecido.
    }
  };

  const escolherPasta = async (caminho: string) => {
    setSalvando(true);
    try {
      await apiClient.put('/sentury/pastas/trabalho', { caminho }, { headers: authHeaders() });
      await reler();
      setEscolhendo(false);
    } catch {
      // Sem permissão ou caminho recusado: o seletor continua aberto.
    } finally {
      setSalvando(false);
    }
  };

  const alternarUniversal = async () => {
    if (salvando) return;
    setSalvando(true);
    const alvo = !pastas.universal;
    try {
      await apiClient.put('/sentury/pastas/trabalho', { universal: alvo }, { headers: authHeaders() });
      await reler();
    } catch {
      // Sem permissão ou API fora: o estado na tela continua o real.
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="rounded-xl">
    <div className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-zinc-700 transition-colors hover:bg-stone-100">
      <Icone className={`h-4 w-4 shrink-0 ${pastas.universal ? 'text-gold-hover' : ''}`} />
      <span className="min-w-0 flex-1">
        <strong className="block text-xs font-semibold text-zinc-900">Área de trabalho</strong>
        <small className="mt-0.5 flex min-w-0 items-center gap-1 text-[10px] text-zinc-500">
          <span className="truncate">{rotulo}</span>
          {liberadas > 0 && !pastas.universal ? <span className="shrink-0">+{liberadas}</span> : null}
        </small>
      </span>

      <button
        type="button"
        role="switch"
        aria-checked={pastas.universal}
        aria-label="Liberar o computador inteiro"
        disabled={salvando}
        onClick={event => { event.stopPropagation(); void alternarUniversal(); }}
        title={pastas.universal
          ? 'Desligar: ele volta a enxergar só a pasta de trabalho'
          : 'Ligar: ele passa a ler e escrever em qualquer pasta'}
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ${pastas.universal ? 'bg-gold-hover' : 'bg-stone-300'}`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${pastas.universal ? 'left-[1.125rem]' : 'left-0.5'}`}
        />
      </button>

      <button
        type="button"
        onClick={() => setEscolhendo(valor => !valor)}
        title={`${detalhe}\nTrocar a pasta de trabalho.`}
        aria-label="Trocar a pasta de trabalho"
        aria-expanded={escolhendo}
        className="shrink-0 rounded-lg p-1 text-zinc-400 transition-colors hover:bg-stone-200 hover:text-zinc-600"
      >
        <ChevronRight className={`h-3.5 w-3.5 transition-transform ${escolhendo ? 'rotate-90' : ''}`} />
      </button>
      </div>

      {escolhendo ? (
        <>
          <SeletorDePasta
            inicial={pastas.projeto}
            onEscolher={escolherPasta}
            onCancelar={() => setEscolhendo(false)}
          />
          {onAbrirHarness ? (
            <button
              type="button"
              onClick={onAbrirHarness}
              className="mx-1.5 mb-1 rounded-lg px-1.5 py-1 text-left text-[10px] text-zinc-400 transition-colors hover:text-zinc-700"
            >
              Liberar mais de uma pasta, no Harness
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
};
