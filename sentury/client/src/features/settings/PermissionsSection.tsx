import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, Plus, ShieldAlert, ShieldCheck, Trash2, Zap } from 'lucide-react';
import { apiClient } from '../../transport/http-client';

interface EstadoPermissoes {
  permitir_tudo: boolean;
  sempre: string[];
  negados: string[];
  sessao: string[];
  registro: string;
}

const VAZIO: EstadoPermissoes = { permitir_tudo: false, sempre: [], negados: [], sessao: [], registro: '' };

export const PermissionsSection: React.FC = () => {
  const [estado, setEstado] = useState<EstadoPermissoes>(VAZIO);
  const [carregando, setCarregando] = useState(true);
  const [novo, setNovo] = useState('');
  const [erro, setErro] = useState('');

  const carregar = useCallback(async () => {
    try {
      const dados = await apiClient.get<EstadoPermissoes>('/sentury/permissoes');
      setEstado({ ...VAZIO, ...dados });
      setErro('');
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui ler as permissões');
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => { void carregar(); }, [carregar]);

  const alternarTudo = async () => {
    const proximo = !estado.permitir_tudo;
    setEstado(atual => ({ ...atual, permitir_tudo: proximo }));
    try {
      setEstado({ ...VAZIO, ...await apiClient.post<EstadoPermissoes>('/sentury/permissoes/permitir-tudo', { ligado: proximo }) });
    } catch { void carregar(); }
  };

  const adicionar = async () => {
    const comando = novo.trim();
    if (!comando) return;
    setErro('');
    try {
      // Mesmo caminho de quando você responde "sempre" na conversa: o backend
      // extrai o verbo, então digitar a linha inteira funciona igual.
      await apiClient.post('/sentury/permissoes', { comando, resposta: 'sempre', session_id: '' });
      setNovo('');
      void carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : 'não consegui autorizar isso');
    }
  };

  const esquecer = async (chave: string) => {
    try {
      setEstado({ ...VAZIO, ...await apiClient.delete<EstadoPermissoes>(`/sentury/permissoes/${encodeURIComponent(chave)}`) });
    } catch { void carregar(); }
  };

  return (
    <section>
      <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-gold-ink">Permissões</p>
      <h2 className="mt-1 text-3xl font-semibold tracking-tight">O que ele pode fazer sem perguntar</h2>
      <p className="mt-2 text-sm text-zinc-500">
        Leitura sempre pôde. Comando que <strong>altera</strong> alguma coisa pergunta na hora — o que está aqui é o que
        você já autorizou para sempre. A permissão cobre o verbo (<code className="font-mono text-xs">git commit</code>),
        não a linha exata.
      </p>

      {erro && <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p>}

      <button
        type="button"
        onClick={() => void alternarTudo()}
        className={`mt-6 flex w-full cursor-pointer items-center gap-3 rounded-xl border p-4 text-left transition ${
          estado.permitir_tudo
            ? 'border-amber-300 bg-amber-50/70 hover:border-amber-400'
            : 'border-stone-200 bg-white/80 hover:border-gold'
        }`}
      >
        {estado.permitir_tudo
          ? <Zap className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" strokeWidth={1.8} />
          : <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-gold-hover" strokeWidth={1.8} />}
        <span className="flex-1">
          <strong className="block text-sm">{estado.permitir_tudo ? 'Permitindo tudo' : 'Permitir tudo sem perguntar'}</strong>
          <span className="mt-1 block text-xs text-zinc-500">
            {estado.permitir_tudo
              ? 'Nenhum comando pede autorização agora. Clique para voltar a perguntar.'
              : 'Para quando você não quer ser interrompido.'}
          </span>
        </span>
        <span className={`h-5 w-9 shrink-0 rounded-full p-0.5 transition ${estado.permitir_tudo ? 'bg-amber-500' : 'bg-stone-300'}`}>
          <span className={`block h-4 w-4 rounded-full bg-white transition ${estado.permitir_tudo ? 'translate-x-4' : ''}`} />
        </span>
      </button>

      <div className="mt-4 rounded-xl border border-stone-200 bg-white/80 p-4">
        <p className="text-[10px] font-bold uppercase tracking-wide text-zinc-400">Autorizados</p>

        {carregando ? (
          <p className="mt-3 flex items-center gap-2 text-sm text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Lendo o registro…
          </p>
        ) : estado.sempre.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-400">
            Nada ainda. Autorize pela conversa quando ele pedir, ou adicione abaixo.
          </p>
        ) : (
          <ul className="mt-3 space-y-1.5">
            {estado.sempre.map(chave => (
              <li key={chave} className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded-md bg-[#fdf8ec] px-2 py-1 font-mono text-xs text-zinc-800">{chave}</code>
                <button
                  type="button"
                  onClick={() => void esquecer(chave)}
                  className="cursor-pointer rounded-md p-1 text-zinc-400 transition hover:bg-stone-100 hover:text-red-600"
                  aria-label={`Remover ${chave}`}
                  title="Remover — volta a perguntar"
                >
                  <Trash2 className="h-3.5 w-3.5" strokeWidth={1.8} />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 flex gap-2 border-t border-stone-200 pt-3">
          <input
            value={novo}
            onChange={event => setNovo(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') void adicionar(); }}
            placeholder="git commit, npm install, mkdir…"
            className="min-w-0 flex-1 rounded-lg border border-stone-200 bg-white px-3 py-2 font-mono text-xs text-zinc-800 outline-none transition placeholder:font-sans placeholder:text-zinc-400 focus:border-gold"
          />
          <button
            type="button"
            onClick={() => void adicionar()}
            disabled={!novo.trim()}
            className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-3 py-2 text-xs font-medium text-zinc-700 transition hover:border-gold hover:bg-[#fdf8ec] disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" strokeWidth={2} /> Autorizar
          </button>
        </div>
      </div>

      <p className="mt-4 flex items-start gap-2 text-xs text-zinc-500">
        <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-400" strokeWidth={1.8} />
        <span>
          O que você libera só para uma conversa morre com ela, e recusar um comando na hora não deixa marca — por isso
          nenhum dos dois aparece aqui.
          {estado.registro && <> Esta lista fica em <code className="font-mono">{estado.registro}</code>, por máquina.</>}
        </span>
      </p>
    </section>
  );
};
