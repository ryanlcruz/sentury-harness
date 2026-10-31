/* Abre um artefato numa janela propria. Sem arquivo persistido nao ha URL para
   abrir, e o botao ficava sem efeito nenhum: aqui o conteudo vira a janela. */

const ESTILO = `
  body { margin: 0; padding: 28px 32px; background: #f6f5f0; color: #26231d;
         font: 14px/1.65 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 62rem; margin: 0 auto; }
  pre { overflow: auto; background: #171613; color: #f3f1ea; padding: 14px 16px; border-radius: 8px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd6c6; padding: 6px 10px; text-align: left; }
  th { background: #efeade; }
  img, svg { max-width: 100%; }
  blockquote { border-left: 3px solid #d9b40a; margin: 1em 0; padding: .6em 1em; background: #fbf7e6; }
  input[type=checkbox] { margin-right: .5em; }
`;

export function abrirEmJanela(titulo: string, html: string): boolean {
  const doc = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>${titulo.replace(/[<&]/g, c => (c === '<' ? '&lt;' : '&amp;'))}</title>
<style>${ESTILO}</style></head><body><main>${html}</main></body></html>`;

  const janela = window.open('', '_blank', 'noopener,width=1100,height=860');
  if (!janela) return false;
  janela.document.write(doc);
  janela.document.close();
  return true;
}

export function abrirUrlEmJanela(url: string): boolean {
  return Boolean(window.open(url, '_blank', 'noopener,noreferrer'));
}
