/* Funções nativas chamadas por `@`.

   Dois tipos, um mecanismo:
   - intenção (`@plano`, `@workflow`, `@goal`, `@image`): vale só para a
     mensagem em que foi escrita e fica citada nela, como a skill. Manter ligada
     depois deixaria um selo aceso que o modelo já não usa.
   - acesso (`@computador`, `@navegador`): põe a ferramenta à disposição e fica
     ligado na conversa até ser desligado. Sumir na mensagem seguinte tiraria a
     tela do agente no meio da tarefa.
   Nenhum dos dois força o modelo: intenção é orientação, acesso é disponibilidade. */

export type TipoDeFuncao = 'intencao' | 'acesso';

export interface FuncaoNativa {
  id: string;
  rotulo: string;
  descricao: string;
  resumo: string;
  tipo: TipoDeFuncao;
  /** Como o acesso aparece na faixa da conversa enquanto está ligado. */
  ligado?: string;
}

export const FUNCOES_NATIVAS: FuncaoNativa[] = [
  {
    id: 'plano',
    rotulo: 'plano',
    tipo: 'intencao',
    resumo: 'Mostra o caminho antes de executar.',
    descricao: 'Mostra o caminho antes de executar, e espera seu ok.',
  },
  {
    id: 'workflow',
    rotulo: 'workflow',
    tipo: 'intencao',
    resumo: 'Processo que se repete ou retoma.',
    descricao: 'Conduz até fechar: divide em fases, marca o que terminou e retoma depois.',
  },
  {
    id: 'goal',
    rotulo: 'goal',
    tipo: 'intencao',
    resumo: 'Objetivo perseguido entre turnos.',
    descricao: 'Um objetivo que a Sentury persegue até cumprir. Ela propõe, você aprova no cartão.',
  },
  {
    id: 'image',
    rotulo: 'image',
    tipo: 'intencao',
    resumo: 'Gera uma imagem.',
    descricao: 'Permite desenhar imagens. Sem isto, pedido de "visual" é gráfico de dados.',
  },
  {
    id: 'computador',
    rotulo: 'computador',
    tipo: 'acesso',
    ligado: 'Tela liberada nesta conversa',
    resumo: 'Libera a tela até você desligar.',
    descricao: 'A Sentury vê a tela e usa seu mouse e teclado quando o pedido precisar, sem pedir a cada gesto. Digitar dado pessoal pede confirmação; Ctrl+Alt+Shift+S para tudo.',
  },
  {
    id: 'navegador',
    rotulo: 'navegador',
    tipo: 'acesso',
    ligado: 'Navegador liberado nesta conversa',
    resumo: 'Libera as abas até você desligar.',
    descricao: 'A Sentury abre e opera páginas no navegador. Ações que enviam dados ou falam em seu nome pedem aprovação.',
  },
];

export const funcaoPorId = (id: string) => FUNCOES_NATIVAS.find(item => item.id === id.toLowerCase());

/** As funções citadas no texto como `@id`, na ordem em que aparecem. */
export function funcoesCitadas(texto: string): FuncaoNativa[] {
  const vistas = new Set<string>();
  const citadas: FuncaoNativa[] = [];
  for (const achado of (texto || '').matchAll(/(?:^|\s)@([a-z][a-z0-9-]*)(?=\s|$|[.,;:!?])/gi)) {
    const funcao = funcaoPorId(achado[1]);
    if (funcao && !vistas.has(funcao.id)) {
      vistas.add(funcao.id);
      citadas.push(funcao);
    }
  }
  return citadas;
}

const PREFIXO = 'sentury_acessos:';

// A ativação antiga ficava no navegador e passava de uma conversa para outra.
try { window.localStorage.removeItem('sentury_funcoes_ativas'); } catch { /* sem storage */ }

/** Os acessos ligados nesta conversa. */
export function lerAcessos(sessionId: string | null | undefined): string[] {
  if (!sessionId) return [];
  try {
    const bruto = JSON.parse(window.localStorage.getItem(PREFIXO + sessionId) || '[]') as unknown;
    if (!Array.isArray(bruto)) return [];
    return bruto.filter((id): id is string => typeof id === 'string' && funcaoPorId(id)?.tipo === 'acesso');
  } catch {
    return [];
  }
}

export function salvarAcessos(sessionId: string, ids: string[]): void {
  try {
    if (ids.length) window.localStorage.setItem(PREFIXO + sessionId, JSON.stringify(ids));
    else window.localStorage.removeItem(PREFIXO + sessionId);
  } catch {
    // Sem storage o acesso vale só enquanto a aba estiver aberta.
  }
}

/** O que vai junto de uma mensagem: os acessos da conversa e o que o texto cita.
 *  Acesso citado passa a ficar ligado na conversa. */
export function funcoesDoEnvio(sessionId: string, texto: string): string[] {
  const citadas = funcoesCitadas(texto);
  const acessos = lerAcessos(sessionId);
  const novos = citadas.filter(f => f.tipo === 'acesso' && !acessos.includes(f.id)).map(f => f.id);
  if (novos.length) salvarAcessos(sessionId, [...acessos, ...novos]);
  return [...new Set([...acessos, ...novos, ...citadas.map(f => f.id)])];
}
