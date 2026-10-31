import React, { useCallback, useEffect, useState } from 'react';
import { FolderPlus, RefreshCw, ShieldCheck, Terminal, Trash2 } from 'lucide-react';
import { PermissionsSection } from '../settings/PermissionsSection';
import { FolderPicker } from './FolderPicker';
import { apiClient } from '../../transport/http-client';
import { authHeaders } from '../../runtime/config';

interface Ambiente {
  shell_ligado?: boolean;
  sistema?: string;
  shell?: string;
  diretorio?: string;
}

/** O Harness como sistema: o que ele deixa o agente fazer.
 *
 * O item do menu abria o mesmo painel do botão de debug, e o turno atual
 * aparecia duas vezes enquanto isto aqui não aparecia em lugar nenhum.
 * Diagnóstico do turno é do debug, ao lado da conversa.
 */
interface Pastas {
  projeto?: string;
  extras?: string[];
  universal?: boolean;
  instalacao?: string;
  trabalhando_na_instalacao?: boolean;
}

export const HarnessView: React.FC = () => {
  const [ambiente, setAmbiente] = useState<Ambiente>({});
  const [carregando, setCarregando] = useState(true);
  const [pastas, setPastas] = useState<Pastas>({});
  const [novaPasta, setNovaPasta] = useState('');
  const [novoTrabalho, setNovoTrabalho] = useState('');
  const [escolhendo, setEscolhendo] = useState<'trabalho' | 'extra' | null>(null);
  const [erroPasta, setErroPasta] = useState('');

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const dados = await apiClient.get<{ ambiente?: Ambiente }>(
        '/sentury/permissoes', { headers: authHeaders() });
      setAmbiente(dados?.ambiente || {});
    } catch {
      setAmbiente({});
    }
    try {
      setPastas(await apiClient.get<Pastas>('/sentury/pastas', { headers: authHeaders() }));
    } catch {
      setPastas({});
    } finally {
      setCarregando(false);
    }
  }, []);

  const liberar = useCallback(async () => {
    const caminho = novaPasta.trim();
    if (!caminho) return;
    setErroPasta('');
    try {
      await apiClient.post('/sentury/pastas', { caminho }, { headers: authHeaders() });
      setNovaPasta('');
      await carregar();
    } catch (motivo) {
      setErroPasta(motivo instanceof Error ? motivo.message : String(motivo));
    }
  }, [novaPasta, carregar]);

  const trocarTrabalho = useCallback(async () => {
    const caminho = novoTrabalho.trim();
    if (!caminho) return;
    setErroPasta('');
    try {
      await apiClient.put('/sentury/pastas/trabalho', { caminho }, { headers: authHeaders() });
      setNovoTrabalho('');
      await carregar();
    } catch (motivo) {
      setErroPasta(motivo instanceof Error ? motivo.message : String(motivo));
    }
  }, [novoTrabalho, carregar]);

  const alternarShell = useCallback(async (ligado: boolean) => {
    try {
      await apiClient.put('/sentury/shell', { ligado }, { headers: authHeaders() });
      await carregar();
    } catch { /* a tela continua como esta */ }
  }, [carregar]);

  const alternarUniversal = useCallback(async (ligado: boolean) => {
    try {
      await apiClient.put('/sentury/pastas/trabalho', { universal: ligado }, { headers: authHeaders() });
      await carregar();
    } catch { /* a tela continua como esta */ }
  }, [carregar]);

  const tirar = useCallback(async (caminho: string) => {
    try {
      await apiClient.delete(
        `/sentury/pastas?caminho=${encodeURIComponent(caminho)}`, { headers: authHeaders() });
      await carregar();
    } catch { /* a lista continua como esta */ }
  }, [carregar]);

  useEffect(() => { void carregar(); }, [carregar]);

  return (
    <section className="h-full overflow-y-auto px-7 py-7">
      <div className="mx-auto max-w-6xl">
        <header className="flex items-start justify-between">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Segurança</p>
            <h1 className="mt-2 text-2xl font-semibold">Harness</h1>
            <p className="mt-1 text-sm text-zinc-500">
              Toda ação do agente passa por aqui antes de rodar. Esta tela mostra o que
              ele pode fazer sem perguntar; o diagnóstico de um turno fica no botão de
              depuração, ao lado da conversa.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void carregar()}
            className="rounded-lg border border-stone-300 bg-white p-2"
            title="Atualizar"
          >
            <RefreshCw className={`h-4 w-4 ${carregando ? 'animate-spin' : ''}`} />
          </button>
        </header>

        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          <article className="rounded-xl border border-stone-200 bg-white/80 p-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-zinc-700">
              <Terminal className="h-3.5 w-3.5 text-gold-hover" />Shell
              <label className="ml-auto inline-flex items-center gap-2 text-[11px] font-normal text-zinc-500">
                {ambiente.shell_ligado ? 'Ligado' : 'Desligado'}
                <input
                  type="checkbox"
                  checked={Boolean(ambiente.shell_ligado)}
                  onChange={event => void alternarShell(event.target.checked)}
                  className="h-4 w-4 accent-[#c99f00]"
                />
              </label>
            </div>
            <p className="mt-2 text-[11px] leading-5 text-zinc-500">
              {ambiente.shell_ligado
                ? 'Comandos rodam um a um, dentro da política: leitura direto, escrita pedindo autorização.'
                : 'Nenhum comando roda, nem os que você já autorizou.'}
            </p>
          </article>

          <article className="rounded-xl border border-stone-200 bg-white/80 p-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-zinc-700">
              <ShieldCheck className="h-3.5 w-3.5 text-gold-hover" />Onde ele roda
            </div>
            <p className="mt-2 truncate text-sm text-zinc-900" title={ambiente.diretorio || ''}>
              {ambiente.diretorio || '—'}
            </p>
            <p className="mt-1 text-[11px] text-zinc-500">
              {[ambiente.sistema, ambiente.shell].filter(Boolean).join(' · ') || 'ambiente não informado'}
            </p>
          </article>
        </div>

        <section className="mt-8 rounded-xl border border-stone-200 bg-white/80 p-5">
          <h2 className="text-sm font-semibold text-zinc-900">Onde ele pode mexer</h2>
          <p className="mt-1 text-[12.5px] leading-5 text-zinc-500">
            Fora destas pastas ele não lê nem escreve, mesmo com o comando autorizado.
          </p>

          {pastas.trabalhando_na_instalacao && !pastas.universal && (
            <p className="mt-3 rounded-lg border border-stone-200 bg-[#efece2] px-3 py-2 text-[12px] leading-5 text-zinc-600">
              Você escolheu trabalhar dentro da instalação do Sentury. O código do motor
              continua protegido contra escrita; o resto desta pasta, não.
            </p>
          )}

          <label className="mt-4 block text-[10px] font-bold uppercase tracking-[0.12em] text-zinc-400">
            Pasta de trabalho
          </label>
          <form
            className="mt-1.5 flex gap-2"
            onSubmit={event => { event.preventDefault(); void trocarTrabalho(); }}
          >
            <input
              value={novoTrabalho}
              onChange={event => setNovoTrabalho(event.target.value)}
              placeholder={pastas.projeto || 'caminho completo'}
              className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 font-mono text-[11.5px] outline-none focus:border-gold"
            />
            <button
              type="button"
              onClick={() => setEscolhendo('trabalho')}
              className="shrink-0 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-semibold text-zinc-700 hover:border-gold"
            >
              Escolher…
            </button>
            <button
              type="submit"
              disabled={!novoTrabalho.trim()}
              className="shrink-0 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-semibold text-zinc-700 hover:border-gold disabled:opacity-40"
            >
              Trocar
            </button>
          </form>
          <p className="mt-1.5 font-mono text-[11px] text-zinc-500">{pastas.projeto || '—'}</p>

          <label className="mt-5 block text-[10px] font-bold uppercase tracking-[0.12em] text-zinc-400">
            Também liberadas
          </label>
          <ul className="mt-1.5 space-y-1.5">
            {(pastas.extras || []).length === 0 && (
              <li className="text-[12px] text-zinc-400">Nenhuma. Só a pasta de trabalho.</li>
            )}
            {(pastas.extras || []).map(caminho => (
              <li key={caminho} className="group flex items-center gap-2 rounded-lg border border-stone-200 px-3 py-2 font-mono text-[11.5px] text-zinc-700">
                <span className="truncate">{caminho}</span>
                <button
                  type="button"
                  onClick={() => void tirar(caminho)}
                  aria-label={`Tirar ${caminho}`}
                  className="ml-auto shrink-0 rounded p-1 text-zinc-400 opacity-0 transition-opacity hover:text-red-600 group-hover:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>

          <form
            className="mt-2 flex gap-2"
            onSubmit={event => { event.preventDefault(); void liberar(); }}
          >
            <input
              value={novaPasta}
              onChange={event => setNovaPasta(event.target.value)}
              placeholder="outra pasta que ele pode usar"
              className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 font-mono text-[11.5px] outline-none focus:border-gold"
            />
            <button
              type="button"
              onClick={() => setEscolhendo('extra')}
              className="shrink-0 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-semibold text-zinc-700 hover:border-gold"
            >
              Escolher…
            </button>
            <button
              type="submit"
              disabled={!novaPasta.trim()}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs font-semibold text-zinc-700 hover:border-gold disabled:opacity-40"
            >
              <FolderPlus className="h-3.5 w-3.5" />Liberar
            </button>
          </form>
          {erroPasta && <p className="mt-2 text-[12px] text-red-700">{erroPasta}</p>}

          <label className="mt-5 flex items-start justify-between gap-4 border-t border-stone-200 pt-4">
            <span>
              <span className="block text-[12.5px] font-semibold text-zinc-800">
                Máquina inteira
              </span>
              <span className="mt-0.5 block text-[12px] leading-5 text-zinc-500">
                Ele passa a alcançar qualquer pasta do computador. Arquivo de credencial
                continua recusado, e escrita continua pedindo autorização.
              </span>
            </span>
            <input
              type="checkbox"
              checked={Boolean(pastas.universal)}
              onChange={event => void alternarUniversal(event.target.checked)}
              className="mt-1 h-4 w-4 shrink-0 accent-[#c99f00]"
            />
          </label>
        </section>

        <div className="mt-6">
          <PermissionsSection />
        </div>

        {escolhendo && (
          <FolderPicker
            titulo={escolhendo === 'trabalho' ? 'Pasta de trabalho' : 'Liberar uma pasta'}
            inicial={pastas.projeto}
            onFechar={() => setEscolhendo(null)}
            onEscolher={async caminho => {
              const alvo = escolhendo;
              setEscolhendo(null);
              setErroPasta('');
              try {
                if (alvo === 'trabalho') {
                  await apiClient.put('/sentury/pastas/trabalho', { caminho }, { headers: authHeaders() });
                } else {
                  await apiClient.post('/sentury/pastas', { caminho }, { headers: authHeaders() });
                }
                await carregar();
              } catch (motivo) {
                setErroPasta(motivo instanceof Error ? motivo.message : String(motivo));
              }
            }}
          />
        )}
      </div>
    </section>
  );
};
