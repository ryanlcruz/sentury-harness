import React, { useCallback, useEffect, useState } from 'react';
import { z } from 'zod';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const EstadoSchema = z.object({
  escolha: z.object({ perfil: z.string(), nome: z.string() }),
  origem: z.string(),
  perfis: z.array(z.object({ nome: z.string(), rotulo: z.string(), descricao: z.string() })),
  chrome_encontrado: z.boolean(),
  atalho: z.string().optional(),
});
type Estado = z.infer<typeof EstadoSchema>;

const opcoes = () => ({ headers: authHeaders() });

/** Em qual Chrome o agente navega quando usa a tela: o da pessoa ou um separado, com nome. */
export const ChromeDoAgente: React.FC = () => {
  const [estado, setEstado] = useState<Estado | null>(null);
  const [perfil, setPerfil] = useState('pessoa');
  const [nome, setNome] = useState('');
  const [salvando, setSalvando] = useState(false);
  const [aviso, setAviso] = useState('');

  const carregar = useCallback(async () => {
    try {
      const lido = EstadoSchema.parse(await apiClient.get('/sentury/ajustes/navegador', opcoes()));
      setEstado(lido);
      setPerfil(lido.escolha.perfil);
      setNome(lido.escolha.nome);
    } catch { setAviso('Não consegui ler a escolha do navegador.'); }
  }, []);
  useEffect(() => { void carregar(); }, [carregar]);

  if (!estado) return aviso ? <p className="mt-4 text-xs text-red-700">{aviso}</p> : null;
  const mudou = estado.origem !== 'tela' || perfil !== estado.escolha.perfil || (perfil === 'agente' && nome.trim() !== estado.escolha.nome);

  const salvar = async () => {
    setSalvando(true);
    setAviso('');
    try {
      const lido = EstadoSchema.parse(await apiClient.put('/sentury/ajustes/navegador', { perfil, nome: nome.trim() }, opcoes()));
      setEstado(lido);
      setAviso(lido.atalho ? `Salvo. O atalho "Chrome do ${lido.escolha.nome}" está no menu Iniciar.` : 'Salvo.');
    } catch (e) { setAviso(e instanceof Error ? e.message : 'Não consegui salvar.'); } finally { setSalvando(false); }
  };

  return (
    <div className="mt-6 max-w-2xl rounded-2xl border border-stone-200 bg-white/80 p-5 shadow-sm">
      <h3 className="text-sm font-semibold">Em qual Chrome o agente navega pela tela</h3>
      <p className="mt-1 text-xs leading-5 text-zinc-500">Quando o agente usa a tela (mouse e teclado), ele abre este Chrome. As abas da extensão acima existem nos dois casos.</p>
      {estado.origem === 'env' ? <p className="mt-2 text-xs text-zinc-600">Vem do <code>.env</code> agora. Salvar aqui passa a valer no lugar dele.</p> : null}
      <div role="radiogroup" aria-label="Chrome do agente" className="mt-4 grid gap-2 sm:grid-cols-2">
        {estado.perfis.map(item => (
          <button key={item.nome} type="button" role="radio" aria-checked={perfil === item.nome} onClick={() => setPerfil(item.nome)}
            className={`rounded-xl border p-3.5 text-left transition-colors ${perfil === item.nome ? 'border-gold bg-gold-soft' : 'border-stone-200 bg-white hover:border-stone-300'}`}>
            <strong className="block text-sm">{item.rotulo}</strong>
            <span className="mt-1 block text-[11px] leading-4 text-zinc-500">{item.descricao}</span>
          </button>
        ))}
      </div>
      {perfil === 'agente' ? (
        <label className="mt-4 block">
          <span className="text-xs font-semibold text-zinc-700">Nome do Chrome do agente</span>
          <input value={nome} onChange={event => setNome(event.target.value)} maxLength={40}
            className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-gold" />
          <span className="mt-1 block text-[11px] text-zinc-500">Aparece como "Chrome do {nome || 'Agente'}" no menu Iniciar e no título da janela.</span>
        </label>
      ) : null}
      {perfil === 'agente' && !estado.chrome_encontrado ? <p className="mt-3 text-xs text-amber-800">Não achei o Google Chrome instalado nesta máquina.</p> : null}
      <div className="mt-4 flex items-center gap-3">
        <button type="button" onClick={() => void salvar()} disabled={!mudou || salvando}
          className="rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">
          {salvando ? 'Salvando…' : 'Salvar'}
        </button>
        {aviso ? <span className="text-[11px] text-zinc-600">{aviso}</span> : null}
      </div>
    </div>
  );
};
