import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, ExternalLink, KeyRound, LoaderCircle, TriangleAlert } from 'lucide-react';
import { z } from 'zod';
import { authHeaders, getRuntimeConfig } from '../runtime/config';
import { apiClient } from '../transport/http-client';
import { ProviderLogo } from '../components/ProviderLogo';

const ProvedorSchema = z.object({
  key: z.string(),
  label: z.string(),
  configured: z.boolean(),
  enabled: z.boolean().default(true),
  estado: z.string().default('off'),
  cost_class: z.string().default(''),
  priority: z.number().default(99),
  categoria: z.string().default('provedor'),
  key_env: z.string().default(''),
  key_url: z.string().default(''),
}).passthrough();
type Provedor = z.infer<typeof ProvedorSchema>;

const RespostaSchema = z.object({ providers: z.array(ProvedorSchema).default([]) }).passthrough();
const TesteSchema = z.object({ ok: z.boolean(), ms: z.number().optional(), tipo: z.string().optional() }).passthrough();

type Etapa = 'escolher' | 'testando' | 'pronto' | 'falhou';

const MOTIVO: Record<string, string> = {
  auth: 'A chave foi recusada. Confira se ela foi copiada inteira e se é deste provedor.',
  rate_limit: 'A chave funciona, mas o limite gratuito acabou por agora. Tente de novo em alguns minutos.',
  credit: 'A chave funciona, mas a conta está sem crédito.',
  network: 'Não consegui falar com o provedor. Confira a conexão com a internet.',
  not_found: 'O provedor não encontrou o modelo configurado.',
};

/** Sem nenhum modelo real de pé, o Sentury só responde no modo de demonstração,
 *  e quem acabou de instalar conclui que ele não funciona. Este cartão guia o
 *  primeiro cadastro pelo mesmo cofre e o mesmo teste do painel de provedores. */
export const PrimeiroAcesso: React.FC<{ aoConfigurarOutros: () => void }> = ({ aoConfigurarOutros }) => {
  const [provedores, setProvedores] = useState<Provedor[] | null>(null);
  const [escolhido, setEscolhido] = useState('');
  const [chave, setChave] = useState('');
  const [etapa, setEtapa] = useState<Etapa>('escolher');
  const [mensagem, setMensagem] = useState('');

  const carregar = useCallback(async () => {
    const config = getRuntimeConfig();
    apiClient.setBaseUrl(config.apiUrl);
    try {
      const resposta = RespostaSchema.parse(await apiClient.get('/sentury/providers', { headers: authHeaders() }));
      setProvedores(resposta.providers);
    } catch {
      setProvedores([]);
    }
  }, []);

  useEffect(() => { void carregar(); }, [carregar]);

  if (!provedores) return null;
  const reais = provedores.filter(p => p.key !== 'fallback' && p.categoria !== 'gateway' && p.enabled);
  const comChave = reais.filter(p => p.configured);
  const semModelo = !comChave.length || comChave.every(p => p.estado === 'error');
  if (!semModelo && etapa !== 'pronto') return null;

  // As opções vêm do YAML do RobinBandit: grátis e com link de onde criar a chave.
  const opcoes = reais
    .filter(p => p.key_env && p.key_url && p.cost_class.startsWith('free'))
    .sort((a, b) => a.priority - b.priority);
  const atual = opcoes.find(p => p.key === escolhido) || opcoes[0];

  const conectar = async () => {
    if (!atual || !chave.trim()) return;
    setEtapa('testando');
    setMensagem('');
    try {
      await apiClient.post('/sentury/providers/keys', { key_env: atual.key_env, valor: chave.trim(), adicionar: false }, { headers: authHeaders() });
      const teste = TesteSchema.parse(await apiClient.post(`/sentury/providers/${encodeURIComponent(atual.key)}/testar`, {}, { headers: authHeaders() }));
      setChave('');
      if (teste.ok) {
        setEtapa('pronto');
        setMensagem(`${atual.label} respondeu${teste.ms ? ` em ${(teste.ms / 1000).toFixed(1)} s` : ''}.`);
      } else {
        setEtapa('falhou');
        setMensagem(MOTIVO[teste.tipo || ''] || `O provedor recusou o teste (${teste.tipo || 'erro desconhecido'}).`);
      }
    } catch (reason) {
      setEtapa('falhou');
      setMensagem(reason instanceof Error ? reason.message : String(reason));
    }
  };

  if (etapa === 'pronto') {
    return (
      <div className="mx-auto mt-8 flex max-w-xl items-start gap-3 rounded-2xl border border-emerald-200 bg-emerald-50/70 px-5 py-4 text-left">
        <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
        <div>
          <p className="text-sm font-semibold text-zinc-900">Pronto. {mensagem}</p>
          <p className="mt-1 text-xs text-zinc-600">Escreva o que precisa abaixo. A chave fica no cofre desta máquina.</p>
        </div>
      </div>
    );
  }

  return (
    <section className="mx-auto mt-8 max-w-xl rounded-2xl border border-stone-200 bg-white/90 p-5 text-left shadow-sm">
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-gold-ink" />
        <h2 className="text-sm font-semibold text-zinc-900">Conecte um modelo para começar</h2>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-zinc-600">
        {comChave.length
          ? 'As chaves cadastradas não estão respondendo, e sem um modelo de pé o Sentury só responde no modo de demonstração.'
          : 'Sem uma chave, o Sentury só responde no modo de demonstração.'}
        {' '}Estas opções têm nível gratuito. A chave fica guardada no cofre desta máquina e não sai daqui.
      </p>

      {atual ? (
        <>
          <div className="mt-4 flex flex-wrap gap-2" role="radiogroup" aria-label="Provedor">
            {opcoes.map(p => (
              <button
                key={p.key}
                type="button"
                role="radio"
                aria-checked={p.key === atual.key}
                onClick={() => { setEscolhido(p.key); setEtapa('escolher'); setMensagem(''); }}
                className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs ${p.key === atual.key ? 'border-gold bg-gold-soft/60 font-semibold text-zinc-900' : 'border-stone-200 text-zinc-600 hover:bg-stone-50'}`}
              >
                <ProviderLogo providerKey={p.key} label={p.label} className="h-4 w-4" />{p.label}
              </button>
            ))}
          </div>

          <ol className="mt-4 space-y-3 text-xs text-zinc-700">
            <li>
              <span className="font-semibold">1.</span> Crie uma chave em{' '}
              <a href={atual.key_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-semibold text-gold-ink underline-offset-2 hover:underline">
                {new URL(atual.key_url).host}<ExternalLink className="h-3 w-3" />
              </a>
            </li>
            <li>
              <span className="font-semibold">2.</span> Cole aqui e teste:
              <form onSubmit={e => { e.preventDefault(); void conectar(); }} className="mt-2 flex gap-2">
                <input
                  type="password"
                  value={chave}
                  onChange={e => setChave(e.target.value)}
                  placeholder={`Chave do ${atual.label}`}
                  autoComplete="off"
                  aria-label={`Chave do ${atual.label}`}
                  className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-xs outline-none focus:border-gold"
                />
                <button
                  type="submit"
                  disabled={!chave.trim() || etapa === 'testando'}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-35"
                >
                  {etapa === 'testando' ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : null}
                  {etapa === 'testando' ? 'Testando' : 'Conectar e testar'}
                </button>
              </form>
            </li>
          </ol>

          {etapa === 'falhou' && mensagem ? (
            <p className="mt-3 flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />{mensagem}
            </p>
          ) : null}
        </>
      ) : (
        <p className="mt-3 text-xs text-zinc-600">Nenhum provedor gratuito está declarado na configuração.</p>
      )}

      <button type="button" onClick={aoConfigurarOutros} className="mt-4 text-[11px] font-medium text-zinc-500 underline-offset-2 hover:text-zinc-800 hover:underline">
        Prefiro configurar outro provedor ou uma assinatura
      </button>
    </section>
  );
};
