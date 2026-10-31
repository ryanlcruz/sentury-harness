import { z } from 'zod';
import { authHeaders } from '../../runtime/config';
import { apiClient } from '../../transport/http-client';
import type { EstadoCoruja } from './Coruja';
import type { ChatMessage } from '../../contracts/domain/session';

const TarefaSchema = z.object({
  id: z.string(),
  agente: z.string(),
  pedido: z.string(),
  origem: z.string().default(''),
  estado: z.string(),
  resposta: z.string().default(''),
  motivo: z.string().default(''),
  pendente: z.string().default(''),
  pai: z.string().default(''),
  aguardando: z.array(z.string()).default([]),
  custo_usd: z.number().default(0),
  criada_em: z.number().default(0),
  terminada_em: z.number().default(0),
}).passthrough();

const AgenteSchema = z.object({
  nome: z.string(),
  papel: z.string(),
  objetivo: z.string(),
  personalidade: z.string().default(''),
  instrucoes: z.string().default(''),
  ferramentas: z.array(z.string()).default([]),
  skills: z.array(z.string()).default([]),
  canais: z.array(z.string()).default([]),
  estado: z.string(),
  orcamento: z.object({ usd_por_dia: z.number(), turnos_por_dia: z.number() }).partial().default({}),
  autonomia: z.object({ iniciativas_por_dia: z.number(), falas_por_assunto: z.number() }).partial().default({}),
  rede: z.enum(['nenhuma', 'internet']).default('nenhuma'),
  cerebro: z.object({ provedor: z.string(), modelo: z.string(), se_cair: z.string(), esforco: z.string() }).partial().default({}),
  aparencia: z.object({
    familia: z.string().default('geral'),
    plumagem: z.string().default(''),
    acessorios: z.record(z.string(), z.string()).default({}),
    sugeridos: z.record(z.string(), z.string()).default({}),
  }).default({ familia: 'geral', plumagem: '', acessorios: {}, sugeridos: {} }),
  cores: z.object({ penas: z.string(), asas: z.string(), barriga: z.string(), olho: z.string() }).partial().default({}),
  uso_de_hoje: z.object({ usd: z.number(), turnos: z.number(), turnos_sem_custo: z.number().default(0) })
    .default({ usd: 0, turnos: 0, turnos_sem_custo: 0 }),
  corte: z.string().nullable().optional(),
  tarefas_abertas: z.number().default(0),
  previa: z.string().default(''),
  criado_em: z.number().default(0),
  memoria: z.string().optional(),
  tarefas: z.array(TarefaSchema).optional(),
}).passthrough();

const CatalogoSchema = z.object({
  familias: z.record(z.string(), z.object({ nome: z.string(), simbolo: z.record(z.string(), z.string()) })),
  plumagens: z.record(z.string(), z.object({ nome: z.string(), penas: z.string(), asas: z.string(), barriga: z.string(), olho: z.string().optional() })),
  encaixes: z.record(z.string(), z.array(z.string())),
});

/** Um acontecimento numa tarefa, como o feed do Escritório mostra. */
const EventoSchema = z.object({
  em: z.number(),
  tipo: z.string(),
  agente: z.string(),
  tarefa: z.string(),
  pedido: z.string().default(''),
  origem: z.string().default(''),
  motivo: z.string().default(''),
  pendente: z.string().default(''),
  /** Na espera por colegas: os nomes deles. */
  aguardando: z.array(z.string()).default([]),
  /** Na liberação: "colegas" quando quem respondeu foram outros residentes. */
  por: z.string().default(''),
  negado: z.string().default(''),
  /** Eventos da Mesa: o assunto, quem falou com quem e o que disse. */
  assunto: z.string().default(''),
  para: z.string().default(''),
  texto: z.string().default(''),
  participantes: z.array(z.string()).default([]),
  /** O residente começou sozinho, sem pedido da pessoa. */
  iniciativa: z.boolean().default(false),
}).passthrough();

export type Tarefa = z.infer<typeof TarefaSchema>;
export type Evento = z.infer<typeof EventoSchema>;
export type Agente = z.infer<typeof AgenteSchema>;
export type Catalogo = z.infer<typeof CatalogoSchema>;

const AssuntoSchema = z.object({
  id: z.string(), titulo: z.string(), texto: z.string(), aberto_por: z.string(),
  estado: z.enum(['aberto', 'fechado']), resumo: z.string(), motivo: z.string(),
  criado_em: z.number(), atualizado_em: z.number(), participantes: z.array(z.string()),
  passaram: z.array(z.string()),
  // Consultados na abertura que decidiram não entrar; um @ depois os traz.
  ficaram_de_fora: z.array(z.string()).default([]),
  falas: z.array(z.object({ de: z.string(), para: z.string(), texto: z.string(), em: z.number() })),
  fechando: z.boolean().default(false),
  // Quem está com a vez: `na_fila` ainda não pegou, `rodando` já está escrevendo desde `desde`,
  // `esperando` parou pedindo autorização; `tarefa` liga a vez ao cartão que a pessoa responde.
  vez: z.array(z.object({
    agente: z.string(), estado: z.string(), papel: z.string().default('falando'), desde: z.number().optional(),
    tarefa: z.string().optional(),
  })).default([]),
  // O que saiu do assunto: tarefas pedidas aos colegas durante as vezes dele.
  custo: z.object({ vezes: z.number(), usd: z.number() }).default({ vezes: 0, usd: 0 }),
  encaminhadas: z.array(z.object({
    id: z.string(), agente: z.string(), pedido: z.string(), estado: z.string(), resposta: z.string().default(''),
  })).default([]),
});
export type Assunto = z.infer<typeof AssuntoSchema>;

const base = '/sentury/residentes';
const opcoes = () => ({ headers: authHeaders() });

const RotinaSchema = z.object({
  id: z.string(), prompt: z.string(), active: z.boolean(), rotulo: z.string(),
  kind: z.string(), proxima_execucao: z.string().nullable(), bloqueio: z.string(),
  fuso: z.string(), motivo: z.string().optional(),
});
export type Rotina = z.infer<typeof RotinaSchema>;
export type NovaRotina = { pedido: string; cron_expr?: string; interval_sec?: number; run_at?: string };

const DecisaoSchema = z.object({
  titulo: z.string(), resumo: z.string(), participantes: z.array(z.string()), em: z.number(),
  origem: z.string(), caminho: z.string(),
});
export type Decisao = z.infer<typeof DecisaoSchema>;

const BlocoDeContextoSchema = z.object({ titulo: z.string(), texto: z.string() });
export type BlocoDeContexto = z.infer<typeof BlocoDeContextoSchema>;

export const residentes = {
  async contexto(nome: string): Promise<BlocoDeContexto[]> {
    const dados = await apiClient.get<{ blocos: unknown[] }>(`${base}/${encodeURIComponent(nome)}/contexto`, opcoes());
    return z.array(BlocoDeContextoSchema).parse(dados.blocos);
  },
  async decisoes(): Promise<Decisao[]> {
    const dados = await apiClient.get<{ decisoes: unknown[] }>(`${base}/_decisoes`, opcoes());
    return z.array(DecisaoSchema).parse(dados.decisoes);
  },
  async assuntos(): Promise<Assunto[]> {
    const dados = await apiClient.get<{ assuntos: unknown[] }>(`${base}/_mesa`, opcoes());
    return z.array(AssuntoSchema).parse(dados.assuntos);
  },
  async assunto(id: string): Promise<Assunto> {
    return AssuntoSchema.parse(await apiClient.get(`${base}/_mesa/${encodeURIComponent(id)}`, opcoes()));
  },
  async abrirAssunto(titulo: string, texto: string): Promise<Assunto> {
    return AssuntoSchema.parse(await apiClient.post(`${base}/_mesa`, { titulo, texto }, opcoes()));
  },
  async falarNoAssunto(id: string, texto: string): Promise<Assunto> {
    return AssuntoSchema.parse(await apiClient.post(`${base}/_mesa/${encodeURIComponent(id)}/falar`, { texto }, opcoes()));
  },
  async apagarAssunto(id: string): Promise<void> {
    await apiClient.delete(`${base}/_mesa/${encodeURIComponent(id)}`, opcoes());
  },
  async fecharAssunto(id: string, resumo: string): Promise<Assunto> {
    return AssuntoSchema.parse(await apiClient.post(`${base}/_mesa/${encodeURIComponent(id)}/fechar`, { resumo }, opcoes()));
  },
  async conversa(nome: string): Promise<{ agente: Agente; mensagens: (ChatMessage & { pedido_original?: string })[]; esperando: Tarefa[]; trabalhando?: boolean }> {
    const dados = await apiClient.get<{ agente: unknown; mensagens: (ChatMessage & { pedido_original?: string })[]; esperando: unknown[]; trabalhando?: boolean }>(
      `${base}/${encodeURIComponent(nome)}/conversa`, opcoes());
    const mensagens = dados.mensagens.map(mensagem => {
      const data = mensagem.timestamp ? new Date(mensagem.timestamp) : null;
      return { ...mensagem, timestamp: data && !Number.isNaN(data.getTime())
        ? data.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '' };
    });
    return { agente: AgenteSchema.parse(dados.agente), mensagens,
      esperando: z.array(TarefaSchema).parse(dados.esperando), trabalhando: Boolean(dados.trabalhando) };
  },
  async pedirNaConversa(nome: string, pedido: string, userId: string, arquivos: { nome: string; data_url: string }[] = []): Promise<Tarefa> {
    return TarefaSchema.parse(await apiClient.post(`${base}/${encodeURIComponent(nome)}/conversa`,
      { pedido, user_id: userId, arquivos }, opcoes()));
  },
  async rotinas(nome: string): Promise<Rotina[]> {
    const dados = await apiClient.get<{ rotinas: unknown[] }>(`${base}/${encodeURIComponent(nome)}/rotinas`, opcoes());
    return z.array(RotinaSchema).parse(dados.rotinas);
  },
  async criarRotina(nome: string, campos: NovaRotina): Promise<Rotina> {
    return RotinaSchema.parse(await apiClient.post(`${base}/${encodeURIComponent(nome)}/rotinas`, campos, opcoes()));
  },
  async mudarRotina(nome: string, id: string, ativa: boolean): Promise<Rotina> {
    return RotinaSchema.parse(await apiClient.patch(`${base}/${encodeURIComponent(nome)}/rotinas/${id}`, { ativa }, opcoes()));
  },
  async apagarRotina(nome: string, id: string): Promise<void> {
    await apiClient.delete(`${base}/${encodeURIComponent(nome)}/rotinas/${id}`, opcoes());
  },
  async listar(): Promise<{ agentes: Agente[]; hq: string }> {
    const dados = await apiClient.get<{ agentes: unknown[]; hq: string }>(base, opcoes());
    return { agentes: z.array(AgenteSchema).parse(dados.agentes || []), hq: dados.hq || 'local' };
  },
  async ver(nome: string): Promise<Agente> {
    return AgenteSchema.parse(await apiClient.get(`${base}/${nome}`, opcoes()));
  },
  async catalogo(): Promise<Catalogo> {
    return CatalogoSchema.parse(await apiClient.get(`${base}/_aparencia`, opcoes()));
  },
  /** A coruja que vai nascer com este nome e esta família. */
  async previa(nome: string, familia: string): Promise<{ aparencia: { familia: string; plumagem: string; acessorios: Record<string, string> }; cores: { penas: string; asas: string; barriga: string; olho?: string } }> {
    const consulta = new URLSearchParams({ nome, familia });
    return apiClient.get(`${base}/_previa?${consulta.toString()}`, opcoes());
  },
  /** O que aconteceu nas tarefas depois de `desde` (relógio da HQ), do mais novo ao mais antigo. */
  async eventos(desde = 0, limite = 60): Promise<Evento[]> {
    const dados = await apiClient.get<{ eventos: unknown[] }>(`${base}/_eventos?desde=${desde}&limite=${limite}`, opcoes());
    return z.array(EventoSchema).parse(dados.eventos || []);
  },
  async esperando(): Promise<Tarefa[]> {
    const dados = await apiClient.get<{ tarefas: unknown[] }>(`${base}/_esperando`, opcoes());
    return z.array(TarefaSchema).parse(dados.tarefas || []);
  },
  async pedir(nome: string, pedido: string): Promise<Tarefa> {
    return TarefaSchema.parse(await apiClient.post(`${base}/${nome}/tarefas`, { pedido }, opcoes()));
  },
  async responder(tarefaId: string, resposta: 'uma_vez' | 'negar' | '', retorno = ''): Promise<Tarefa> {
    return TarefaSchema.parse(await apiClient.post(`${base}/_tarefas/${tarefaId}/responder`, { resposta, retorno }, opcoes()));
  },
  async mudar(nome: string, acao: 'pausar' | 'retomar' | 'aposentar'): Promise<Agente> {
    return AgenteSchema.parse(await apiClient.post(`${base}/${nome}/${acao}`, {}, opcoes()));
  },
  async trocarAcessorios(nome: string, acessorios: Record<string, string>): Promise<Agente> {
    return AgenteSchema.parse(await apiClient.put(`${base}/${nome}/acessorios`, { acessorios }, opcoes()));
  },
};

const PEDIDO_DE_FERRAMENTA = 'ferramenta_nova ';

/** "ferramenta_nova escrever_arquivo" vira "escrever_arquivo"; outro comando vira "". */
export function ferramentaPedida(pendente: string): string {
  return pendente.startsWith(PEDIDO_DE_FERRAMENTA) ? pendente.slice(PEDIDO_DE_FERRAMENTA.length).trim() : '';
}

/** "agente:atlas" vira "Atlas"; outra origem vira "". */
export function colegaDaOrigem(origem: string): string {
  return origem.startsWith('agente:') ? nomeVisivel(origem.slice('agente:'.length)) : '';
}

export function nomeVisivel(nome: string): string {
  return nome.charAt(0).toUpperCase() + nome.slice(1);
}

/** O estado que a coruja mostra: tarefa esperando a pessoa vence o resto. */
export function estadoDaCoruja(agente: Agente, esperando: Tarefa[]): EstadoCoruja {
  if (agente.estado === 'pausado' || agente.corte) return 'pausado';
  if (esperando.some(t => t.agente === agente.nome)) return 'esperando';
  if (agente.estado === 'trabalhando') return 'trabalhando';
  return 'dormindo';
}

export const NOME_DO_ESTADO: Record<EstadoCoruja, string> = {
  parado: 'Disponível',
  dormindo: 'Dormindo',
  trabalhando: 'Trabalhando',
  esperando: 'Esperando você',
  pausado: 'Pausado',
};

export const PECAS: Record<string, string> = {
  capacete: 'Capacete', gorro: 'Gorro', bone: 'Boné', chapeu: 'Chapéu',
  oculos: 'Óculos', escuros: 'Óculos escuros', monoculo: 'Monóculo',
  fone: 'Fone',
  gravata: 'Gravata', borboleta: 'Gravata-borboleta', cachecol: 'Cachecol', cracha: 'Crachá',
  chave: 'Chave inglesa', lupa: 'Lupa', prancheta: 'Prancheta', notebook: 'Notebook', caneca: 'Caneca', escudo: 'Escudo',
};

export const ENCAIXES: Record<string, string> = {
  cabeca: 'Cabeça', rosto: 'Rosto', ouvidos: 'Ouvidos', pescoco: 'Pescoço', asa: 'Na asa',
};

const ProvedorSchema = z.object({
  key: z.string(),
  label: z.string().optional(),
  name: z.string().optional(),
  models: z.array(z.string()).default([]),
  configured: z.boolean().optional(),
}).passthrough();

export type Provedor = z.infer<typeof ProvedorSchema>;

export const cerebros = {
  /** Os provedores do RobinBandit, com os modelos de cada um. */
  async provedores(): Promise<Provedor[]> {
    const dados = await apiClient.get<{ providers?: unknown[] }>('/sentury/providers', opcoes());
    return z.array(ProvedorSchema).parse(dados.providers || []);
  },
};

export const edicao = {
  async editar(nome: string, campos: Record<string, unknown>): Promise<Agente> {
    return AgenteSchema.parse(await apiClient.patch(`${base}/${nome}`, campos, opcoes()));
  },
  /** Ajusta o residente proposto na conversa antes do "Criar". */
  async ajustarProposta(sessionId: string, userId: string, argumentos: Record<string, unknown>): Promise<void> {
    await apiClient.put(`${base}/_proposta`, { session_id: sessionId, user_id: userId, argumentos }, opcoes());
  },
};
