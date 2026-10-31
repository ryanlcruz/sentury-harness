import type { TableArtifact } from '../contracts/domain/artifact';

/**
 * Uma tabela da conversa vira artefato quando a pessoa pede, pelo botão
 * "Abrir no painel" que cada tabela traz. Adivinhar pelo texto do pedido
 * ("tabela", "crie um relatório") só reconhece português escrito certinho.
 */
export function tabelaParaArtefato(tabela: HTMLTableElement, sessionId: string, id: string): TableArtifact {
  const cabecalho = Array.from(tabela.querySelectorAll('thead th'));
  const linhas = Array.from(tabela.querySelectorAll('tbody tr'));
  const columns = cabecalho.map((th, indice) => ({
    key: `col_${indice}`,
    label: th.textContent?.trim() || `Coluna ${indice + 1}`,
    type: 'string' as const,
  }));
  const rows = linhas.map((tr, indiceDaLinha) => {
    const celulas = Array.from(tr.querySelectorAll('td'));
    const linha: Record<string, string> = { id: `row_${indiceDaLinha}` };
    columns.forEach((coluna, indice) => { linha[coluna.key] = celulas[indice]?.textContent?.trim() ?? ''; });
    return linha;
  });
  return {
    id,
    type: 'table',
    title: columns[0]?.label ? `Tabela: ${columns[0].label}` : 'Tabela',
    sessionId,
    createdAt: new Date().toISOString(),
    columns,
    rows,
  };
}
