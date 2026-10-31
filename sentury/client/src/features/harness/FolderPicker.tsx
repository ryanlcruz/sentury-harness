import React, { useCallback, useEffect, useState } from 'react';
import { ArrowUp, Check, Folder, X } from 'lucide-react';
import { apiClient } from '../../transport/http-client';
import { authHeaders } from '../../runtime/config';

interface Nivel {
  atual: string;
  pai: string;
  pastas: Array<{ nome: string; caminho: string }>;
}

interface FolderPickerProps {
  titulo: string;
  inicial?: string;
  onEscolher: (caminho: string) => void;
  onFechar: () => void;
}

/** Lista pastas pelo servidor, pois o navegador não expõe caminhos absolutos. */
export const FolderPicker: React.FC<FolderPickerProps> = ({ titulo, inicial, onEscolher, onFechar }) => {
  const [nivel, setNivel] = useState<Nivel>({ atual: '', pai: '', pastas: [] });
  const [carregando, setCarregando] = useState(true);

  const abrir = useCallback(async (caminho: string) => {
    setCarregando(true);
    try {
      setNivel(await apiClient.get<Nivel>(
        `/sentury/pastas/navegar?caminho=${encodeURIComponent(caminho)}`,
        { headers: authHeaders() },
      ));
    } catch {
      setNivel({ atual: caminho, pai: '', pastas: [] });
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { void abrir(inicial || ''); }, [abrir, inicial]);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-zinc-900/30 p-4">
      <div className="flex max-h-[70vh] w-[min(560px,100%)] flex-col overflow-hidden rounded-2xl border border-stone-300 bg-[#fffdf8] shadow-2xl">
        <header className="flex items-center gap-3 border-b border-stone-200 px-5 py-3.5">
          <Folder className="h-4 w-4 shrink-0 text-gold-hover" />
          <h3 className="text-sm font-semibold text-zinc-900">{titulo}</h3>
          <button
            type="button"
            onClick={onFechar}
            aria-label="Fechar"
            className="ml-auto rounded-md p-1 text-zinc-400 hover:bg-stone-100 hover:text-zinc-800"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex items-center gap-2 border-b border-stone-200 px-5 py-2.5">
          <button
            type="button"
            disabled={!nivel.pai}
            onClick={() => void abrir(nivel.pai)}
            title="Subir um nível"
            className="rounded-md border border-stone-300 p-1.5 text-zinc-600 hover:border-gold disabled:opacity-30"
          >
            <ArrowUp className="h-3.5 w-3.5" />
          </button>
          <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-zinc-600" title={nivel.atual}>
            {nivel.atual || '…'}
          </span>
        </div>

        <ul className="flex-1 overflow-y-auto px-3 py-2">
          {carregando && <li className="px-2 py-3 text-xs text-zinc-500">Lendo a pasta…</li>}
          {!carregando && nivel.pastas.length === 0 && (
            <li className="px-2 py-3 text-xs text-zinc-500">Nenhuma subpasta aqui.</li>
          )}
          {nivel.pastas.map(pasta => (
            <li key={pasta.caminho}>
              <button
                type="button"
                onDoubleClick={() => void abrir(pasta.caminho)}
                onClick={() => void abrir(pasta.caminho)}
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] text-zinc-700 hover:bg-[#efece2]"
              >
                <Folder className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
                <span className="truncate">{pasta.nome}</span>
              </button>
            </li>
          ))}
        </ul>

        <footer className="flex items-center gap-3 border-t border-stone-200 px-5 py-3">
          <p className="min-w-0 flex-1 truncate text-[11.5px] text-zinc-500">
            Escolhe a pasta aberta acima.
          </p>
          <button
            type="button"
            onClick={onFechar}
            className="rounded-lg border border-stone-300 px-3 py-2 text-xs font-semibold text-zinc-700"
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={!nivel.atual}
            onClick={() => onEscolher(nivel.atual)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-gold disabled:opacity-40"
          >
            <Check className="h-3.5 w-3.5" />Usar esta
          </button>
        </footer>
      </div>
    </div>
  );
};
