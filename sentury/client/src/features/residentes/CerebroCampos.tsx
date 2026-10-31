import React, { useEffect, useState } from 'react';
import { cerebros, type Provedor } from './api';

export interface Cerebro {
  provedor: string;
  modelo: string;
  se_cair: 'parar' | 'robinbandit';
  esforco?: 'low' | 'medium' | 'high';
}

const ROUTER = '';

/** O esforço salvo, se for um dos que a tela oferece. */
export function esforcoDe(valor: unknown): Cerebro['esforco'] {
  return valor === 'low' || valor === 'medium' || valor === 'high' ? valor : undefined;
}
// Vazio é o padrão do provedor; leve deixa o residente de tarefa simples mais rápido e barato.
const ESFORCOS: [Cerebro['esforco'] | '', string][] = [['', 'Padrão'], ['low', 'Leve'], ['medium', 'Médio'], ['high', 'Alto']];

/** Provedor e modelo fixos do residente, e o que fazer se o modelo cair.
 * Provedor vazio é o Router do RobinBandit escolhendo a cada turno. */
export const CerebroCampos: React.FC<{ valor: Cerebro | null; onMudar: (valor: Cerebro | null) => void }> = ({ valor, onMudar }) => {
  const [provedores, setProvedores] = useState<Provedor[]>([]);
  useEffect(() => { void cerebros.provedores().then(setProvedores).catch(() => setProvedores([])); }, []);

  const atual = provedores.find(p => p.key === valor?.provedor);
  const modelos = atual?.models.length ? atual.models : valor?.modelo ? [valor.modelo] : [];
  const campo = 'h-11 w-full rounded-lg border border-[#d8cfbd] bg-white px-2.5 text-sm text-zinc-900 outline-none focus:border-gold-hover';
  const pilula = (ativa: boolean) => `min-h-11 rounded-full px-3.5 text-[13px] transition ${ativa
    ? 'border-2 border-gold-hover bg-gold-soft' : 'border border-[#ded7c6] bg-white hover:border-zinc-400'}`;

  return (
    <div className="flex flex-col gap-2.5">
      <div className="grid gap-2.5 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-zinc-600">
          Provedor
          <select className={campo} value={valor?.provedor || ROUTER}
            onChange={event => {
              const chave = event.target.value;
              if (!chave) { onMudar(null); return; }
              const escolhido = provedores.find(p => p.key === chave);
              onMudar({ provedor: chave, modelo: escolhido?.models[0] || '', se_cair: valor?.se_cair || 'parar' });
            }}>
            <option value={ROUTER}>Router do RobinBandit</option>
            {provedores.map(p => (
              <option key={p.key} value={p.key}>{p.label || p.name || p.key}{p.configured === false ? ' (sem chave)' : ''}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-zinc-600">
          Modelo
          <select className={`${campo} font-mono text-[13px]`} disabled={!valor} value={valor?.modelo || ''}
            onChange={event => valor && onMudar({ ...valor, modelo: event.target.value })}>
            {!valor ? <option value="">escolhido a cada turno</option> : null}
            {modelos.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
      </div>
      {valor ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-xs text-zinc-600">Se esse modelo cair:</span>
          <button type="button" aria-pressed={valor.se_cair === 'parar'} className={pilula(valor.se_cair === 'parar')}
            onClick={() => onMudar({ ...valor, se_cair: 'parar' })}>Parar e me avisar</button>
          <button type="button" aria-pressed={valor.se_cair === 'robinbandit'} className={pilula(valor.se_cair === 'robinbandit')}
            onClick={() => onMudar({ ...valor, se_cair: 'robinbandit' })}>Seguir com o RobinBandit</button>
        </div>
      ) : null}
      {valor ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-xs text-zinc-600">Esforço:</span>
          {ESFORCOS.map(([nivel, rotulo]) => (
            <button key={rotulo} type="button" aria-pressed={(valor.esforco || '') === nivel} className={pilula((valor.esforco || '') === nivel)}
              onClick={() => onMudar({ ...valor, esforco: nivel || undefined })}>{rotulo}</button>
          ))}
        </div>
      ) : (
        <p className="text-xs text-zinc-500">Sem modelo fixo, o RobinBandit escolhe a melhor cadeia disponível em cada turno.</p>
      )}
    </div>
  );
};
