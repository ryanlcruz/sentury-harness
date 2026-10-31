export interface Anexo {
  nome: string;
  tipo: string;
  tamanho: number;
  dataUrl?: string;
}

export async function lerAnexos(arquivos: FileList | File[] | null) {
  let grandes = 0;
  const lidos = await Promise.all(Array.from(arquivos || []).slice(0, 6).map(arquivo => new Promise<Anexo | null>(resolve => {
    if (arquivo.size > 8 * 1024 * 1024) { grandes += 1; resolve(null); return; }
    const base: Anexo = { nome: arquivo.name || 'arquivo', tipo: arquivo.type || 'application/octet-stream', tamanho: arquivo.size };
    const leitor = new FileReader();
    leitor.onerror = () => resolve(base);
    leitor.onload = () => resolve({ ...base, dataUrl: String(leitor.result || '') });
    leitor.readAsDataURL(arquivo);
  })));
  return { lidos: lidos.filter((item): item is Anexo => Boolean(item)), grandes };
}
