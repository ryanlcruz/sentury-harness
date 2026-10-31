import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Users, X } from 'lucide-react';
import { Coruja, type CoresCoruja } from './Coruja';
import { residentes } from './api';

/** O cartão da equipe: vários residentes propostos no mesmo pedido. Cada linha é
 * um residente; a pessoa desmarca quem não quer e cria os marcados de uma vez.
 * Aparece no lugar da fábrica quando o turno pausou com mais de um `criar_agente`. */

const CINZA: CoresCoruja = { penas: '#76767e', asas: '#55555c', barriga: '#b4b4bb' };
const texto = (valor: unknown) => (typeof valor === 'string' ? valor : '');
const lista = (valor: unknown) => (Array.isArray(valor) ? valor.map(String) : []);
const visivel = (nome: string) => (nome ? nome[0].toUpperCase() + nome.slice(1) : 'Residente');

interface Props {
  equipe: Record<string, unknown>[];
  enviando: boolean;
  erro: string;
  onCriar: (nomes: string[]) => void;
  onNaoCriar: () => void;
  onFechar: () => void;
}

const Membro: React.FC<{ membro: Record<string, unknown>; incluido: boolean; onTrocar: () => void }> = ({ membro, incluido, onTrocar }) => {
  const nome = texto(membro.nome);
  const [aberto, setAberto] = useState(false);
  const [cores, setCores] = useState<CoresCoruja>(CINZA);
  const [acessorios, setAcessorios] = useState<Record<string, string>>({});
  // O servidor monta a coruja: a da linha é a mesma que vai nascer.
  useEffect(() => {
    void residentes.previa(nome, texto(membro.familia))
      .then(dados => { if (dados.cores.penas) setCores(dados.cores); setAcessorios(dados.aparencia.acessorios); })
      .catch(() => undefined);
  }, [nome, membro.familia]);
  return (
    <li className={`px-4 py-3 ${incluido ? '' : 'opacity-55'}`}>
      <div className="flex items-center gap-3">
        <input type="checkbox" checked={incluido} onChange={onTrocar} aria-label={`Incluir ${visivel(nome)}`}
          className="h-4 w-4 shrink-0 accent-[#c9a227]" />
        <Coruja cores={cores} acessorios={acessorios} tamanho={40} rotulo={nome} />
        <button type="button" onClick={() => setAberto(valor => !valor)} aria-expanded={aberto}
          className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-zinc-900">{visivel(nome)}</span>
            <span className="block truncate text-xs text-zinc-600">{texto(membro.papel)}</span>
          </span>
          {aberto ? <ChevronDown className="h-4 w-4 shrink-0 text-zinc-400" /> : <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" />}
        </button>
      </div>
      {aberto ? (
        <dl className="mt-2.5 space-y-1.5 pl-[76px] text-xs text-zinc-600">
          <div><dt className="font-semibold text-zinc-700">Objetivo</dt><dd>{texto(membro.objetivo)}</dd></div>
          <div><dt className="font-semibold text-zinc-700">Ferramentas</dt><dd>{lista(membro.ferramentas).join(', ') || 'nenhuma'}</dd></div>
          {lista(membro.skills).length ? <div><dt className="font-semibold text-zinc-700">Skills</dt><dd>{lista(membro.skills).map(s => `/${s}`).join(', ')}</dd></div> : null}
          {texto(membro.personalidade) ? <div><dt className="font-semibold text-zinc-700">Como fala</dt><dd>{texto(membro.personalidade)}</dd></div> : null}
        </dl>
      ) : null}
    </li>
  );
};

export const EquipeDeResidentes: React.FC<Props> = ({ equipe, enviando, erro, onCriar, onNaoCriar, onFechar }) => {
  const [fora, setFora] = useState<Set<string>>(new Set());
  const nomes = equipe.map(membro => texto(membro.nome)).filter(Boolean);
  const marcados = nomes.filter(nome => !fora.has(nome));
  const trocar = (nome: string) => setFora(atual => {
    const proximo = new Set(atual);
    if (proximo.has(nome)) proximo.delete(nome); else proximo.add(nome);
    return proximo;
  });
  return (
    <section aria-label="Nova equipe">
      <header className="flex items-start gap-3 border-b border-[#ebe5d8] px-4 py-3.5">
        <Users className="mt-0.5 h-4 w-4 shrink-0 text-gold-ink" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-bold uppercase tracking-[.13em] text-gold-ink">Nova equipe</p>
          <p className="mt-0.5 text-sm text-zinc-700">{nomes.length} residentes propostos. Desmarque quem não quiser.</p>
        </div>
        <button type="button" onClick={onFechar} aria-label="Fechar" className="rounded-md p-1 text-zinc-400 hover:bg-stone-100 hover:text-zinc-700">
          <X className="h-4 w-4" />
        </button>
      </header>
      <ul className="divide-y divide-[#efe9dc]">
        {equipe.map(membro => (
          <Membro key={texto(membro.nome)} membro={membro} incluido={!fora.has(texto(membro.nome))}
            onTrocar={() => trocar(texto(membro.nome))} />
        ))}
      </ul>
      {erro ? <p role="alert" className="px-4 pt-3 text-xs text-red-700">{erro}</p> : null}
      <footer className="flex items-center justify-end gap-2 border-t border-[#ebe5d8] px-4 py-3">
        <button type="button" onClick={onNaoCriar} disabled={enviando}
          className="rounded-lg px-3 py-2 text-xs font-semibold text-zinc-600 hover:bg-stone-100 disabled:opacity-50">Não criar</button>
        <button type="button" onClick={() => onCriar(marcados)} disabled={enviando || !marcados.length}
          className="rounded-lg bg-zinc-900 px-3.5 py-2 text-xs font-semibold text-white hover:bg-zinc-800 disabled:opacity-40">
          {enviando ? 'Criando…' : marcados.length === 1 ? 'Criar 1 residente' : `Criar ${marcados.length} residentes`}
        </button>
      </footer>
    </section>
  );
};
