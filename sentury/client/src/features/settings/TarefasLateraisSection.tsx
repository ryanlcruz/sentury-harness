import React, { useEffect, useState } from 'react';
import { Check, RefreshCw } from 'lucide-react';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

type Escolha = 'atual' | 'auxiliar';
type Estado = { modelo: Escolha; rota_declarada: boolean };

const OPCOES: { id: Escolha; titulo: string; texto: string }[] = [
  {
    id: 'atual',
    titulo: 'Modelo da conversa',
    texto: 'O mesmo modelo que responde resume o histórico. Entende a conversa como ela foi e não precisa de nada configurado.',
  },
  {
    id: 'auxiliar',
    titulo: 'Modelo auxiliar',
    texto: 'Um modelo à parte, mais barato, resume. Não usa a conta do Reforçado nem a do Dedicado.',
  },
];

// Quem compacta o histórico, dá título à conversa e resume página longa.
export const TarefasLateraisSection: React.FC = () => {
  const [estado, setEstado] = useState<Estado | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');

  useEffect(() => {
    void apiClient.get<Estado>('/sentury/tarefas-laterais', { headers: authHeaders() })
      .then(setEstado)
      .catch(() => setErro('Não consegui ler a escolha. Confira se a API está ligada.'));
  }, []);

  const escolher = async (modelo: Escolha) => {
    if (!estado || modelo === estado.modelo) return;
    setErro('');
    setSalvando(true);
    try {
      setEstado(await apiClient.put<Estado>('/sentury/tarefas-laterais', { modelo }, { headers: authHeaders() }));
    } catch {
      setErro('Não consegui salvar a escolha.');
    } finally {
      setSalvando(false);
    }
  };

  return (
    <div className="mt-6 rounded-2xl border border-stone-200 bg-white/80 p-5" aria-label="Quem resume a conversa">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">Quem resume a conversa</h3>
          <p className="mt-1 text-[11px] text-zinc-500">Compactar o histórico longo, dar título à conversa e resumir página longa da pesquisa.</p>
        </div>
        {salvando ? <RefreshCw className="h-3.5 w-3.5 animate-spin text-zinc-400" /> : null}
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2" role="radiogroup">
        {OPCOES.map(opcao => {
          const ativa = estado?.modelo === opcao.id;
          return (
            <button
              key={opcao.id}
              type="button"
              role="radio"
              aria-checked={ativa}
              disabled={!estado || salvando}
              onClick={() => void escolher(opcao.id)}
              className={`rounded-xl border p-4 text-left transition-colors disabled:opacity-60 ${ativa ? 'border-gold bg-gold-soft/30' : 'border-stone-200 hover:border-gold'}`}
            >
              <span className="flex items-center gap-2 text-sm font-semibold">
                {ativa ? <Check className="h-3.5 w-3.5 text-gold-hover" /> : null}
                {opcao.titulo}
              </span>
              <span className="mt-1 block text-xs text-zinc-500">{opcao.texto}</span>
            </button>
          );
        })}
      </div>
      {estado?.modelo === 'auxiliar' ? (
        <p className="mt-3 text-[11px] text-zinc-500">
          {estado.rota_declarada
            ? 'Usa a rota auxiliar declarada no RobinBandit.'
            : 'Sem rota auxiliar declarada no RobinBandit, usa o Router. Para fixar o modelo, declare a rota auxiliar no YAML.'}
        </p>
      ) : null}
      {erro ? <p role="alert" className="mt-3 text-xs text-red-700">{erro}</p> : null}
    </div>
  );
};
