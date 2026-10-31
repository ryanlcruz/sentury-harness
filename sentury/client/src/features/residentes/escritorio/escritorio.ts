/** O motor do Escritório: monta a sala em SVG, põe cada residente numa mesa,
 * faz andar, falar e mostrar o estado, quadro a quadro.
 *
 * Não inventa trabalho: só se mexe com o que a tela manda (`sincronizar`,
 * `pedidoChegou`, `falar`, `painel`), que vem da HQ. O que roda sozinho é o
 * jeito de estar vivo: respirar, piscar, olhar para o lado e, para quem está
 * livre, dar uma volta pela sala (café na copa, cochilo no sofá, um banquinho
 * na mesa redonda, espiar um colega que trabalha). Ninguém fala nessas voltas:
 * balão só sai de evento da HQ. Chegou tarefa, a volta acaba na hora.
 */
import { S, esc, iso } from './iso';
import {
  MESA, MESINHA, ASSENTOS, RACK, banquinho, caixaDePedidos, cenarioEstatico, copa, defsDaCena, lixeira, luminaria,
  mesaRedonda, mesinhaDeCentro, rackDoRouter, vaso, type LuzDoRack, type AssentoDaMesa,
} from './cenario';
import { criar3D, type CoresDaCoruja, type CorujaAnimada, type Motor3D, type PoseDaCoruja } from './coruja3d';
import { ESTILO_DO_ESCRITORIO } from './estilo';
import { QUADRO_DA_SALA } from './projecao3d';
import { FOLGA, rota } from './caminhos';

const NS = 'http://www.w3.org/2000/svg';

export interface ResidenteNaCena {
  nome: string;
  rotulo: string;
  familia: string;
  cores: CoresDaCoruja;
  acessorios: Record<string, string>;
  pose: PoseDaCoruja;
}

export interface PainelDoDia {
  feitas: number;
  fila: number;
  esperando: number;
  usd: number;
  turnos: number;
}

type Olhar = number | 'mesa';
/** `via`: pontos de passagem, para chegar ao sofá pela frente e não por cima do braço. */
interface Posto { x: number; y: number; z: number; olhar: Olhar; via?: { x: number; y: number }[] }

const CAMERA = Math.PI / 4;
const PASSAGEM_DO_SOFA = { x: 2.01, y: 6.95 };
/** Os cantos da sala aonde quem está livre vai dar uma volta. */
const CANTOS: Record<string, Posto> = {
  sofaA: { x: 0.85, y: 7.0, z: 0.48, olhar: Math.PI / 2, via: [PASSAGEM_DO_SOFA] },
  sofaB: { x: 0.85, y: 8.55, z: 0.48, olhar: Math.PI / 2, via: [PASSAGEM_DO_SOFA, { x: 2.01, y: 8.55 }] },
  cafe: { x: 10.05, y: 5.6, z: 0, olhar: Math.PI / 2 },
};
const LUGARES_DO_SOFA = ['sofaA', 'sofaB'] as const;
/** Quanto tempo o nome de cada um fica à vista quando a sala abre ou alguém chega. */
const NOME_NA_ABERTURA_MS = 4500;
const LIVRE = new Set<PoseDaCoruja>(['dormindo', 'parado']);
type Volta = 'cafe' | 'sofa' | 'mesa' | 'visita' | 'cochilo';
type AcaoDaCoruja = (vigente: () => boolean) => Promise<void>;
const VOLTAS: Volta[] = ['cafe', 'sofa', 'mesa', 'visita', 'cochilo'];
const POSTOS: Record<string, Posto> = {
  mesaParede: { x: 1.75, y: 3.25, z: 0, olhar: 0 },
  pesquisaA: { x: 2.35, y: 1.95, z: 0, olhar: Math.PI / 2 },
  pesquisaB: { x: 3.75, y: 1.95, z: 0, olhar: Math.PI / 2 },
  memoria: { x: 6.75, y: 1.7, z: 0, olhar: Math.PI / 2 },
  portal: { x: 10.4, y: 1.9, z: 0, olhar: Math.PI / 2 },
  ...Object.fromEntries(ASSENTOS.map(p => [p.nome, { x: p.x, y: p.y, z: 0.45, olhar: 'mesa' as const }])),
  caixa: { x: 1.75, y: 5.25, z: 0, olhar: -0.35 },
  ...CANTOS,
};
/** Onde cada família prefere sentar; quem sobra vai para a mesa redonda. */
const PREFERE: Record<string, string[]> = {
  pesquisa: ['pesquisaA', 'pesquisaB'],
  conteudo: ['pesquisaB', 'pesquisaA'],
  codigo: ['portal'],
  infraestrutura: ['portal'],
  seguranca: ['portal'],
  dados: ['memoria'],
  financas: ['memoria'],
  atendimento: ['mesaParede'],
};
const ORDEM_DOS_POSTOS = ['mesaParede', 'pesquisaA', 'pesquisaB', 'memoria', 'portal', 'lugarO', 'lugarN', 'lugarL', 'lugarS'];
export const MAXIMO_NA_SALA = ORDEM_DOS_POSTOS.length;

const K = 0.6; // escala da coruja plana na cena
const VEL_ANDAR = 1.75; // unidades por segundo

interface Coruja extends CorujaAnimada {
  r: ResidenteNaCena;
  /** O estado que a HQ deu. `pose` é o que a cena mostra: livre e acordado na volta, de olho fechado no cochilo. */
  real: PoseDaCoruja;
  cochilando: boolean;
  assinatura: string;
  x: number; y: number; z: number; alvoZ: number;
  posto: string;
  postoAtual: string;
  olhar: Olhar;
  caminho: { x: number; y: number }[];
  aoChegar: (() => void) | null;
  cancelarCaminho: (() => void) | null;
  fila: Promise<unknown>;
  revisao: number;
  ocupado: number;
  /** O canto reservado durante uma volta. */
  fora: string | null;
  /** O lugar na mesa redonda enquanto participa de um assunto da Mesa. */
  naMesa: string | null;
  baralho: Volta[];
  /** Encerra a pausa da volta antes da hora (chegou tarefa). */
  acordar: (() => void) | null;
  /** A HQ chamou no meio da volta: o que falta dela não acontece. */
  chamada: boolean;
  olhando: Coruja | null;
  el: SVGGElement;
  ginga: SVGGElement;
  sinal: SVGGElement;
  etiqueta: SVGGElement;
  larguraEtiqueta: number;
  etiquetaVisivel: boolean;
  /** O nome aparece com o mouse ou o foco em cima, e por um tempo ao chegar. */
  sobMouse: boolean;
  nomeAte: number;
  /** O último `translate` escrito, para não repetir. */
  lugar: string;
  balao: SVGGElement | null;
  balaoLarg: number;
  balaoAlt: number;
  /** O último desenho do balão, para não reescrever o mesmo. */
  balaoEscrito: string;
  ledAceso: boolean | null;
  assinaturaDoSinal: string;
  remover: () => void;
}


const mistura = (a: number, b: number, t: number) => { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return a + d * t; };
const espera = (ms: number) => new Promise<void>(resolve => window.setTimeout(resolve, ms));

/** A fala do balão em até `maximo` linhas de `largura` caracteres, quebrando
 * entre palavras; o que sobra vira reticências na última linha. */
export function linhasDoBalao(texto: string, largura = 46, maximo = 3): string[] {
  const linhas: string[] = [];
  let atual = '';
  for (const palavra of texto.replace(/\s+/g, ' ').trim().split(' ')) {
    const junto = atual ? `${atual} ${palavra}` : palavra;
    if (junto.length <= largura) { atual = junto; continue; }
    if (atual) linhas.push(atual);
    atual = palavra.length > largura ? `${palavra.slice(0, largura - 1)}…` : palavra;
    if (linhas.length === maximo) break;
  }
  if (atual && linhas.length < maximo) linhas.push(atual);
  const usadas = linhas.join(' ').length;
  if (usadas < texto.replace(/\s+/g, ' ').trim().length && linhas.length) {
    const ultima = linhas[linhas.length - 1];
    linhas[linhas.length - 1] = `${ultima.length >= largura ? ultima.slice(0, largura - 1).trimEnd() : ultima}…`;
  }
  return linhas.length ? linhas : [''];
}

/** O que aparece por cima da coruja: z de quem dorme, ! de quem espera, brilho de quem trabalha. */
function sinalDaPose(pose: PoseDaCoruja, cor: string) {
  if (pose === 'dormindo') {
    return [[96, 32, 15, ''], [104, 22, 12, ' esc-z2'], [110, 13, 10, ' esc-z3']].map(([x, y, t, c]) =>
      `<text class="esc-z${c}" x="${x}" y="${y}" font-size="${t}" font-weight="700" fill="#cfc8ea" font-family="Geist, sans-serif">z</text>`).join('');
  }
  if (pose === 'esperando') {
    return `<g class="esc-exclama"><circle cx="104" cy="14" r="12" fill="#f5c400"/><path d="M96 22 L93 30 L102 25 Z" fill="#f5c400"/>
      <rect x="102.5" y="6" width="3" height="10" rx="1.5" fill="#1a1a1a"/><circle cx="104" cy="20" r="1.8" fill="#1a1a1a"/></g>`;
  }
  if (pose === 'trabalhando') {
    return `<path class="esc-brilho" d="M104 22 l2 5 l5 2 l-5 2 l-2 5 l-2 -5 l-5 -2 l5 -2 Z" fill="${cor}"/>
      <path class="esc-brilho esc-b2" d="M14 26 l1.5 3.5 l3.5 1.5 l-3.5 1.5 l-1.5 3.5 l-1.5 -3.5 l-3.5 -1.5 l3.5 -1.5 Z" fill="${cor}"/>`;
  }
  return '';
}

/** A coruja plana, para quando o navegador não tem WebGL. */
function corujaPlana(c: CoresDaCoruja) {
  const olho = (cx: number) => `<circle cx="${cx}" cy="54" r="9" fill="#141218"/><circle cx="${cx}" cy="54" r="6" fill="${c.olho}"/>
    <circle cx="${cx}" cy="54" r="3" fill="#07060a"/><circle cx="${cx + 2.6}" cy="51" r="2" fill="#fff"/>`;
  return `<ellipse cx="51" cy="108" rx="6" ry="3" fill="#f2b705"/><ellipse cx="69" cy="108" rx="6" ry="3" fill="#f2b705"/>
    <path d="M30 44 L24 17 L46 33 Z" fill="${c.asas}"/><path d="M90 44 L96 17 L74 33 Z" fill="${c.asas}"/>
    <ellipse cx="60" cy="70" rx="36" ry="40" fill="${c.penas}"/><ellipse cx="60" cy="90" rx="21" ry="17" fill="${c.barriga}"/>
    <ellipse cx="26" cy="80" rx="9" ry="20" fill="${c.asas}"/><ellipse cx="94" cy="80" rx="9" ry="20" fill="${c.asas}"/>
    <circle cx="45" cy="54" r="17" fill="#f3eee4"/><circle cx="75" cy="54" r="17" fill="#f3eee4"/>
    <ellipse cx="60" cy="63" rx="11" ry="9" fill="#f3eee4"/>${olho(45)}${olho(75)}
    <path d="M60 60 L65.5 67 L60 75 L54.5 67 Z" fill="#f2b705" stroke="#3b2a00" stroke-width="1.2" stroke-linejoin="round"/>`;
}

/** `esperado` é o intervalo do ritmo em que o quadro foi pedido: 30 quadros/s em movimento, 8 parada. */
export interface MedicaoDaSala { ms: number; intervalo: number; esperado?: number; chamadas: number; triangulos: number }

export class Escritorio {
  private readonly host: HTMLElement;
  private readonly svg: SVGSVGElement;
  private readonly moveis: SVGGElement;
  private readonly dinamico: SVGGElement;
  private readonly frente: SVGGElement;
  private readonly sobreposto: SVGGElement;
  private readonly tres: Motor3D | null;
  private readonly aoSelecionar: (nome: string | null) => void;
  private readonly aoQuadro?: (medicao: MedicaoDaSala) => void;
  private readonly aoAtividade?: (ativa: boolean) => void;
  private readonly aoPreparacao?: (faltam: number) => void;
  private readonly progressivo: boolean;
  private readonly porMontar = new Set<Coruja>();
  private preparando = false;
  private readonly reduzir: boolean;
  private readonly corujas = new Map<string, Coruja>();
  private readonly objetos: { el: SVGGElement; prof: () => number }[] = [];
  private assentos: AssentoDaMesa[] = [];
  private readonly cadeiras = new Map<string, { el: SVGGElement; prof: () => number }>();
  private rack: { el: SVGGElement; prof: () => number } | null = null;
  private assinaturaDoRack = '';
  private selecionado: string | null = null;
  private pedidosNaCaixa = 0;
  private readonly reservados = new Map<string, Coruja>();
  private escNome = 1;
  private escBalao = 1;
  private ultimo = performance.now();
  private animarAte = 0;
  private quadroId = 0;
  private relogioId = 0;
  private olharId = 0;
  private piscarId = 0;
  private voltaId = 0;
  private vivo = true;
  private readonly aoRedimensionar = () => this.medirTela();
  private readonly aoMudarVisibilidade = () => this.atualizarAtividade();
  private readonly aoClicarNaSala = (e: Event) => {
    if (!(e.target as Element).closest('.esc-coruja')) this.aoSelecionar(null);
  };
  private naTela = true;
  /** O laço e os temporizadores só rodam com a sala à vista e a aba do navegador em frente. */
  private rodando = false;
  private vigia: IntersectionObserver | null = null;
  private tamanho: ResizeObserver | null = null;

  constructor(host: HTMLElement, opcoes: {
    aoSelecionar: (nome: string | null) => void;
    aoQuadro?: (medicao: MedicaoDaSala) => void;
    aoAtividade?: (ativa: boolean) => void;
    aoPreparacao?: (faltam: number) => void;
    progressivo?: boolean;
  }) {
    this.host = host;
    this.aoSelecionar = opcoes.aoSelecionar;
    this.aoQuadro = opcoes.aoQuadro;
    this.aoAtividade = opcoes.aoAtividade;
    this.aoPreparacao = opcoes.aoPreparacao;
    this.progressivo = !!opcoes.progressivo;
    this.reduzir = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    host.classList.add('esc-raiz');
    const estilo = document.createElement('style');
    estilo.textContent = ESTILO_DO_ESCRITORIO;
    host.appendChild(estilo);
    this.svg = document.createElementNS(NS, 'svg');
    const { x, y, largura, altura } = QUADRO_DA_SALA;
    host.style.setProperty('--esc-proporcao', String(largura / altura));
    const quadro = `${x} ${y} ${largura} ${altura}`;
    this.svg.setAttribute('viewBox', quadro);
    this.svg.setAttribute('role', 'group');
    this.svg.setAttribute('aria-label', 'Escritório dos residentes');
    this.svg.innerHTML = `<defs>${defsDaCena()}</defs><g class="esc-cenario">${cenarioEstatico()}</g><g class="esc-moveis"></g>`;
    host.appendChild(this.svg);
    this.moveis = this.svg.querySelector('.esc-moveis') as SVGGElement;
    this.tres = criar3D();
    if (this.tres) host.appendChild(this.tres.canvas);
    const interfaceDaSala = document.createElementNS(NS, 'svg');
    interfaceDaSala.setAttribute('viewBox', quadro);
    interfaceDaSala.setAttribute('class', 'esc-overlay');
    interfaceDaSala.innerHTML = '<g class="esc-dinamico"></g><g class="esc-frente"></g><g class="esc-sobreposto"></g>';
    host.appendChild(interfaceDaSala);
    this.dinamico = interfaceDaSala.querySelector('.esc-dinamico') as SVGGElement;
    this.frente = interfaceDaSala.querySelector('.esc-frente') as SVGGElement;
    this.sobreposto = interfaceDaSala.querySelector('.esc-sobreposto') as SVGGElement;
    this.montarMoveis();
    host.addEventListener('click', this.aoClicarNaSala);
    this.medirTela();
    window.addEventListener('resize', this.aoRedimensionar);
    if (typeof ResizeObserver !== 'undefined') {
      this.tamanho = new ResizeObserver(() => this.medirTela());
      this.tamanho.observe(host);
    }
    if (typeof IntersectionObserver !== 'undefined') {
      this.vigia = new IntersectionObserver(([e]) => {
        this.naTela = e.isIntersecting;
        if (e.isIntersecting) this.medirTela();
        this.atualizarAtividade();
      });
      this.vigia.observe(host);
    }
    document.addEventListener('visibilitychange', this.aoMudarVisibilidade);
    this.relogioDaParede();
    this.atualizarAtividade();
  }

  /** Liga ou desliga a sala inteira: fora de vista ela não gasta CPU nem GPU. */
  private atualizarAtividade() {
    const deveRodar = this.vivo && this.naTela && !document.hidden;
    if (deveRodar === this.rodando) return;
    this.rodando = deveRodar;
    this.aoAtividade?.(deveRodar);
    if (deveRodar) {
      // Sem isto, o primeiro quadro depois da pausa contaria o tempo parado.
      this.ultimo = performance.now();
      // Escondida, a sala não acompanhou o que mudou: volta em ritmo cheio.
      this.animar();
      this.relogioDaParede();
      this.relogioId = window.setInterval(() => this.relogioDaParede(), 15000);
      this.quadroId = requestAnimationFrame(t => this.quadro(t));
      if (!this.reduzir) {
        this.piscarId = window.setTimeout(() => this.piscar(), 1200);
        this.olharId = window.setTimeout(() => this.olharEmVolta(), 5000);
        this.voltaId = window.setTimeout(() => this.darUmaVolta(), 2500);
      }
    } else {
      cancelAnimationFrame(this.quadroId);
      window.clearInterval(this.relogioId);
      window.clearTimeout(this.olharId);
      window.clearTimeout(this.piscarId);
      window.clearTimeout(this.voltaId);
      this.descartarAnimacoes();
    }
  }

  ativa() { return this.rodando; }

  /** Desenho oculto não acumula gestos; o estado da HQ e os lugares da Mesa ficam. */
  private descartarAnimacoes() {
    for (const o of this.corujas.values()) {
      o.revisao += 1;
      o.cancelarCaminho?.(); o.acordar?.();
      o.fila = Promise.resolve(); o.ocupado = 0;
      if (o.fora) this.liberarLugar(o, o.fora);
      o.fora = null; o.olhando = null; o.cochilando = false;
      o.balao?.remove(); o.balao = null; o.falando = false;
      this.colocar(o, o.naMesa || o.posto);
    }
    this.pedidosNaCaixa = 0; this.mostrarPedidos();
    this.host.querySelector('#esc-vapor')?.classList.remove('esc-ligado');
  }

  private colocar(o: Coruja, nome: string, p = POSTOS[nome]) {
    o.cancelarCaminho?.();
    o.x = p.x; o.y = p.y; o.z = p.z; o.alvoZ = p.z;
    o.postoAtual = nome; o.olhar = p.olhar; o.andando = false;
    o.yaw = this.yawParado(o); o.yawAlvo = o.yaw;
    this.mostrarPose(o); this.posicionar(o);
    this.tres?.posar(o.r.nome, o, 0, this.reduzir);
  }

  reconciliarMesa(nomes: string[]) {
    this.descartarAnimacoes();
    const presentes = new Set(nomes);
    this.levantarDaMesa([...this.corujas.keys()].filter(n => !presentes.has(n)), false);
    this.sentarNaMesa(nomes, false);
  }

  // ---------- montagem ----------
  private addObjeto(markup: string, profundidade: number, naFrente = false) {
    const g = document.createElementNS(NS, 'g');
    g.innerHTML = markup;
    const objeto = { el: g, prof: () => profundidade };
    const camada = naFrente ? this.frente : this.moveis;
    const proximo = this.objetos.find(o => o.el.parentNode === camada && o.prof() > profundidade);
    camada.insertBefore(g, proximo?.el ?? null);
    this.objetos.push(objeto);
    this.objetos.sort((a, b) => a.prof() - b.prof());
    return objeto;
  }

  private montarMoveis() {
    this.addObjeto(mesaRedonda(), MESA.x + MESA.y);
    this.addObjeto(mesinhaDeCentro(), MESINHA.x + MESINHA.y + (MESINHA.w + MESINHA.d) / 2, true);
    this.addObjeto(luminaria(3.6, 9.25), 3.6 + 9.25, true);
    this.addObjeto(vaso(11.3, 9.3, 1.1, 'figueira', 'terra'), 20.6, true);
    this.addObjeto(vaso(6.6, 9.45, 1.0, 'costela', 'creme'), 16.05, true);
    this.addObjeto(copa(), 11.37 + 5.6, true);
    this.addObjeto(caixaDePedidos(), 0.56 + 4.95);
    this.addObjeto(lixeira(), 4.88 + 0.78);
    this.montarRack([]);
  }

  private montarAssentos(quantidade: number) {
    const necessarios = new Set([...this.corujas.values()].flatMap(o =>
      [o.posto, o.naMesa, o.fora].filter((n): n is string => !!n && n.startsWith('lugar'))));
    const escolhidos = new Set(necessarios);
    for (const p of ASSENTOS) {
      if (escolhidos.size >= quantidade) break;
      escolhidos.add(p.nome);
    }
    const ativos = ASSENTOS.filter(p => escolhidos.has(p.nome));
    if (ativos.map(p => p.nome).join('|') === this.assentos.map(p => p.nome).join('|')) return;
    for (const [nome, cadeira] of this.cadeiras) {
      if (escolhidos.has(nome)) continue;
      cadeira.el.remove();
      this.objetos.splice(this.objetos.indexOf(cadeira), 1);
      this.cadeiras.delete(nome);
    }
    for (const p of ativos) {
      if (!this.cadeiras.has(p.nome)) {
        const cadeira = this.addObjeto(banquinho(p.x, p.y, p.angulo), p.x + p.y - 0.45);
        cadeira.el.setAttribute('data-assento', p.nome);
        this.cadeiras.set(p.nome, cadeira);
      }
    }
    this.assentos = ativos;
    this.tres?.assentos(ativos);
  }

  private montarRack(luzes: LuzDoRack[]) {
    const assinatura = luzes.map(l => l.nome + l.cor).join('|');
    if (this.rack && assinatura === this.assinaturaDoRack) return;
    this.assinaturaDoRack = assinatura;
    const custo = this.svg.querySelector('#esc-uso-custo')?.textContent || 'US$ 0,00';
    const turnos = this.svg.querySelector('#esc-uso-turnos')?.textContent || 'hoje';
    if (this.rack) this.rack.el.innerHTML = rackDoRouter(luzes);
    else this.rack = this.addObjeto(rackDoRouter(luzes), RACK.x + RACK.y + (RACK.w + RACK.d) / 2);
    this.texto('esc-uso-custo', custo);
    this.texto('esc-uso-turnos', turnos);
    this.corujas.forEach((o) => { o.ledAceso = null; });
  }

  private texto(id: string, valor: string) {
    const el = this.svg.querySelector(`#${id}`);
    if (el) el.textContent = valor;
  }

  private medirTela() {
    const caixa = this.svg.getBoundingClientRect();
    const larg = caixa.width || QUADRO_DA_SALA.largura;
    this.escNome = Math.max(1, Math.min(1.8, (10 / 12.5) * 840 / larg));
    this.escBalao = Math.max(1, Math.min(1.55, (8.5 / 12.5) * 840 / larg));
    // A escala da etiqueta mudou: a próxima posição é escrita mesmo parada.
    this.corujas.forEach((o) => { o.lugar = ''; });
    this.tres?.resolucao(larg, caixa.height || larg * QUADRO_DA_SALA.altura / QUADRO_DA_SALA.largura);
  }

  // ---------- residentes ----------
  /** Põe na sala quem está na HQ: chega quem é novo, sai quem foi aposentado,
   * e quem mudou de estado ou de acessório se atualiza. */
  sincronizar(lista: ResidenteNaCena[]) {
    const visiveis = lista.slice(0, MAXIMO_NA_SALA);
    const nomes = new Set(visiveis.map(r => r.nome));
    this.corujas.forEach((o, nome) => { if (!nomes.has(nome)) this.tirar(o); });
    const ocupados = new Set([...this.corujas.values()].map(o => o.posto));
    visiveis.forEach((r) => {
      const existente = this.corujas.get(r.nome);
      if (existente) { this.atualizar(existente, r); return; }
      const preferidos = [...(PREFERE[r.familia] || []), ...ORDEM_DOS_POSTOS];
      const posto = preferidos.find(p => !ocupados.has(p)) || 'lugarS';
      ocupados.add(posto);
      this.criar(r, posto);
    });
    this.montarAssentos(visiveis.length);
    this.montarRack(visiveis.map(r => ({ nome: r.nome, cor: r.cores.olho })));
    this.aoPreparacao?.(this.porMontar.size + Number(this.preparando));
    if (this.selecionado && !this.corujas.has(this.selecionado)) this.selecionar(null);
  }

  private criar(r: ResidenteNaCena, posto: string) {
    const p = POSTOS[posto];
    const g = document.createElementNS(NS, 'g');
    g.setAttribute('class', 'esc-coruja');
    g.setAttribute('tabindex', '0');
    g.setAttribute('role', 'button');
    g.setAttribute('aria-label', r.rotulo);
    const tres = this.tres;
    g.innerHTML = `${tres ? '' : `<ellipse class="esc-anel" cx="0" cy="0" rx="${0.55 * S * 1.2247}" ry="${0.55 * S * 0.7071}" fill="none" stroke="${r.cores.olho}" stroke-width="2"/>`}
      ${tres ? '<rect x="-34" y="-78" width="68" height="86" fill="transparent"/>' : `<ellipse cx="0" cy="0" rx="${0.36 * S * 1.2247}" ry="${0.36 * S * 0.7071}" fill="#000" opacity=".3"/>`}
      <g class="esc-ginga"><g transform="translate(${-60 * K} ${-112 * K}) scale(${K})"><g class="esc-plana">${tres ? '' : corujaPlana(r.cores)}</g><g class="esc-sinal"></g></g></g>`;
    const etiqueta = document.createElementNS(NS, 'g');
    etiqueta.setAttribute('class', 'esc-etiqueta');
    etiqueta.setAttribute('data-nome', r.nome);
    // Nasce apagada: só acende em `arrumarEtiquetas`, já no lugar e com o corpo desenhado.
    etiqueta.style.opacity = '0';
    etiqueta.innerHTML = `<rect y="-10.5" height="21" rx="10.5" fill="#111726" fill-opacity=".92" stroke="${r.cores.olho}" stroke-opacity=".8"/>
      <text x="0" y="4.5" text-anchor="middle" font-size="12.5" font-weight="600" fill="#f2efe8" font-family="Geist, sans-serif">${esc(r.rotulo)}</text>`;
    this.sobreposto.appendChild(etiqueta);
    const abrir = () => this.aoSelecionar(r.nome);
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); abrir(); } };
    const mostrarNome = () => { o.sobMouse = true; this.animar(); };
    const esconderNome = () => { o.sobMouse = false; this.animar(); };
    g.addEventListener('click', abrir);
    g.addEventListener('keydown', tecla);
    g.addEventListener('pointerenter', mostrarNome);
    g.addEventListener('pointerleave', esconderNome);
    g.addEventListener('focus', mostrarNome);
    g.addEventListener('blur', esconderNome);
    this.dinamico.appendChild(g);
    const o: Coruja = {
      r, real: r.pose, cochilando: false, assinatura: '', cores: r.cores, acessorios: r.acessorios, pose: r.pose,
      andando: false, falando: false, fase: Math.random() * 6, yaw: CAMERA, yawAlvo: CAMERA, piscandoAte: 0,
      x: p.x, y: p.y, z: p.z, alvoZ: p.z, posto, postoAtual: posto, olhar: p.olhar, caminho: [], aoChegar: null, cancelarCaminho: null,
      fila: Promise.resolve(), revisao: 0, ocupado: 0, fora: null, naMesa: null, baralho: [], acordar: null, chamada: false, olhando: null,
      el: g, ginga: g.querySelector('.esc-ginga') as SVGGElement, sinal: g.querySelector('.esc-sinal') as SVGGElement,
      etiqueta, larguraEtiqueta: 60, etiquetaVisivel: false, balao: null, balaoLarg: 0, balaoAlt: 0, balaoEscrito: '', ledAceso: null, assinaturaDoSinal: '',
      sobMouse: false, nomeAte: performance.now() + NOME_NA_ABERTURA_MS, lugar: '',
      remover: () => {
        g.removeEventListener('click', abrir);
        g.removeEventListener('keydown', tecla);
        g.removeEventListener('pointerenter', mostrarNome);
        g.removeEventListener('pointerleave', esconderNome);
        g.removeEventListener('focus', mostrarNome);
        g.removeEventListener('blur', esconderNome);
        g.remove(); etiqueta.remove(); o.balao?.remove();
        this.tres?.remover(r.nome);
      },
    };
    this.corujas.set(r.nome, o);
    this.medirEtiqueta(o);
    this.atualizar(o, r);
    this.posicionar(o);
  }

  /** Corpo e etiqueta no ponto da sala, sempre juntos. Só escreve quando muda:
   * reescrever o mesmo valor faz o navegador repintar a sala inteira. */
  private posicionar(o: Coruja) {
    this.tres?.posicionar(o.r.nome, o.x, o.y, o.z);
    const [sx, sy] = iso(o.x, o.y, o.z);
    const lugar = `translate(${sx.toFixed(1)} ${sy.toFixed(1)})`;
    if (lugar === o.lugar) return;
    o.lugar = lugar;
    o.el.setAttribute('transform', lugar);
    o.etiqueta.setAttribute('transform', `translate(${sx.toFixed(1)} ${(sy + 6 + 11 * this.escNome).toFixed(1)}) scale(${this.escNome.toFixed(3)})`);
  }

  private atualizar(o: Coruja, r: ResidenteNaCena) {
    o.r = r;
    o.real = r.pose;
    if (!LIVRE.has(r.pose)) this.chamarDeVolta(o);
    o.el.classList.toggle('esc-pausada', r.pose === 'pausado');
    const assinatura = JSON.stringify([r.cores, r.acessorios]);
    if (assinatura !== o.assinatura) {
      o.assinatura = assinatura;
      o.cores = r.cores;
      o.acessorios = r.acessorios;
      if (this.tres) {
        if (this.progressivo) {
          this.porMontar.add(o);
          this.aoPreparacao?.(this.porMontar.size + Number(this.preparando));
        } else this.montarModelo(o);
      }
      else (o.el.querySelector('.esc-plana') as SVGGElement).innerHTML = corujaPlana(r.cores);
    }
    this.mostrarPose(o);
  }

  /** O que a cena mostra: o estado da HQ; quem está livre fica acordado, a não ser no cochilo. */
  private mostrarPose(o: Coruja) {
    o.pose = LIVRE.has(o.real) ? (o.cochilando ? 'dormindo' : 'parado') : o.real;
    this.atualizarSinal(o);
  }

  /** Chegou trabalho no meio de uma volta: acorda e para onde está. Dali a
   * coruja segue para o que estiver na fila ou volta para a mesa. */
  private chamarDeVolta(o: Coruja) {
    o.chamada = true;
    o.cochilando = false;
    o.acordar?.();
    if (o.fora && o.andando) {
      o.cancelarCaminho?.();
    }
  }

  private tirar(o: Coruja) {
    this.porMontar.delete(o);
    o.cancelarCaminho?.();
    o.acordar?.();
    if (o.fora) this.liberarLugar(o, o.fora);
    if (o.naMesa) this.liberarLugar(o, o.naMesa);
    o.remover();
    this.corujas.delete(o.r.nome);
  }

  private montarModelo(o: Coruja) {
    this.tres?.montar(o.r.nome, o);
    this.tres?.posicionar(o.r.nome, o.x, o.y, o.z);
    this.tres?.posar(o.r.nome, o, 0, this.reduzir);
  }

  /** Uma coruja por quadro deixa o navegador processar scroll entre as montagens. */
  private montarProximo() {
    if (this.preparando || !this.porMontar.size) return;
    const o = this.porMontar.values().next().value!;
    this.porMontar.delete(o);
    this.montarModelo(o);
    this.preparando = true;
    Promise.resolve(this.tres?.preparar?.()).catch(e => {
      console.warn('Não foi possível preparar o desenho do Escritório.', e);
    }).finally(() => {
      this.preparando = false;
      this.animar();
      if (this.vivo) this.aoPreparacao?.(this.porMontar.size);
    });
  }

  private liberarLugar(o: Coruja, lugar: string) {
    // A saída antiga não pode apagar a reserva de quem chegou depois.
    if (this.reservados.get(lugar) === o) this.reservados.delete(lugar);
  }

  private atualizarSinal(o: Coruja) {
    const assinatura = `${o.andando}:${o.pose}:${o.cores.olho}`;
    if (assinatura === o.assinaturaDoSinal) return;
    o.assinaturaDoSinal = assinatura;
    o.sinal.innerHTML = o.andando ? '' : sinalDaPose(o.pose, o.cores.olho);
  }

  private medirEtiqueta(o: Coruja) {
    const larg = (o.etiqueta.querySelector('text') as SVGTextElement).getComputedTextLength() + 18;
    const rect = o.etiqueta.querySelector('rect') as SVGRectElement;
    rect.setAttribute('x', (-larg / 2).toFixed(1));
    rect.setAttribute('width', larg.toFixed(1));
    o.larguraEtiqueta = larg;
  }

  /** O nome aparece quando a coruja chega à sala, com o mouse ou o foco em cima
   * e enquanto ela está selecionada; no resto do tempo, a sala fica limpa e o
   * clique abre a ficha. Nome que bateria em outro some até abrir espaço. */
  private arrumarEtiquetas() {
    const agora = performance.now();
    const quer = (o: Coruja) => {
      return o.r.nome === this.selecionado || o.sobMouse || agora < o.nomeAte;
    };
    const peso = (o: Coruja) => (o.r.nome === this.selecionado ? 4 : 0) + (o.sobMouse ? 3 : 0) + (o.balao ? 2 : 0) + (o.pose === 'esperando' ? 1 : 0);
    const postas: { x1: number; x2: number; y1: number; y2: number }[] = [];
    [...this.corujas.values()].sort((a, b) => peso(b) - peso(a)).forEach((o) => {
      const [sx, sy] = iso(o.x, o.y, o.z);
      const cy = sy + 6 + 11 * this.escNome, meia = o.larguraEtiqueta / 2 * this.escNome, alt = 10.5 * this.escNome;
      const caixa = { x1: sx - meia, x2: sx + meia, y1: cy - alt, y2: cy + alt };
      const visivel = quer(o) && !postas.some(p => caixa.x1 < p.x2 && caixa.x2 > p.x1 && caixa.y1 < p.y2 && caixa.y2 > p.y1);
      if (visivel) postas.push(caixa);
      if (visivel !== o.etiquetaVisivel) {
        o.etiquetaVisivel = visivel;
        o.etiqueta.style.opacity = visivel ? '1' : '0';
      }
    });
  }

  selecionar(nome: string | null) {
    this.selecionado = nome;
    this.animar();
    this.corujas.forEach((o, n) => {
      o.el.classList.toggle('esc-selecionada', n === nome);
      this.tres?.destacar(n, n === nome || o.sobMouse);
      o.etiqueta.querySelector('rect')?.setAttribute('stroke-width', n === nome ? '2' : '1');
    });
  }

  retrato(nome: string): string | null {
    const o = this.corujas.get(nome);
    return o && this.tres ? this.tres.retrato(nome) : null;
  }

  // ---------- ações ----------
  private agir(o: Coruja, fn: AcaoDaCoruja) {
    const revisao = o.revisao;
    const vigente = () => this.vivo && this.corujas.get(o.r.nome) === o && o.revisao === revisao;
    o.ocupado += 1;
    const prom = o.fila.then(() => {
      if (vigente()) return fn(vigente);
    }).finally(() => { if (o.revisao === revisao) o.ocupado -= 1; });
    o.fila = prom.catch(() => undefined);
    return prom;
  }

  private andar(o: Coruja, nome: string, destino: Posto = POSTOS[nome]) {
    if (!this.vivo || this.corujas.get(o.r.nome) !== o) return Promise.resolve();
    if (!this.rodando) { this.colocar(o, nome, destino); return Promise.resolve(); }
    o.olhando = null;
    o.cancelarCaminho?.();
    o.olhar = destino.olhar;
    return new Promise<void>((resolve) => {
      let de = { x: o.x, y: o.y };
      o.caminho = [];
      const saida = o.postoAtual.startsWith('sofa') ? [...(POSTOS[o.postoAtual].via || [])].reverse() : [];
      for (const p of [...saida, ...(destino.via || []), destino]) {
        const trecho = rota(de, p, this.assentos);
        if (!trecho.length) { o.caminho = []; resolve(); return; }
        o.caminho.push(...trecho); de = p;
      }
      if (!o.caminho.length) { resolve(); return; }
      o.postoAtual = '';
      o.alvoZ = destino.z;
      const terminar = (chegou: boolean) => {
        o.caminho = []; o.andando = false; o.aoChegar = null; o.cancelarCaminho = null;
        if (chegou) o.postoAtual = nome;
        else o.alvoZ = o.z;
        this.atualizarSinal(o);
        resolve();
      };
      o.aoChegar = () => terminar(true);
      o.cancelarCaminho = () => terminar(false);
      o.andando = true;
      this.atualizarSinal(o);
    });
  }

  /** Chegou tarefa: o envelope cai na caixa e o residente vai buscar. */
  pedidoChegou(nome: string) {
    if (!this.rodando) return;
    const o = this.corujas.get(nome);
    this.pedidosNaCaixa = Math.min(3, this.pedidosNaCaixa + 1);
    this.mostrarPedidos();
    if (!o) return;
    this.chamarDeVolta(o);
    void this.agir(o, async vigente => {
      if (this.reduzir) { this.pedidosNaCaixa = Math.max(0, this.pedidosNaCaixa - 1); this.mostrarPedidos(); return; }
      await this.andar(o, 'caixa');
      if (!vigente()) return;
      this.pedidosNaCaixa = Math.max(0, this.pedidosNaCaixa - 1);
      this.mostrarPedidos();
      await espera(700);
      if (!vigente()) return;
      await this.andar(o, o.posto);
    });
  }

  private mostrarPedidos() {
    [0, 1, 2].forEach(i => this.svg.querySelector(`#esc-envelope-${i}`)?.setAttribute('opacity', i < this.pedidosNaCaixa ? '1' : '0'));
    this.svg.querySelector('#esc-brilho-pedidos')?.classList.toggle('esc-pulsando', this.pedidosNaCaixa > 0);
  }

  /** Cada participante reserva uma cadeira e fica nela até o assunto fechar. */
  sentarNaMesa(nomes: string[], animar = this.rodando) {
    const ocupados = new Set([...this.corujas.values()].map(o => o.posto));
    for (const nome of nomes) {
      const o = this.corujas.get(nome);
      if (o?.fora?.startsWith('lugar')) this.liberarLugar(o, o.fora);
    }
    for (const nome of nomes) {
      const o = this.corujas.get(nome);
      if (!o) continue;
      if (o.naMesa) { if (!animar) this.colocar(o, o.naMesa); continue; }
      const lugares = this.assentos.map(p => p.nome);
      const lugar = lugares.includes(o.posto) && !this.reservados.has(o.posto)
        ? o.posto : lugares.find(l => !this.reservados.has(l) && !ocupados.has(l));
      if (!lugar) continue;
      this.reservados.set(lugar, o);
      o.naMesa = lugar;
      this.chamarDeVolta(o);
      if (animar) void this.agir(o, () => this.andar(o, lugar));
      else this.colocar(o, lugar);
    }
  }

  levantarDaMesa(nomes: string[], animar = this.rodando) {
    for (const nome of nomes) {
      const o = this.corujas.get(nome);
      if (!o || !o.naMesa) continue;
      this.liberarLugar(o, o.naMesa);
      o.naMesa = null;
      if (animar) void this.agir(o, () => this.andar(o, o.posto));
      else this.colocar(o, o.posto);
    }
  }

  /** Um balão sobre a cabeça. `para` vira o cabeçalho ("Iris → você").
   * Quem está no caminho (voltando de uma volta, buscando o envelope) fala ao
   * chegar à mesa: ninguém pede autorização do sofá. */
  falar(nome: string, texto: string, para = '', ms = 4200) {
    if (!this.rodando) return;
    this.animar(ms);
    const o = this.corujas.get(nome);
    if (!o) return;
    if (o.andando || o.ocupado) {
      this.chamarDeVolta(o);
      void this.agir(o, async vigente => {
        // Na Mesa, a fala sai de lá; fora dela, da própria mesa.
        const casa = o.naMesa || o.posto;
        if (o.postoAtual !== casa) await this.andar(o, casa);
        if (!vigente()) return;
        this.balao(o, texto, para, ms);
      });
      return;
    }
    this.balao(o, texto, para, ms);
  }

  private balao(o: Coruja, texto: string, para: string, ms: number) {
    o.balao?.remove();
    const g = document.createElementNS(NS, 'g');
    g.setAttribute('class', 'esc-balao');
    g.innerHTML = `<rect rx="10" fill="#fffdf6" stroke="rgba(0,0,0,.1)"/><path fill="#fffdf6"/>
      ${para ? `<text class="esc-de" font-size="10.5" font-weight="650" fill="#57503f" font-family="Geist, sans-serif"></text>` : ''}`;
    this.sobreposto.appendChild(g);
    // A fala quebra em até três linhas em vez de sumir no meio da frase; o que
    // passa disso fica para o chat e para a Mesa, que mostram a fala inteira.
    const linhas = linhasDoBalao(texto);
    const ditos = linhas.map(linha => {
      const t = document.createElementNS(NS, 'text') as SVGTextElement;
      t.setAttribute('class', 'esc-dito'); t.setAttribute('font-size', '12.5'); t.setAttribute('font-weight', '500');
      t.setAttribute('fill', '#1e1d24'); t.setAttribute('font-family', 'Geist, sans-serif');
      t.textContent = linha;
      g.appendChild(t);
      return t;
    });
    const de = g.querySelector('.esc-de') as SVGTextElement | null;
    if (de) de.textContent = `${o.r.rotulo} → ${para}`;
    const maior = Math.max(...ditos.map(t => t.getComputedTextLength()), de ? de.getComputedTextLength() : 0);
    const larg = Math.min(340, maior + 22);
    const topo = de ? 16 : 0;
    const alt = topo + 12 + linhas.length * 16;
    const rect = g.querySelector('rect') as SVGRectElement;
    rect.setAttribute('width', String(larg)); rect.setAttribute('height', String(alt));
    rect.setAttribute('x', String(-larg / 2)); rect.setAttribute('y', String(-alt));
    (g.querySelector('path') as SVGPathElement).setAttribute('d', 'M-6 -1 L0 8 L6 -1 Z');
    ditos.forEach((t, i) => { t.setAttribute('x', String(-larg / 2 + 11)); t.setAttribute('y', String(-alt + topo + 18 + i * 16)); });
    if (de) { de.setAttribute('x', String(-larg / 2 + 11)); de.setAttribute('y', String(-alt + 17)); }
    o.balao = g; o.balaoLarg = larg; o.balaoAlt = alt; o.balaoEscrito = ''; o.falando = true;
    this.arrumarBaloes();
    // Fala longa fica mais tempo: dá para ler antes de sumir.
    const tempo = Math.max(ms, Math.min(9000, 2500 + linhas.join(' ').length * 45));
    window.setTimeout(() => { if (o.balao === g) { g.remove(); o.balao = null; o.falando = false; } }, tempo);
  }

  /** Cada balão sobre a cabeça de quem fala. Dois ao mesmo tempo não se cobrem:
   * o de cima sobe até ficar livre e o bico estica até a coruja. */
  private arrumarBaloes() {
    const e = this.escBalao;
    const postos: { x1: number; x2: number; y1: number; y2: number }[] = [];
    [...this.corujas.values()].filter(o => o.balao).map((o) => {
      const [sx, sy] = iso(o.x, o.y, o.z);
      return { o, sx, base: sy - 72 };
    }).sort((a, b) => b.base - a.base).forEach(({ o, sx, base }) => {
      const meio = o.balaoLarg / 2 * e, alt = o.balaoAlt * e;
      const cx = Math.max(-392 + meio, Math.min(432 - meio, sx));
      let y = base;
      for (let i = 0; i < postos.length + 1; i++) {
        const bate = postos.find(p => cx - meio < p.x2 + 4 && cx + meio > p.x1 - 4 && y - alt < p.y2 && y + 2 > p.y1);
        if (!bate) break;
        y = bate.y1 - 6;
      }
      postos.push({ x1: cx - meio, x2: cx + meio, y1: y - alt, y2: y + 2 });
      const ponta = (sx - cx) / e, base0 = Math.max(-o.balaoLarg / 2 + 14, Math.min(o.balaoLarg / 2 - 14, ponta));
      const desce = 8 + (base - y) / e;
      const transform = `translate(${cx.toFixed(1)} ${y.toFixed(1)}) scale(${e.toFixed(3)})`;
      const bico = `M${(base0 - 6).toFixed(1)} -1 L${ponta.toFixed(1)} ${desce.toFixed(1)} L${(base0 + 6).toFixed(1)} -1 Z`;
      // Balão parado não muda: reescrever o atributo a cada quadro só custa estilo.
      if (o.balaoEscrito === transform + bico) return;
      o.balaoEscrito = transform + bico;
      (o.balao as SVGGElement).setAttribute('transform', transform);
      o.balao?.querySelector('path')?.setAttribute('d', bico);
    });
  }

  /** Quadro do dia, rack do Router e farol: tudo o que a HQ conta em números. */
  painel(p: PainelDoDia) {
    this.texto('esc-quadro-feitas', String(p.feitas));
    this.texto('esc-quadro-fila', String(p.fila));
    this.texto('esc-quadro-esperando', String(p.esperando));
    this.texto('esc-uso-custo', `US$ ${p.usd.toFixed(2).replace('.', ',')}`);
    this.texto('esc-uso-turnos', `${p.turnos} turnos`);
    const aceso = p.esperando > 0;
    this.svg.querySelector('#esc-farol')?.classList.toggle('esc-aceso', aceso);
    this.svg.querySelector('#esc-farol-brilho')?.classList.toggle('esc-aceso', aceso);
  }

  // ---------- o jeito de estar vivo ----------
  private relogioDaParede() {
    const agora = new Date(), m = agora.getMinutes(), h = agora.getHours() % 12 + m / 60;
    this.svg.querySelector('#esc-ponteiro-h')?.setAttribute('transform', `rotate(${(h * 30).toFixed(1)} .38 .38)`);
    this.svg.querySelector('#esc-ponteiro-m')?.setAttribute('transform', `rotate(${(m * 6).toFixed(1)} .38 .38)`);
  }

  private piscar() {
    if (!this.vivo || !this.rodando) return;
    this.corujas.forEach((o) => {
      if (Math.random() < 0.35 && o.pose !== 'dormindo' && o.pose !== 'pausado') o.piscandoAte = performance.now() + 140;
    });
    this.piscarId = window.setTimeout(() => this.piscar(), 1400 + Math.random() * 1600);
  }

  /** De vez em quando alguém olha para um colega por uns segundos. */
  private olharEmVolta() {
    if (!this.vivo || !this.rodando) return;
    const livres = [...this.corujas.values()].filter(o => !o.andando && !o.balao && o.pose !== 'dormindo' && o.pose !== 'pausado');
    if (livres.length > 1) {
      const quem = livres[Math.floor(Math.random() * livres.length)];
      const outros = livres.filter(o => o !== quem);
      quem.olhando = outros[Math.floor(Math.random() * outros.length)];
      window.setTimeout(() => { quem.olhando = null; }, 2600);
    }
    this.olharId = window.setTimeout(() => this.olharEmVolta(), 6000 + Math.random() * 6000);
  }

  // ---------- as voltas de quem está livre ----------
  private podeSair(o: Coruja) {
    return LIVRE.has(o.real) && !o.andando && !o.balao && !o.ocupado && !o.fora && !o.naMesa && o.postoAtual === o.posto;
  }

  /** De tempos em tempos alguém livre levanta. Metade da sala, no máximo, fica fora da mesa. */
  private darUmaVolta() {
    if (!this.vivo || !this.rodando) return;
    const todas = [...this.corujas.values()];
    const fora = todas.filter(o => o.fora).length;
    const podem = todas.filter(o => this.podeSair(o));
    if (podem.length && fora < Math.max(1, Math.floor(todas.length / 2))) {
      const o = podem[Math.floor(Math.random() * podem.length)];
      // Um baralho por coruja: cada tipo de volta sai uma vez por rodada.
      for (let tentativa = 0; tentativa < VOLTAS.length; tentativa++) {
        if (!o.baralho.length) o.baralho = VOLTAS.slice().sort(() => Math.random() - 0.5);
        const volta = this.volta(o, o.baralho.shift() as Volta);
        if (volta) { void this.agir(o, volta); break; }
      }
    }
    this.voltaId = window.setTimeout(() => this.darUmaVolta(), 2200 + Math.random() * 3200);
  }

  private volta(o: Coruja, tipo: Volta): AcaoDaCoruja | null {
    const sorte = Math.random();
    if (tipo === 'cafe') {
      if (this.reservados.has('cafe')) return null;
      const vapor = this.host.querySelector('#esc-vapor');
      return this.passeio(o, 'cafe', CANTOS.cafe, 2600 + sorte * 1600, {
        cena: () => { vapor?.classList.add('esc-ligado'); return () => vapor?.classList.remove('esc-ligado'); },
      });
    }
    if (tipo === 'sofa') {
      // Mesmo sem reserva, quem está saindo ainda ocupa o espaço do assento.
      const canto = LUGARES_DO_SOFA.find(c => !this.reservados.has(c)
        && ![...this.corujas.values()].some(colega =>
          Math.hypot(colega.x - CANTOS[c].x, colega.y - CANTOS[c].y) < FOLGA * 2));
      return canto ? this.passeio(o, canto, CANTOS[canto], 8000 + sorte * 6000, { cochila: true }) : null;
    }
    if (tipo === 'mesa') {
      const ocupados = new Set([...this.corujas.values()].map(c => c.posto));
      const livres = this.assentos.map(p => p.nome).filter(l => !ocupados.has(l) && !this.reservados.has(l));
      if (!livres.length) return null;
      const lugar = livres[Math.floor(sorte * livres.length)];
      return this.passeio(o, lugar, POSTOS[lugar], 4500 + sorte * 3500, {});
    }
    if (tipo === 'visita') {
      const trabalhando = [...this.corujas.values()].filter(c => c !== o && c.real === 'trabalhando'
        && !c.andando && c.postoAtual === c.posto && !c.posto.startsWith('lugar') && !this.reservados.has(`visita:${c.r.nome}`));
      if (!trabalhando.length) return null;
      const alvo = trabalhando[Math.floor(sorte * trabalhando.length)];
      // Para na frente da mesa do colega, do lado da sala.
      const p = POSTOS[alvo.posto], dx = 6 - p.x, dy = 5.2 - p.y, d = Math.hypot(dx, dy) || 1;
      const ponto: Posto = { x: p.x + dx / d * 1.05, y: p.y + dy / d * 1.05, z: 0, olhar: Math.atan2(-dx, -dy) };
      return this.passeio(o, `visita:${alvo.r.nome}`, ponto, 3200 + sorte * 1800, { olhando: alvo });
    }
    // Cochilo na própria mesa: só para quem a HQ diz que está dormindo.
    if (o.real !== 'dormindo') return null;
    return async vigente => {
      o.cochilando = true;
      this.mostrarPose(o);
      await this.pausa(o, 6000 + sorte * 6000);
      if (!vigente()) return;
      o.cochilando = false;
      this.mostrarPose(o);
    };
  }

  private passeio(o: Coruja, canto: string, destino: Posto, ms: number,
    op: { cochila?: boolean; olhando?: Coruja; cena?: () => () => void }) {
    this.reservados.set(canto, o);
    o.fora = canto;
    return async (vigente: () => boolean) => {
      o.chamada = false;
      try {
        if (!LIVRE.has(o.real)) return;
        await this.andar(o, canto, destino);
        if (!vigente() || !LIVRE.has(o.real) || o.chamada) return;
        if (op.olhando) o.olhando = op.olhando;
        if (op.cochila && o.real === 'dormindo') { o.cochilando = true; this.mostrarPose(o); }
        const desfazer = op.cena?.();
        await this.pausa(o, ms);
        desfazer?.();
      } finally {
        if (!vigente()) return;
        o.cochilando = false;
        o.olhando = null;
        this.mostrarPose(o);
        if (o.naMesa !== canto) this.liberarLugar(o, canto);
        o.fora = null;
        // Com outra ação na fila (chegou pedido), ela segue direto dali; senão volta para a mesa.
        if (this.vivo && this.corujas.get(o.r.nome) === o && o.ocupado <= 1 && o.postoAtual !== o.posto) await this.andar(o, o.posto);
      }
    };
  }

  /** Espera da volta: acaba antes se chegar tarefa (`acordar`). */
  private pausa(o: Coruja, ms: number) {
    if (!LIVRE.has(o.real) || !this.vivo || o.chamada) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const fim = () => { window.clearTimeout(id); if (o.acordar === fim) o.acordar = null; resolve(); };
      const id = window.setTimeout(fim, ms);
      o.acordar = fim;
    });
  }

  private yawParado(o: Coruja) {
    if (o.olhando) return mistura(Math.atan2(o.olhando.x - o.x, o.olhando.y - o.y), CAMERA, 0.35);
    if (o.olhar === 'mesa') return mistura(Math.atan2(MESA.x - o.x, MESA.y - o.y), CAMERA, 0.45);
    return o.olhar;
  }

  /** Algo na sala está mudando: alguém anda, chega, assenta, está sob o mouse
   * ou foi tocado há pouco. Parada, a sala só respira e pisca. */
  private emMovimento(agora: number) {
    if (agora < this.animarAte || this.porMontar.size > 0 || this.preparando) return true;
    for (const o of this.corujas.values()) {
      if (o.caminho.length || o.andando || o.sobMouse || Math.abs(o.alvoZ - o.z) > 0.01) return true;
    }
    return false;
  }

  /** Volta ao ritmo cheio por um instante, depois de um toque na sala. */
  private animar(ms = 1200) {
    this.animarAte = performance.now() + ms;
  }

  private quadro(t: number) {
    if (!this.vivo || !this.rodando) return;
    const decorrido = (t - this.ultimo) / 1000;
    // Parada, a sala desenha a 8 quadros/s; o respirar e o piscar não pedem 30.
    const ativa = this.emMovimento(t);
    if (decorrido + 0.001 < (ativa ? 1 / 30 : 1 / 8)) {
      this.quadroId = requestAnimationFrame(x => this.quadro(x));
      return;
    }
    const dt = Math.min(ativa ? 0.05 : 0.15, decorrido);
    this.ultimo = t;
    const inicio = this.aoQuadro ? performance.now() : 0;
    this.montarProximo();
    this.corujas.forEach((o) => {
      if (o.caminho.length && o.real !== 'pausado') {
        const alvo = o.caminho[0];
        const dx = alvo.x - o.x, dy = alvo.y - o.y, dist = Math.hypot(dx, dy);
        const passo = VEL_ANDAR * dt;
        if (dist <= passo) { o.x = alvo.x; o.y = alvo.y; o.caminho.shift(); } else { o.x += dx / dist * passo; o.y += dy / dist * passo; }
        o.z += (0 - o.z) * Math.min(1, dt * 10);
        if (!o.caminho.length) {
          o.andando = false;
          this.atualizarSinal(o);
          const f = o.aoChegar; o.aoChegar = null; f?.();
        }
      } else if (!o.caminho.length) {
        o.z += (o.alvoZ - o.z) * Math.min(1, dt * 8);
      }
      o.fase += dt * (o.andando ? 10 : 2.2);
      this.posicionar(o);
      this.tres?.destacar(o.r.nome, this.selecionado === o.r.nome || o.sobMouse);
      if (this.tres) {
        o.yawAlvo = o.andando && o.caminho.length ? Math.atan2(o.caminho[0].x - o.x, o.caminho[0].y - o.y) : this.yawParado(o);
        this.tres.posar(o.r.nome, o, dt, this.reduzir);
      } else if (!this.reduzir) {
        const sobe = o.andando ? Math.abs(Math.sin(o.fase)) * 3 : o.pose === 'esperando' ? Math.abs(Math.sin(o.fase * 2.2)) * 5 : Math.sin(o.fase) * 1.2;
        o.ginga.setAttribute('transform', `translate(0 ${(-sobe).toFixed(2)})`);
      }
      const usa = o.real === 'trabalhando' || o.falando;
      if (usa !== o.ledAceso) {
        o.ledAceso = usa;
        this.svg.querySelector(`#esc-led-${CSS.escape(o.r.nome)}`)?.classList.toggle('esc-ativo', usa);
      }
    });
    if (!this.preparando) this.tres?.desenhar();
    this.arrumarBaloes();
    if (!this.preparando) this.arrumarEtiquetas();
    if (this.aoQuadro) this.aoQuadro({ ms: performance.now() - inicio, intervalo: decorrido * 1000,
      esperado: 1000 / (ativa ? 30 : 8),
      ...(this.tres?.medicao() ?? { chamadas: 0, triangulos: 0 }) });
    this.quadroId = requestAnimationFrame(x => this.quadro(x));
  }

  destruir() {
    this.vivo = false;
    this.rodando = false;
    document.removeEventListener('visibilitychange', this.aoMudarVisibilidade);
    this.host.removeEventListener('click', this.aoClicarNaSala);
    this.vigia?.disconnect();
    this.tamanho?.disconnect();
    cancelAnimationFrame(this.quadroId);
    window.clearInterval(this.relogioId);
    window.clearTimeout(this.olharId);
    window.clearTimeout(this.piscarId);
    window.clearTimeout(this.voltaId);
    this.corujas.forEach(o => o.acordar?.());
    this.corujas.forEach(o => o.cancelarCaminho?.());
    window.removeEventListener('resize', this.aoRedimensionar);
    this.corujas.forEach(o => o.remover());
    this.corujas.clear();
    this.porMontar.clear();
    this.reservados.clear();
    this.tres?.destruir();
    this.host.replaceChildren();
    this.host.classList.remove('esc-raiz');
    this.host.style.removeProperty('--esc-proporcao');
  }
}

