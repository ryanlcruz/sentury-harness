import React, { useCallback, useEffect, useState } from 'react';
import { Check, CircleAlert, FlaskConical, RefreshCw } from 'lucide-react';
import { z } from 'zod';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

const ProvedorSchema = z.object({
  nome: z.string(), rotulo: z.string(), descricao: z.string(), tem_chave: z.boolean(), precisa_chave: z.boolean(), chave_env: z.string(),
  base_url: z.string(), modelos: z.array(z.string()), modelos_do_servidor: z.boolean(),
});
const EstadoSchema = z.object({
  escolha: z.object({ provedor: z.string(), modelo: z.string(), base_url: z.string() }),
  origem: z.string(),
  ligado: z.boolean(),
  provedores: z.array(ProvedorSchema),
});
const TesteSchema = z.object({
  ok: z.boolean(), erro: z.string().optional(), mensagem: z.string().optional(), ms: z.number().optional(),
  relacionado: z.number().optional(), sem_relacao: z.number().optional(), corte: z.number().optional(),
  separa: z.boolean().optional(),
});
type Estado = z.infer<typeof EstadoSchema>;
type Teste = z.infer<typeof TesteSchema>;
type Rascunho = { provedor: string; modelo: string; base_url: string };

const opcoes = () => ({ headers: authHeaders() });
const nota = (valor?: number) => (valor ?? 0).toFixed(2).replace('.', ',');
const motivo = (erro: unknown) => (erro instanceof Error ? erro.message : 'Não consegui falar com a API.');

/** Qual modelo de embeddings liga pedido a decisão e conhecimento pelo sentido. */
export const EmbeddingsSection: React.FC = () => {
  const [estado, setEstado] = useState<Estado | null>(null);
  const [rascunho, setRascunho] = useState<Rascunho>({ provedor: 'nenhum', modelo: '', base_url: '' });
  const [locais, setLocais] = useState<{ ligado: boolean; modelos: string[] } | null>(null);
  const [teste, setTeste] = useState<Teste | null>(null);
  const [ocupado, setOcupado] = useState<'' | 'testando' | 'salvando' | 'buscando'>('');
  const [erro, setErro] = useState('');
  const [novaChave, setNovaChave] = useState('');

  const carregar = useCallback(async () => {
    try {
      const lido = EstadoSchema.parse(await apiClient.get('/sentury/ajustes/embeddings', opcoes()));
      setEstado(lido);
      setRascunho(lido.escolha);
    } catch (e) { setErro(motivo(e)); }
  }, []);
  useEffect(() => { void carregar(); }, [carregar]);

  if (!estado) return erro ? <p className="mt-6 text-sm text-red-700">{erro}</p> : null;
  const provedor = estado.provedores.find(p => p.nome === rascunho.provedor);
  const semChave = Boolean(provedor?.precisa_chave && !provedor.tem_chave);
  // Vindo do .env, confirmar a mesma escolha também conta: ela passa a morar na tela.
  const mudou = estado.origem !== 'tela' || JSON.stringify(rascunho) !== JSON.stringify(estado.escolha);
  const modelos = provedor?.modelos_do_servidor ? (locais?.modelos || []) : (provedor?.modelos || []);

  const escolherProvedor = (nome: string) => {
    const alvo = estado.provedores.find(p => p.nome === nome);
    setTeste(null);
    setErro('');
    setRascunho({ provedor: nome, modelo: alvo?.modelos[0] || '', base_url: alvo?.base_url || '' });
    if (alvo?.modelos_do_servidor) void buscarLocais(alvo.base_url);
  };

  const buscarLocais = async (base: string) => {
    setOcupado('buscando');
    try {
      const lido = await apiClient.get<{ ligado: boolean; modelos: string[] }>(
        `/sentury/ajustes/embeddings/servidor-local?base_url=${encodeURIComponent(base)}`, opcoes());
      setLocais(lido);
      if (lido.modelos.length) setRascunho(atual => ({ ...atual, modelo: atual.modelo && lido.modelos.includes(atual.modelo) ? atual.modelo : lido.modelos[0] }));
    } catch (e) { setErro(motivo(e)); } finally { setOcupado(''); }
  };

  // A chave vai para o mesmo cofre dos provedores: a do Gemini serve ao chat e aos embeddings.
  const guardarChave = async () => {
    if (!provedor?.chave_env || !novaChave.trim()) return;
    setOcupado('salvando');
    setErro('');
    try {
      await apiClient.post('/sentury/providers/keys', { key_env: provedor.chave_env, valor: novaChave.trim() }, opcoes());
      setNovaChave('');
      const lido = EstadoSchema.parse(await apiClient.get('/sentury/ajustes/embeddings', opcoes()));
      setEstado(lido);
    } catch (e) { setErro(motivo(e)); } finally { setOcupado(''); }
  };

  const testar = async () => {
    setOcupado('testando');
    setErro('');
    try { setTeste(TesteSchema.parse(await apiClient.post('/sentury/ajustes/embeddings/testar', rascunho, opcoes()))); }
    catch (e) { setErro(motivo(e)); } finally { setOcupado(''); }
  };

  const salvar = async () => {
    setOcupado('salvando');
    setErro('');
    try {
      const lido = EstadoSchema.parse(await apiClient.put('/sentury/ajustes/embeddings', rascunho, opcoes()));
      setEstado(lido);
      setRascunho(lido.escolha);
    } catch (e) { setErro(motivo(e)); } finally { setOcupado(''); }
  };

  return (
    <section className="mt-8">
      <h3 className="text-sm font-semibold">Busca por sentido</h3>
      <p className="mt-1 text-xs leading-5 text-zinc-500">
        Liga o pedido às decisões da equipe e à base de conhecimento pelo significado. Com um modelo, "agora temos 3 vagas"
        traz de volta "decidimos desligar 3 pessoas"; sem modelo, só palavras iguais se encontram.
      </p>
      {estado.origem === 'env' ? (
        <p className="mt-3 text-xs text-zinc-600">Em uso agora pelo <code>.env</code> ({estado.escolha.provedor}, {estado.escolha.modelo}). Escolher aqui passa a valer no lugar dele.</p>
      ) : null}
      <div role="radiogroup" aria-label="Modelo da busca por sentido" className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {estado.provedores.map(item => {
          const selecionado = item.nome === rascunho.provedor;
          return (
            <button key={item.nome} type="button" role="radio" aria-checked={selecionado} onClick={() => escolherProvedor(item.nome)}
              className={`rounded-xl border p-3.5 text-left transition-colors ${selecionado ? 'border-gold bg-gold-soft' : 'border-stone-200 bg-white/80 hover:border-stone-300'}`}>
              <span className="flex items-center gap-2">
                <strong className="text-sm">{item.rotulo}</strong>
                {estado.escolha.provedor === item.nome && estado.ligado ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[9px] font-bold text-emerald-700">EM USO</span> : null}
                {item.precisa_chave && !item.tem_chave ? <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[9px] font-bold text-zinc-500">SEM CHAVE</span> : null}
              </span>
              <span className="mt-1 block text-[11px] leading-4 text-zinc-500">{item.descricao}</span>
            </button>
          );
        })}
      </div>

      {provedor && provedor.nome !== 'nenhum' ? (
        <div className="mt-4 flex flex-col gap-3 rounded-xl border border-stone-200 bg-white/80 p-4">
          {provedor.modelos_do_servidor ? (
            <label className="block">
              <span className="text-xs font-semibold text-zinc-700">Endereço do servidor local</span>
              <span className="mt-1.5 flex gap-2">
                <input value={rascunho.base_url} onChange={event => setRascunho({ ...rascunho, base_url: event.target.value })}
                  className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-gold" />
                <button type="button" onClick={() => void buscarLocais(rascunho.base_url)} disabled={ocupado !== ''}
                  className="flex items-center gap-1.5 rounded-lg border border-stone-300 px-3 text-xs font-medium hover:border-gold disabled:opacity-50">
                  <RefreshCw className={`h-3.5 w-3.5 ${ocupado === 'buscando' ? 'animate-spin' : ''}`} />Ver modelos
                </button>
              </span>
              {locais && !locais.ligado ? <span className="mt-1.5 block text-[11px] text-amber-800">O servidor local não respondeu. Abra o LM Studio e ligue o servidor, ou use a tela Modelos locais.</span> : null}
              {locais?.ligado && !locais.modelos.length ? <span className="mt-1.5 block text-[11px] text-amber-800">O servidor não tem modelo de embeddings carregado. No LM Studio, baixe e carregue um (por exemplo, nomic-embed-text).</span> : null}
            </label>
          ) : null}
          {modelos.length ? (
            <label className="block">
              <span className="text-xs font-semibold text-zinc-700">Modelo</span>
              <select value={rascunho.modelo} onChange={event => setRascunho({ ...rascunho, modelo: event.target.value })}
                className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-gold">
                {modelos.map(modelo => <option key={modelo} value={modelo}>{modelo}</option>)}
              </select>
            </label>
          ) : null}
          {semChave ? (
            <form className="block" onSubmit={event => { event.preventDefault(); void guardarChave(); }}>
              <span className="flex items-center gap-1.5 text-xs font-semibold text-amber-800"><CircleAlert className="h-4 w-4 shrink-0" />Chave de {provedor.rotulo}</span>
              <span className="mt-1.5 flex gap-2">
                <input type="password" autoComplete="off" value={novaChave} onChange={event => setNovaChave(event.target.value)}
                  placeholder={`Cole a chave (${provedor.chave_env})`} aria-label={`Chave de ${provedor.rotulo}`}
                  className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-gold" />
                <button type="submit" disabled={!novaChave.trim() || ocupado !== ''}
                  className="rounded-lg bg-zinc-900 px-3 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">Guardar chave</button>
              </span>
              <span className="mt-1.5 block text-[11px] text-zinc-500">Fica no cofre do Sentury, o mesmo dos provedores: a chave vale também para conversar com {provedor.rotulo}.</span>
            </form>
          ) : null}
          {teste ? (
            teste.ok && teste.relacionado !== undefined ? (
              <p className={`flex items-start gap-2 text-xs ${teste.separa ? 'text-emerald-800' : 'text-amber-800'}`}>
                {teste.separa ? <Check className="mt-0.5 h-4 w-4 shrink-0" /> : <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />}
                <span>
                  {teste.separa ? 'Separa bem: ' : 'Não separou o exemplo: '}
                  nota {nota(teste.relacionado)} para o par com relação e {nota(teste.sem_relacao)} para o sem relação
                  (o mínimo deste modelo é {nota(teste.corte)}). Respondeu em {teste.ms} ms.
                </span>
              </p>
            ) : <p className="text-xs text-red-700">{teste.erro || teste.mensagem}</p>
          ) : null}
        </div>
      ) : null}

      {erro ? <p role="alert" className="mt-3 text-xs text-red-700">{erro}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        {rascunho.provedor !== 'nenhum' ? (
          <button type="button" onClick={() => void testar()} disabled={ocupado !== '' || semChave || !rascunho.modelo}
            className="flex items-center gap-1.5 rounded-lg border border-stone-300 bg-white px-4 py-2 text-xs font-semibold text-zinc-700 hover:border-gold disabled:opacity-50">
            <FlaskConical className="h-3.5 w-3.5" />{ocupado === 'testando' ? 'Testando…' : 'Testar'}
          </button>
        ) : null}
        <button type="button" onClick={() => void salvar()} disabled={ocupado !== '' || !mudou || semChave || (rascunho.provedor !== 'nenhum' && !rascunho.modelo)}
          className="rounded-lg bg-zinc-900 px-4 py-2 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">
          {ocupado === 'salvando' ? 'Salvando…' : 'Usar este'}
        </button>
      </div>
    </section>
  );
};
