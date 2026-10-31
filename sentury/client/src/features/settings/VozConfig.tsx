import React, { useCallback, useEffect, useState } from 'react';
import { z } from 'zod';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const EstadoSchema = z.object({
  escolha: z.object({ provedor: z.string(), modelo: z.string(), voz: z.string() }),
  provedores: z.array(z.object({
    nome: z.string(), rotulo: z.string(), descricao: z.string(), tem_chave: z.boolean(),
    modelos: z.array(z.string()), vozes: z.array(z.string()),
  })),
});
type Estado = z.infer<typeof EstadoSchema>;
type Escolha = Estado['escolha'];

const opcoes = () => ({ headers: authHeaders() });
const CAMPO = 'mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-gold';

/** Provedor, modelo e voz da ligação; vale a partir da próxima chamada. */
export const VozConfig: React.FC<{ onSalvo?: () => void }> = ({ onSalvo }) => {
  const [estado, setEstado] = useState<Estado | null>(null);
  const [rascunho, setRascunho] = useState<Escolha | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [aviso, setAviso] = useState('');

  const carregar = useCallback(async () => {
    try {
      const lido = EstadoSchema.parse(await apiClient.get('/sentury/ajustes/voz', opcoes()));
      setEstado(lido);
      setRascunho(lido.escolha);
    } catch { setAviso('Não consegui ler a configuração de voz.'); }
  }, []);
  useEffect(() => { void carregar(); }, [carregar]);

  if (!estado || !rascunho) return aviso ? <p className="mt-3 text-xs text-red-700">{aviso}</p> : null;
  const provedor = estado.provedores.find(p => p.nome === rascunho.provedor) || estado.provedores[0];
  const mudou = JSON.stringify(rascunho) !== JSON.stringify(estado.escolha);

  const salvar = async () => {
    setSalvando(true);
    setAviso('');
    try {
      const lido = EstadoSchema.parse(await apiClient.put('/sentury/ajustes/voz', rascunho, opcoes()));
      setEstado(lido);
      setRascunho(lido.escolha);
      setAviso('Salvo. Vale a partir da próxima ligação.');
      onSalvo?.();
    } catch (e) { setAviso(e instanceof Error ? e.message : 'Não consegui salvar.'); } finally { setSalvando(false); }
  };

  return (
    <div className="mt-4 grid gap-3 rounded-lg border border-stone-200 p-4 sm:grid-cols-3">
      <label className="block">
        <span className="text-xs font-semibold text-zinc-700">Provedor</span>
        <select value={rascunho.provedor} className={CAMPO}
          onChange={event => {
            const alvo = estado.provedores.find(p => p.nome === event.target.value);
            setRascunho({ provedor: event.target.value, modelo: alvo?.modelos[0] || '', voz: alvo?.vozes[0] || '' });
          }}>
          {estado.provedores.map(p => <option key={p.nome} value={p.nome}>{p.rotulo}{p.tem_chave ? '' : ' (sem chave)'}</option>)}
        </select>
      </label>
      <label className="block">
        <span className="text-xs font-semibold text-zinc-700">Modelo</span>
        <select value={rascunho.modelo} onChange={event => setRascunho({ ...rascunho, modelo: event.target.value })} className={CAMPO}>
          {[...new Set([rascunho.modelo, ...provedor.modelos].filter(Boolean))].map(m => <option key={m} value={m}>{m}</option>)}
        </select>
      </label>
      <label className="block">
        <span className="text-xs font-semibold text-zinc-700">Voz</span>
        <select value={rascunho.voz} onChange={event => setRascunho({ ...rascunho, voz: event.target.value })} className={CAMPO}>
          {provedor.vozes.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
      </label>
      <div className="flex items-center gap-3 sm:col-span-3">
        <button type="button" onClick={() => void salvar()} disabled={!mudou || salvando}
          className="rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">
          {salvando ? 'Salvando…' : 'Salvar voz'}
        </button>
        <span className="text-[11px] text-zinc-500">{aviso || provedor.descricao}</span>
      </div>
    </div>
  );
};
