import { useEffect, useState } from 'react';
import { FileText, MessagesSquare } from 'lucide-react';
import { renderMarkdown } from '../../domain/markdown';
import { Coruja } from './Coruja';
import { coresDoAgente } from './useEsperando';
import { abrirAssuntoDaMesa } from './abrirConversa';
import { nomeVisivel, residentes, type Agente, type Decisao } from './api';

/** O que a equipe já decidiu, da decisão mais nova para a mais antiga. Cada uma é
 * um arquivo `.md`: a Mesa grava ao fechar, e o Sentury ou um residente anotam. */
export default function DecisoesView({ agentes }: { agentes: Agente[] }) {
  const [decisoes, setDecisoes] = useState<Decisao[] | null>(null);
  const [erro, setErro] = useState('');
  useEffect(() => {
    let vivo = true;
    const ler = () => residentes.decisoes()
      .then(lista => { if (vivo) { setDecisoes(lista); setErro(''); } })
      .catch(e => { if (vivo) setErro(e instanceof Error ? e.message : 'Não consegui ler as decisões.'); });
    void ler();
    const intervalo = window.setInterval(() => void ler(), 15000);
    return () => { vivo = false; window.clearInterval(intervalo); };
  }, []);

  if (erro) return <p role="alert" className="text-sm text-red-700">{erro}</p>;
  if (!decisoes) return <p className="text-sm text-zinc-500">Lendo as decisões…</p>;
  if (!decisoes.length) {
    return <p className="rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] p-6 text-sm text-zinc-600">
      Nenhuma decisão ainda. Um assunto da Mesa que fecha com resumo vira uma decisão aqui, e no chat dá para
      pedir "anote essa decisão".
    </p>;
  }
  return <ol className="space-y-3">
    {decisoes.map(d => {
      const assunto = d.origem.startsWith('mesa:') ? d.origem.slice('mesa:'.length) : '';
      return <li key={d.caminho} className="rounded-2xl border border-[#e3ddcd] bg-[#fffdf8] p-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-zinc-500">{new Date(d.em * 1000).toLocaleDateString('pt-BR')}</p>
            <h3 className="mt-0.5 font-semibold">{d.titulo}</h3>
          </div>
          <div className="flex -space-x-2" aria-label={`Participantes: ${d.participantes.map(nomeVisivel).join(', ')}`}>
            {d.participantes.map(nome => {
              const agente = agentes.find(a => a.nome === nome);
              return <Coruja key={nome} tamanho={28} rotulo={nome} cores={coresDoAgente(agente)} acessorios={agente?.aparencia.acessorios} estado="parado" />;
            })}
          </div>
        </div>
        <div className="mt-2 text-sm text-zinc-800" dangerouslySetInnerHTML={{ __html: renderMarkdown(d.resumo) }} />
        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-zinc-500">
          <span className="flex min-w-0 items-center gap-1" title={d.caminho}><FileText size={14} /><span className="truncate font-mono">{d.caminho.split(/[\\/]/).pop()}</span></span>
          {assunto ? <button type="button" onClick={() => abrirAssuntoDaMesa(assunto)}
            className="flex items-center gap-1 text-gold-ink hover:underline"><MessagesSquare size={14} />Ver na Mesa</button> : null}
        </div>
      </li>;
    })}
  </ol>;
}
