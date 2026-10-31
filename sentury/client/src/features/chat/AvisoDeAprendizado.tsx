import React, { useState } from 'react';
import { BookmarkCheck, ChevronRight, Wrench } from 'lucide-react';
import { Aprendizado } from '../../contracts/domain/session';
import { authHeaders, getRuntimeConfig } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';

type Estado = 'guardado' | 'desfazendo' | 'desfeito' | 'falhou';

const ACAO_DA_SKILL: Record<string, string> = {
  criada: 'skill nova',
  acrescentada: 'lição nova na skill',
  corrigida: 'skill corrigida',
  anexado: 'arquivo novo na skill',
};

async function desfazerNoServidor(item: Aprendizado): Promise<void> {
  const config = getRuntimeConfig();
  apiClient.setBaseUrl(config.apiUrl);
  if (item.tipo === 'skill') {
    await apiClient.post(`/sentury/skills/${encodeURIComponent(item.nome || '')}/desfazer`, {}, { headers: authHeaders() });
    return;
  }
  await apiClient.post('/sentury/memory/usuario/esquecer', { user_id: config.userId, texto: item.texto }, { headers: authHeaders() });
}

const Item: React.FC<{ item: Aprendizado }> = ({ item }) => {
  const [estado, setEstado] = useState<Estado>('guardado');
  const Icone = item.tipo === 'skill' ? Wrench : BookmarkCheck;
  const texto = item.tipo === 'skill' ? item.nome : item.texto;
  const legenda = item.tipo === 'skill' ? (ACAO_DA_SKILL[item.acao || ''] || 'skill') : 'memória';

  const desfazer = async () => {
    setEstado('desfazendo');
    try {
      await desfazerNoServidor(item);
      setEstado('desfeito');
    } catch {
      setEstado('falhou');
    }
  };

  if (estado === 'desfeito') {
    return <p className="text-xs text-zinc-500">{item.tipo === 'skill' ? `Desfiz a mudança em ${item.nome}.` : 'Esqueci.'}</p>;
  }
  return (
    <div className="flex items-start gap-2.5 text-[13px] text-zinc-600">
      <Icone className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold-hover" />
      <p className="min-w-0 flex-1">
        {texto}
        <span className="block text-[11px] text-zinc-400">{legenda}</span>
        {estado === 'falhou' && <span className="block text-[11px] text-red-700">Não consegui desfazer agora. Tente pela tela de Memória ou de Skills.</span>}
      </p>
      <button
        type="button"
        onClick={() => void desfazer()}
        disabled={estado === 'desfazendo'}
        className="shrink-0 text-xs text-zinc-400 underline decoration-stone-300 underline-offset-2 hover:text-zinc-700 hover:decoration-gold disabled:opacity-50"
      >
        desfazer
      </button>
    </div>
  );
};

/** O que o turno guardou, recolhido no rodapé da resposta: aparece como uma
 *  linha e abre num clique, com desfazer em cada item. */
export const AvisoDeAprendizado: React.FC<{ itens: Aprendizado[] }> = ({ itens }) => {
  const [aberto, setAberto] = useState(false);
  if (!itens.length) return null;
  const rotulo = itens.length === 1 ? 'Aprendi uma coisa' : `Aprendi ${itens.length} coisas`;
  return (
    <div>
      <button
        type="button"
        aria-expanded={aberto}
        onClick={() => setAberto(valor => !valor)}
        className="inline-flex items-center gap-2 text-xs text-zinc-500 hover:text-zinc-800"
      >
        <BookmarkCheck className="h-3.5 w-3.5 text-gold-ink" />
        <span className="font-semibold text-zinc-700">{rotulo}</span>
        <ChevronRight className={`h-3.5 w-3.5 transition-transform motion-reduce:transition-none ${aberto ? 'rotate-90' : ''}`} />
      </button>
      {aberto && (
        <div className="mt-2 max-w-2xl space-y-2 rounded-lg border border-stone-200 bg-[#fffdf8] px-3 py-2.5">
          {itens.map((item, indice) => <Item key={`${item.tipo}-${item.nome || item.texto}-${indice}`} item={item} />)}
        </div>
      )}
    </div>
  );
};
