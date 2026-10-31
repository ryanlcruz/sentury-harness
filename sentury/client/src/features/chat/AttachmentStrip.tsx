import React from 'react';
import { Download, ExternalLink } from 'lucide-react';
import { useWorkbenchStore } from '../../stores/workbench-store';

interface Anexo {
  type?: string;
  filename?: string;
  mime_type?: string;
  content_base64?: string;
  content?: string;
  artifact_id?: string;
}

interface AttachmentStripProps {
  sessionId: string;
  anexos: Anexo[];
}

/** Acima disto a grade viraria um mural e o texto sairia da tela; daí em
 *  diante os arquivos viram pílulas ao lado da conversa. */
const LIMITE_DA_GRADE = 5;

/** Formatos que o workbench sabe abrir; o resto baixa direto. */
const ABRE_NO_WORKBENCH = new Set([
  'html', 'markdown', 'md', 'csv', 'ascii', 'svg', 'chart_json',
  'png', 'jpg', 'jpeg', 'webp',
]);

/** O rotulo da ficha: o tipo interno as vezes e maior que a extensao real
 *  ("markdown" virava "MARK" no quadradinho). */
const ROTULO: Record<string, string> = {
  markdown: 'MD',
  chart_json: 'IMG',
  ascii: 'TXT',
  jpeg: 'JPG',
};

const COR: Record<string, string> = {
  pdf: 'bg-[#e4574c]',
  xlsx: 'bg-[#1f9254]',
  csv: 'bg-[#1f9254]',
  docx: 'bg-[#3b6fd4]',
  pptx: 'bg-[#d97706]',
  markdown: 'bg-[#7b61b8]',
  md: 'bg-[#7b61b8]',
  html: 'bg-[#c2410c]',
  svg: 'bg-[#0f766e]',
  ascii: 'bg-zinc-600',
};

/** Corta pelo meio e preserva a extensão: o fim do nome é o que diz o que o
 *  arquivo é, e cortar ali deixa cinco PDFs com o mesmo rótulo. */
function encurtar(nome: string, maximo = 26): string {
  if (nome.length <= maximo) return nome;
  const ponto = nome.lastIndexOf('.');
  const extensao = ponto > 0 ? nome.slice(ponto) : '';
  const base = ponto > 0 ? nome.slice(0, ponto) : nome;
  const sobra = Math.max(6, maximo - extensao.length - 1);
  return `${base.slice(0, sobra)}…${extensao}`;
}

function baixar(anexo: Anexo): void {
  const nome = anexo.filename || 'arquivo';
  const tipo = anexo.mime_type || 'application/octet-stream';
  const href = anexo.content_base64
    ? `data:${tipo};base64,${anexo.content_base64}`
    : `data:${tipo};charset=utf-8,${encodeURIComponent(anexo.content || '')}`;
  const link = document.createElement('a');
  link.href = href;
  link.download = nome;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function extensaoDe(anexo: Anexo, indice: number): {
  nome: string; tipo: string; rotulo: string; abre: boolean;
} {
  const nome = anexo.filename || `arquivo-${indice + 1}`;
  const tipo = (anexo.type || nome.split('.').pop() || '').toLowerCase();
  return {
    nome,
    tipo,
    rotulo: ROTULO[tipo] || tipo.slice(0, 4).toUpperCase() || 'BIN',
    abre: ABRE_NO_WORKBENCH.has(tipo),
  };
}

function textoDe(anexo: Anexo): string {
  if (typeof anexo.content === 'string') return anexo.content;
  if (!anexo.content_base64) return '';
  try { return decodeURIComponent(escape(window.atob(anexo.content_base64))); }
  catch { return ''; }
}

export const AttachmentStrip: React.FC<AttachmentStripProps> = ({ sessionId, anexos }) => {
  const addArtifact = useWorkbenchStore(state => state.addArtifact);
  const setActiveArtifact = useWorkbenchStore(state => state.setActiveArtifact);
  const openWorkbench = useWorkbenchStore(state => state.openWorkbench);

  if (!anexos.length) return null;

  const acionar = (anexo: Anexo, abre: boolean, nome: string, tipo: string) => {
    if (!abre) { baixar(anexo); return; }
    const texto = textoDe(anexo);
    if (!texto) { baixar(anexo); return; }
    const id = `att-${sessionId}-${nome}`;
    const comum = { id, title: nome, sessionId, createdAt: new Date().toISOString() };
    // O workbench renderiza markdown; HTML entra como codigo, que e o que ele
    // mostra sem executar nada.
    addArtifact(tipo === 'html'
      ? { ...comum, type: 'code', code: texto, language: 'html' }
      : { ...comum, type: 'markdown', content: texto });
    setActiveArtifact(id);
    openWorkbench(id);
  };

  // Poucos arquivos cabem lado a lado e o nome fica legível embaixo do ícone.
  if (anexos.length <= LIMITE_DA_GRADE) {
    return (
      <div className="mt-3 grid max-w-[460px] grid-cols-[repeat(auto-fill,minmax(104px,1fr))] gap-2.5">
        {anexos.map((anexo, indice) => {
          const { nome, tipo, rotulo, abre } = extensaoDe(anexo, indice);
          return (
            <button
              key={`${nome}-${indice}`}
              type="button"
              title={`${nome} — ${abre ? 'abrir' : 'baixar'}`}
              onClick={() => acionar(anexo, abre, nome, tipo)}
              className="flex w-full flex-col items-center gap-2 overflow-hidden rounded-[10px] border border-stone-300 bg-[#efece2] px-2 pb-2.5 pt-3.5 transition-colors hover:border-gold hover:bg-[#fffdf8]"
            >
              <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[10px] font-mono text-[10px] font-medium tracking-wide text-white ${COR[tipo] || 'bg-zinc-500'}`}>
                {rotulo}
              </span>
              <span className="line-clamp-2 w-full break-all text-center text-[11.5px] font-medium leading-[1.3] text-zinc-800">
                {nome}
              </span>
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="mt-3 flex max-w-[470px] flex-wrap gap-1.5">
      {anexos.map((anexo, indice) => {
        const { nome, tipo, rotulo, abre } = extensaoDe(anexo, indice);
        return (
          <button
            key={`${nome}-${indice}`}
            type="button"
            title={`${nome} — ${abre ? 'abrir' : 'baixar'}`}
            onClick={() => acionar(anexo, abre, nome, tipo)}
            className="group inline-flex max-w-[230px] items-center gap-2 rounded-full border border-stone-300 bg-[#efece2] py-1 pl-1 pr-3 transition-colors hover:border-gold hover:bg-[#fffdf8]"
          >
            <span className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-md font-mono text-[8px] font-medium tracking-wide text-white ${COR[tipo] || 'bg-zinc-500'}`}>
              {rotulo}
            </span>
            <span className="truncate text-[12.5px] font-medium text-zinc-800">{encurtar(nome)}</span>
            {abre
              ? <ExternalLink className="h-3 w-3 shrink-0 text-zinc-400 group-hover:text-zinc-700" />
              : <Download className="h-3 w-3 shrink-0 text-zinc-400 group-hover:text-zinc-700" />}
          </button>
        );
      })}
    </div>
  );
};
