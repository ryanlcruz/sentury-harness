import React, { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, Plus, Search, X } from 'lucide-react';
import { apiClient } from '../../transport/http-client';
import { authHeaders } from '../../runtime/config';
import { ProviderLogo } from '../../components/ProviderLogo';

/**
 * Quem responde no Reforçado e no Dedicado — conta e modelos.
 *
 * A escolha grava conta e modelo na seleção usada pela execução.
 * No Dedicado, vários alvos são tentados na ordem definida pelo usuário.
 */

interface Conta {
  id: string;
  provider: string;
  label: string;
  models: string[];
  paga: boolean;
  configurada: boolean;
  auth_type: string;
}

const MAX_VIVOS_COMO_BOTAO = 12;
/** Assinatura e chave de API se comportam diferente no custo e no limite: o
 * selo diz qual é, pelo `cost_class` que o provedor declara. */
const SeloDeAcesso: React.FC<{ conta: Conta; custo: string }> = ({ conta, custo }) => {
  if (custo === 'subscription') {
    return <span title="Usa a sua assinatura pelo login; não cobra por chamada, mas tem limite de uso"
      className="rounded bg-stone-100 px-1.5 py-px text-[9px] font-semibold text-zinc-600">assinatura</span>;
  }
  if (conta.paga) {
    return <span title="Chave de API paga: cada chamada é cobrada"
      className="rounded bg-gold-soft px-1.5 py-px text-[9px] font-semibold text-gold-ink">API paga</span>;
  }
  return null;
};

interface Alvo {
  conta: string;
  modelos: string[];
}

interface Props {
  modo: 'ultra' | 'ultra_max';
  rotulo: string;
  /** Uma linha: o que este modo faz de diferente do Router. */
  descricao?: string;
  contas: Conta[];
  /** Modelos por provedor, para a conta que não declara os seus. */
  modelosDoProvedor: Record<string, string[]>;
  /** `cost_class` de cada provedor: `subscription` é assinatura. */
  custoDoProvedor?: Record<string, string>;
  onSalvo?: () => void;
}

export const SelecaoDeModo: React.FC<Props> = ({ modo, rotulo, descricao, contas, modelosDoProvedor, custoDoProvedor = {}, onSalvo }) => {
  const [alvos, setAlvos] = useState<Alvo[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');
  const [adicionando, setAdicionando] = useState(false);
  // Qual alvo esta com a busca do catalogo aberta, e o que ela trouxe.
  const [buscandoEm, setBuscandoEm] = useState<number | null>(null);
  const [termo, setTermo] = useState('');
  const [catalogo, setCatalogo] = useState<string[]>([]);
  const [lendoCatalogo, setLendoCatalogo] = useState(false);
  // "Catalogo ao vivo indisponivel": sem isto a busca so dizia que nao
  // achou, e parecia que o provedor nao tinha outros modelos.
  const [avisoDoCatalogo, setAvisoDoCatalogo] = useState('');

  const ler = useCallback(async () => {
    setCarregando(true);
    try {
      const dados = await apiClient.get<{ modes?: Record<string, Alvo[]> }>(
        '/sentury/providers/modes', { headers: authHeaders() });
      setAlvos(dados.modes?.[modo] || []);
      setErro('');
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : String(causa));
    } finally {
      setCarregando(false);
    }
  }, [modo]);

  useEffect(() => { void ler(); }, [ler]);

  // O catálogo vivo de cada provedor no modo: a lista que a conta declara
  // envelhece, e o modelo novo do provedor só aparecia pela busca.
  const [vivos, setVivos] = useState<Record<string, string[]>>({});
  const provedoresNoModo = [...new Set(alvos.map(a => contas.find(c => c.id === a.conta)?.provider).filter(Boolean))] as string[];
  const chaveDosProvedores = provedoresNoModo.join(',');
  useEffect(() => {
    for (const provedor of provedoresNoModo) {
      if (vivos[provedor]) continue;
      void apiClient.get<{ models?: { id: string; selectable?: boolean }[] }>(
        `/sentury/providers/${provedor}/models`, { headers: authHeaders() },
      ).then(dados => {
        const ids = (dados.models || []).filter(m => m.selectable !== false).map(m => m.id);
        // Catálogo grande (dezenas de modelos) fica na busca, não vira botão.
        setVivos(atual => ({ ...atual, [provedor]: ids.length <= MAX_VIVOS_COMO_BOTAO ? ids : [] }));
      }).catch(() => setVivos(atual => ({ ...atual, [provedor]: [] })));
    }
  }, [chaveDosProvedores]);

  const gravar = async (proximos: Alvo[]) => {
    setSalvando(true);
    try {
      await apiClient.post('/sentury/providers/modes',
        { modo, alvos: proximos }, { headers: authHeaders() });
      setAlvos(proximos);
      setErro('');
      onSalvo?.();
    } catch (causa) {
      // Sem alvo válido o servidor recusa, e a mensagem dele diz o motivo:
      // mostrar a recusa é melhor que fingir que salvou.
      setErro(causa instanceof Error ? causa.message : String(causa));
      void ler();
    } finally {
      setSalvando(false);
    }
  };

  const modelosDe = (conta: Conta): string[] => {
    const declarados = conta.models.length ? conta.models : (modelosDoProvedor[conta.provider] || []);
    const novos = (vivos[conta.provider] || []).filter(m => !declarados.includes(m));
    return [...declarados, ...novos];
  };

  // O que o modo usa aparece SEMPRE, mesmo fora da lista da conta: um modelo
  // escolhido pelo catalogo e que nao aparecesse aqui nao teria como sair.
  const chipsDe = (alvo: Alvo, conta?: Conta): string[] => {
    const base = conta ? modelosDe(conta) : [];
    return [...alvo.modelos.filter(m => !base.includes(m)), ...base];
  };

  // Escolhe um modelo apenas para este modo, sem alterar o catálogo do Router.
  const abrirBusca = async (indice: number, provedor: string) => {
    setBuscandoEm(indice);
    setTermo('');
    setLendoCatalogo(true);
    try {
      const dados = await apiClient.get<{ models?: { id: string; selectable?: boolean }[]; warnings?: string[] }>(
        `/sentury/providers/${provedor}/models`, { headers: authHeaders() });
      setCatalogo((dados.models || []).filter(m => m.selectable !== false).map(m => m.id));
      setAvisoDoCatalogo((dados.warnings || [])[0] || '');
    } catch (causa) {
      setCatalogo([]);
      setErro(causa instanceof Error ? causa.message : String(causa));
    } finally {
      setLendoCatalogo(false);
    }
  };

  const escolherDoCatalogo = (indice: number, modelo: string) => {
    setBuscandoEm(null);
    const alvo = alvos[indice];
    if (!alvo || alvo.modelos.includes(modelo)) return;
    void gravar(alvos.map((a, i) => i !== indice ? a : { ...a, modelos: [...a.modelos, modelo] }));
  };

  const adicionarIdManual = (indice: number) => {
    const id = termo.trim();
    if (!id || id.length > 200 || /\s/.test(id)) {
      setErro('O ID do modelo deve ter até 200 caracteres e não conter espaços.');
      return;
    }
    escolherDoCatalogo(indice, id);
  };

  const alternarModelo = (indice: number, modelo: string) => {
    const proximos = alvos.map((alvo, i) => i !== indice ? alvo : {
      ...alvo,
      modelos: alvo.modelos.includes(modelo)
        ? alvo.modelos.filter(m => m !== modelo)
        : [...alvo.modelos, modelo],
    });
    // Alvo sem modelo é alvo desligado: o servidor recusa, então tiramos aqui.
    void gravar(proximos.filter(alvo => alvo.modelos.length > 0));
  };

  const acrescentar = (conta: Conta) => {
    const modelos = modelosDe(conta);
    setAdicionando(false);
    if (!modelos.length) {
      setErro(`A conta ${conta.label || conta.id} não declara modelos — escolha outra.`);
      return;
    }
    void gravar([...alvos, { conta: conta.id, modelos: [modelos[0]] }]);
  };

  const remover = (indice: number) => void gravar(alvos.filter((_, i) => i !== indice));

  const disponiveis = contas.filter(c => c.configurada && !alvos.some(a => a.conta === c.id));

  return (
    <div className="rounded-xl border border-stone-300 bg-white/70 p-4">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-zinc-900">{rotulo}</h3>
        {carregando || salvando ? <Loader2 className="h-3.5 w-3.5 animate-spin text-gold-hover" /> : null}
        <span className="ml-auto text-[11px] text-zinc-500">
          {alvos.length === 0 ? 'desligado' : alvos.length === 1 ? '1 alvo' : `${alvos.length} alvos, nesta ordem`}
        </span>
      </div>

      {descricao ? <p className="mt-1 text-[11px] leading-5 text-zinc-500">{descricao}</p> : null}

      {erro ? <p className="mt-2 text-[11px] text-red-600">{erro}</p> : null}


      <div className="mt-3 space-y-2">
        {alvos.map((alvo, indice) => {
          const conta = contas.find(c => c.id === alvo.conta);
          const modelos = chipsDe(alvo, conta);
          const achados = catalogo
            .filter(m => !alvo.modelos.includes(m) && m.toLowerCase().includes(termo.trim().toLowerCase()))
            .slice(0, 12);
          return (
            <div key={`${alvo.conta}-${indice}`} className="rounded-lg border border-stone-200 bg-[#fffdf8] p-3">
              <div className="flex items-center gap-2">
                <span className="text-[10px] tabular-nums text-zinc-400">{indice + 1}º</span>
                <ProviderLogo providerKey={conta?.provider || alvo.conta} label={conta?.label || alvo.conta} className="h-4 w-4" />
                <span className="text-xs font-semibold text-zinc-800">{conta?.label || alvo.conta}</span>
                {conta ? <SeloDeAcesso conta={conta} custo={custoDoProvedor[conta.provider] || ''} /> : null}
                <button
                  type="button"
                  onClick={() => remover(indice)}
                  className="ml-auto rounded p-1 text-zinc-400 hover:bg-stone-100 hover:text-zinc-700"
                  aria-label={`Tirar ${conta?.label || alvo.conta} do ${rotulo}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {modelos.map(modelo => {
                  const ligado = alvo.modelos.includes(modelo);
                  return (
                    <button
                      key={modelo}
                      type="button"
                      onClick={() => alternarModelo(indice, modelo)}
                      aria-pressed={ligado}
                      className={`flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] transition-colors ${
                        ligado
                          ? 'border-gold bg-gold-soft text-gold-ink'
                          : 'border-stone-300 text-zinc-500 hover:border-zinc-400'
                      }`}
                    >
                      {ligado ? <Check className="h-2.5 w-2.5" /> : null}
                      {modelo}
                    </button>
                  );
                })}
                {conta ? (
                  <button
                    type="button"
                    onClick={() => void abrirBusca(indice, conta.provider)}
                    className="flex items-center gap-1 rounded-full border border-dashed border-stone-300 px-2 py-0.5 text-[10px] text-zinc-500 hover:border-gold hover:text-zinc-800"
                  >
                    <Plus className="h-2.5 w-2.5" />outro modelo
                  </button>
                ) : null}
              </div>
              {buscandoEm === indice ? (
                <div className="mt-2 rounded-lg border border-stone-200 bg-white p-2">
                  <div className="flex items-center gap-1.5 rounded-md border border-stone-200 px-2 py-1">
                    <Search className="h-3 w-3 text-zinc-400" />
                    <input
                      autoFocus
                      value={termo}
                      onChange={evento => setTermo(evento.target.value)}
                      placeholder={`Buscar no catálogo de ${conta?.label || alvo.conta}`}
                      className="w-full bg-transparent text-[11px] outline-none"
                    />
                    <button type="button" onClick={() => setBuscandoEm(null)} aria-label="Fechar busca" className="text-zinc-400 hover:text-zinc-700">
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                  {avisoDoCatalogo && !lendoCatalogo ? (
                    <p className="mt-1.5 px-1 text-[10px] leading-4 text-zinc-400">{avisoDoCatalogo}</p>
                  ) : null}
                  <div className="mt-1.5 max-h-40 overflow-y-auto">
                    {lendoCatalogo ? (
                      <p className="px-1 py-1 text-[11px] text-zinc-500">Lendo o catálogo…</p>
                    ) : achados.length === 0 ? (
                      <p className="px-1 py-1 text-[11px] text-zinc-500">
                        {catalogo.every(m => alvo.modelos.includes(m))
                          ? 'Todos os modelos que o catálogo conhece já estão aqui.'
                          : 'Nenhum modelo com esse nome.'}
                      </p>
                    ) : achados.map(modelo => (
                      <button
                        key={modelo}
                        type="button"
                        onClick={() => escolherDoCatalogo(indice, modelo)}
                        className="block w-full truncate rounded px-1.5 py-1 text-left font-mono text-[10px] text-zinc-700 hover:bg-stone-100"
                      >
                        {modelo}
                      </button>
                    ))}
                  </div>
                  {termo.trim() && !catalogo.includes(termo.trim()) && !alvo.modelos.includes(termo.trim()) ? (
                    <button type="button" onClick={() => adicionarIdManual(indice)}
                      className="mt-2 flex w-full items-center gap-1.5 rounded-md border border-dashed border-stone-300 px-2 py-1.5 text-left text-[10px] font-medium text-zinc-700 hover:border-gold">
                      <Plus className="h-3 w-3" /> Usar ID manual: <code className="truncate">{termo.trim()}</code>
                    </button>
                  ) : null}
                  <p className="mt-1.5 text-[10px] text-zinc-400">IDs manuais não são verificados; se o provedor os recusar, a chamada falhará.</p>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      {adicionando ? (
        <div className="mt-2 rounded-lg border border-stone-200 bg-white p-1.5">
          {disponiveis.length === 0 ? (
            <p className="px-2 py-1.5 text-[11px] text-zinc-500">
              Nenhuma outra conta configurada. Ligue uma chave, ou entre no CLI do provedor.
            </p>
          ) : disponiveis.map(conta => (
            <button
              key={conta.id}
              type="button"
              onClick={() => acrescentar(conta)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-stone-100"
            >
              <ProviderLogo providerKey={conta.provider} label={conta.label || conta.id} className="h-4 w-4" />
              <span className="text-xs text-zinc-800">{conta.label || conta.id}</span>
              <span className="ml-auto font-mono text-[10px] text-zinc-400">{modelosDe(conta).length} modelos</span>
            </button>
          ))}
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAdicionando(true)}
          disabled={salvando}
          className="mt-2 flex items-center gap-1.5 rounded-lg border border-dashed border-stone-300 px-2.5 py-1.5 text-[11px] text-zinc-600 transition-colors hover:border-gold hover:text-zinc-900 disabled:opacity-50"
        >
          <Plus className="h-3 w-3" />
          {alvos.length ? 'Acrescentar reserva' : 'Escolher quem responde'}
        </button>
      )}
    </div>
  );
};
