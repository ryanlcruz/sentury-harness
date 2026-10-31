import React, { useState } from 'react';
import { ResizeHandle } from '../../components/ResizeHandle';
import { useWorkbenchStore } from '../../stores/workbench-store';
import { SeverityCell } from '../../components/SeverityCell';
import { X, Table, Download, ExternalLink } from 'lucide-react';
import { renderMarkdown } from '../../domain/markdown';
import { abrirEmJanela } from '../../runtime/window-open';
import { PlanoCard } from '../chat/PlanoCard';
import { CommandCard } from '../chat/CommandCard';
import { AttachmentRenderer } from '../chat/AttachmentRenderer';

export const WorkbenchPanel: React.FC = () => {
  const [largura, setLarguraBruta] = useState<number>(() => {
    const salvo = Number(localStorage.getItem('sentury_workbench_w'));
    return Number.isFinite(salvo) && salvo >= 320 ? salvo : 672;
  });
  const setLargura = (v: number) => {
    setLarguraBruta(v);
    try { localStorage.setItem('sentury_workbench_w', String(v)); } catch { /* modo privado */ }
  };

  const { isOpen, closeWorkbench, artifacts, abertas, activeArtifactId, setActiveArtifact, fecharAba } = useWorkbenchStore();
  // As abas sao o que esta ABERTO agora; `artifacts` e a biblioteca inteira.
  const naTela = abertas
    .map(id => artifacts.find(item => item.id === id))
    .filter((item): item is NonNullable<typeof item> => Boolean(item));

  const activeArtifact = naTela.find(a => a.id === activeArtifactId) ?? naTela[0];

  if (!isOpen) return null;

  return (
    <aside className="fixed inset-y-0 right-0 z-50 flex animate-[sentury-workbench-in_220ms_ease-out] flex-col border-l border-zinc-200 bg-white text-zinc-800 shadow-[-18px_0_48px_rgba(35,31,24,0.18)]"
      style={{ width: `min(${largura}px, calc(100vw - 3.5rem))` }}>
      <ResizeHandle width={largura} onResize={setLargura} min={320} />
      {/* Header */}
      <div className="h-14 px-4 flex items-center justify-between border-b border-zinc-200 shrink-0 bg-zinc-50/70">
        <div className="flex items-center gap-2 font-semibold text-sm text-zinc-900">
          <Table className="w-4 h-4 text-gold-hover" />
          <span>Workbench</span>
          <span className="text-[10px] text-zinc-400 font-mono">({artifacts.length} artefatos)</span>
        </div>
        <div className="flex items-center gap-1">
          {activeArtifact && (activeArtifact.type === 'markdown' || activeArtifact.type === 'code') ? (
            <button
              onClick={() => abrirEmJanela(
                activeArtifact.title,
                activeArtifact.type === 'markdown'
                  ? renderMarkdown(activeArtifact.content)
                  : `<pre>${activeArtifact.code.replace(/[<&]/g, c => (c === '<' ? '&lt;' : '&amp;'))}</pre>`,
              )}
              className="rounded-md p-1 text-zinc-400 transition-colors hover:bg-zinc-200/60 hover:text-zinc-700"
              title="Abrir em outra janela"
            >
              <ExternalLink className="h-4 w-4" />
            </button>
          ) : null}
          <button
            onClick={closeWorkbench}
            className="p-1 rounded-md text-zinc-400 hover:text-zinc-700 hover:bg-zinc-200/60 transition-colors"
            title="Fechar Workbench"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Artifact Tabs (se houver mais de um) */}
      {artifacts.length > 1 && (
        <div className="flex overflow-x-auto border-b border-zinc-200 bg-zinc-100/60 px-2 py-1 gap-1">
          {naTela.map(art => (
            <span
              key={art.id}
              className={`group flex shrink-0 items-center gap-1 rounded pl-3 pr-1.5 py-1 text-xs font-medium transition-colors ${
                art.id === activeArtifactId
                  ? 'bg-white text-zinc-900 shadow-2xs border border-zinc-200'
                  : 'text-zinc-500 hover:text-zinc-800'
              }`}
            >
              <button
                type="button"
                onClick={() => setActiveArtifact(art.id)}
                title={art.title}
                className="max-w-[140px] truncate"
              >
                {art.title}
              </button>
              <button
                type="button"
                onClick={() => fecharAba(art.id)}
                aria-label={`Fechar ${art.title}`}
                title="Fechar a aba (o artefato continua em Artefatos)"
                className="rounded p-0.5 text-zinc-400 opacity-0 transition-opacity hover:bg-zinc-200 hover:text-zinc-800 focus-visible:opacity-100 group-hover:opacity-100"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Body / Active Artifact Renderer */}
      <div className="flex-1 overflow-y-auto p-4">
        {activeArtifact ? (
          activeArtifact.type === 'table' ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-wider">{activeArtifact.title}</h3>
                <button
                  onClick={() => {
                    const csv = [
                      activeArtifact.columns.map(c => c.label).join(','),
                      ...activeArtifact.rows.map(r => activeArtifact.columns.map(c => `"${r[c.key] || ''}"`).join(',')),
                    ].join('\n');
                    const blob = new Blob([csv], { type: 'text/csv' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `${activeArtifact.title.toLowerCase().replace(/\s+/g, '_')}.csv`;
                    a.click();
                  }}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium bg-zinc-100 hover:bg-zinc-200 text-zinc-700 transition-colors border border-zinc-200"
                  title="Exportar CSV"
                >
                  <Download className="w-3 h-3" />
                  <span>CSV</span>
                </button>
              </div>

              {/* Tabela Formatada com Severidade Semântica */}
              <div className="border border-zinc-200 rounded-lg overflow-hidden shadow-2xs">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-zinc-100/80 border-b border-zinc-200">
                      {activeArtifact.columns.map(col => (
                        <th key={col.key} className="p-2.5 font-semibold text-zinc-700 text-[11px]">
                          {col.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200">
                    {activeArtifact.rows.map(row => (
                      <tr key={row.id} className="hover:bg-zinc-50/80 transition-colors">
                        {activeArtifact.columns.map(col => (
                          <td key={col.key} className="p-2.5">
                            {col.type === 'severity' ? (
                              <SeverityCell value={row[col.key]} />
                            ) : (
                              <span className="text-zinc-700 font-medium">{row[col.key]}</span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

            </div>
          ) : activeArtifact.type === 'markdown' ? (
            <div
              className="bubble__md prose prose-sm max-w-none"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(activeArtifact.content) }}
            />
          ) : activeArtifact.type === 'code' ? (
            <pre className="sentury-scroll overflow-auto rounded-lg bg-zinc-950 p-4 text-[11px] leading-5 text-zinc-100">
              <code>{activeArtifact.code}</code>
            </pre>
          ) : activeArtifact.type === 'file' ? (
            <AttachmentRenderer key={activeArtifact.id} sessionId={activeArtifact.sessionId}
              rawAttachment={activeArtifact.attachment} />
          ) : activeArtifact.type === 'workflow' ? (
            // O que atravessa o turno mora aqui, nao no meio da conversa.
            <PlanoCard plano={activeArtifact.plano} sessionId={activeArtifact.sessionId} />
          ) : activeArtifact.type === 'trilha' ? (
            <div className="space-y-1.5">
              {/* A trilha e o caminho DESTE turno: o que rodou, em que ordem,
                  o que falhou. Morre com a resposta; o workflow nao. */}
              {activeArtifact.passos.map(passo => (
                <CommandCard key={passo.id} run={passo} defaultOpen={false} />
              ))}
            </div>
          ) : (
            <div className="text-xs text-zinc-500">Visualizador de artefato não suportado.</div>
          )
        ) : (
          <div className="text-xs text-zinc-400 text-center py-10">Nenhum artefato gerado ainda nesta sessão.</div>
        )}
      </div>
    </aside>
  );
};
