// A lib passa de meio megabyte, entao so e importada quando um diagrama
// aparece de verdade.

let carregando: Promise<typeof import('mermaid').default> | null = null;

function carregar(): Promise<typeof import('mermaid').default> {
  if (!carregando) {
    carregando = import('mermaid').then(mod => {
      const mermaid = mod.default;
      mermaid.initialize({
        startOnLoad: false,
        // O diagrama vem do modelo: conteudo de terceiro.
        securityLevel: 'strict',
        theme: 'base',
        fontFamily: "'Geist Variable', sans-serif",
        themeVariables: {
          background: '#fffdf8',
          primaryColor: '#fff4b8',
          primaryTextColor: '#1a1a1a',
          primaryBorderColor: '#c99f00',
          lineColor: '#8a8172',
          secondaryColor: '#ece7da',
          tertiaryColor: '#f6f5f0',
        },
      });
      return mermaid;
    });
  }
  return carregando;
}

// Diagrama invalido vira aviso no lugar do bloco: o modelo erra a sintaxe e
// isso nao pode custar o turno.
export async function renderizarDiagramas(raiz: ParentNode): Promise<void> {
  const nos = Array.from(raiz.querySelectorAll<HTMLElement>('pre.mermaid:not([data-pronto])'));
  if (!nos.length) return;

  const mermaid = await carregar();
  for (const no of nos) {
    no.dataset.pronto = '1';
    const fonte = no.textContent || '';
    try {
      const id = `mmd-${Math.random().toString(36).slice(2, 10)}`;
      const { svg } = await mermaid.render(id, fonte);
      no.outerHTML = `<div class="mermaid-svg">${svg}</div>`;
    } catch (erro) {
      console.warn('[mermaid] diagrama inválido:', erro);
      no.classList.add('mermaid--invalido');
      no.title = 'Diagrama com sintaxe inválida';
    }
  }
}
