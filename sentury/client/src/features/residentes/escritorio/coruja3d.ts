/** Os residentes compartilham a cena 3D, alinhada ao cenário SVG. */
import * as THREE from 'three';
import { escurecer } from './iso';
import { MESA, MESINHA, PARTES_DA_CADEIRA, RACK, TAMPOS, vaso, luminaria, lixeira, type AssentoDaMesa } from './cenario';
import { recorte3D } from './recortes3d';
import { cameraDaSala, ESCALA_DA_CORUJA, QUADRO_DA_SALA } from './projecao3d';
import { juntarMalhas } from './malhas3d';

export interface CoresDaCoruja { penas: string; asas: string; barriga: string; olho: string }

export type PoseDaCoruja = 'parado' | 'trabalhando' | 'esperando' | 'dormindo' | 'pausado';

export interface CorujaAnimada {
  cores: CoresDaCoruja;
  /** Encaixe → peça, como o residente guarda (`cabeca: 'capacete'`). */
  acessorios: Record<string, string>;
  pose: PoseDaCoruja;
  andando: boolean;
  falando: boolean;
  fase: number;
  yaw: number;
  yawAlvo: number;
  piscandoAte: number;
}

interface Modelo {
  raiz: THREE.Group;
  corpo: THREE.Group;
  olhos: THREE.Group;
  fechados: THREE.Group;
  asaE: THREE.Group;
  asaD: THREE.Group;
  pes: THREE.Mesh[];
  coresOriginais: Map<THREE.MeshStandardMaterial, THREE.Color>;
  pausado: boolean;
}

export interface Motor3D {
  canvas: HTMLCanvasElement;
  montar(chave: string, coruja: CorujaAnimada): void;
  posar(chave: string, coruja: CorujaAnimada, dt: number, reduzir: boolean): void;
  posicionar(chave: string, x: number, y: number, z: number): void;
  destacar(chave: string, visivel: boolean): void;
  assentos(lista: readonly AssentoDaMesa[]): void;
  desenhar(): void;
  preparar?(): Promise<void>;
  resolucao(largura: number, altura: number): void;
  medicao(): { chamadas: number; triangulos: number };
  retrato(chave: string): string;
  remover(chave: string): void;
  destruir(): void;
}

const MASCARA = '#f3eee4';
const OURO = '#f2b705';

export function criar3D(): Motor3D | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    if (!renderer.getContext()) return null;
  } catch {
    return null;
  }
  renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio || 1));
  renderer.setSize(QUADRO_DA_SALA.largura, QUADRO_DA_SALA.altura, false);
  renderer.domElement.className = 'esc-canvas3d';
  renderer.domElement.setAttribute('aria-hidden', 'true');
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  const cena = new THREE.Scene();
  const camera = cameraDaSala();
  const hh = 100 / 2 / 66, hw = 88 / 2 / 66;
  const cam = new THREE.OrthographicCamera(-hw, hw, hh, -hh, 0.1, 50);
  const alvo = new THREE.Vector3(0, 0.6, 0);
  const el = THREE.MathUtils.degToRad(30), az = Math.PI / 4;
  cam.position.copy(alvo).addScaledVector(new THREE.Vector3(Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az)), 10);
  cam.lookAt(alvo);
  cam.updateMatrixWorld();
  const PI = Math.PI;
  cena.add(new THREE.HemisphereLight(0xdfe8ff, 0x6b4a32, 0.85 * PI));
  const chave = new THREE.DirectionalLight(0xffe7c7, 1.25 * PI);
  chave.position.set(-4, 12, 8);
  chave.target.position.set(6, 0, 5);
  cena.add(chave, chave.target);
  const borda = new THREE.DirectionalLight(0x9cc4ff, 0.95 * PI);
  borda.position.set(2, 8, -8);
  cena.add(borda);
  const preench = new THREE.DirectionalLight(0xffd2a8, 0.35 * PI);
  preench.position.set(14, 5, 6);
  cena.add(preench);

  interface OpMat { r?: number; m?: number; e?: string; ei?: number; t?: boolean; o?: number }
  const mat = (h: string, op: OpMat = {}) => new THREE.MeshStandardMaterial({
    color: new THREE.Color(h), roughness: op.r ?? 0.58, metalness: op.m ?? 0,
    emissive: op.e ? new THREE.Color(op.e) : new THREE.Color(0), emissiveIntensity: op.ei ?? 1,
    transparent: !!op.t, opacity: op.o ?? 1,
  });
  const malha = (geo: THREE.BufferGeometry, h: string, op?: OpMat) => {
    const m = new THREE.Mesh(geo, mat(h, op));
    m.castShadow = true; m.receiveShadow = true;
    return m;
  };
  const esf = (r: number, h: string, pos: [number, number, number], esc: [number, number, number] = [1, 1, 1], op?: OpMat) => {
    const m = malha(new THREE.SphereGeometry(r, r < 0.12 ? 14 : 24, r < 0.12 ? 10 : 16), h, op);
    m.position.set(...pos); m.scale.set(...esc);
    return m;
  };
  /** Meia esfera (cúpula) para chapéus e capacete. */
  const cupula = (r: number, h: string, y: number, esc: [number, number, number], op?: OpMat) => {
    const m = malha(new THREE.SphereGeometry(r, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), h, op);
    m.position.set(0, y, 0); m.scale.set(...esc);
    return m;
  };

  // ---------- as peças do catálogo ----------
  type Lugar = { corpo: THREE.Group; asaE: THREE.Group; asaD: THREE.Group };
  const PECAS: Record<string, (l: Lugar) => void> = {
    // cabeça: tudo assenta no alto da cabeça (y 0,86), acima da máscara, para o rosto ficar à vista
    capacete: ({ corpo }) => {
      corpo.add(cupula(0.3, '#f5c400', 0.86, [1.05, 0.8, 1.03], { r: 0.35, m: 0.25 }));
      const aba = malha(new THREE.TorusGeometry(0.31, 0.024, 10, 56), '#d9ab00', { r: 0.4, m: 0.2 });
      aba.rotation.x = Math.PI / 2; aba.position.set(0, 0.865, 0.01); aba.scale.set(1.05, 1.02, 1);
      const crista = malha(new THREE.BoxGeometry(0.05, 0.04, 0.46), '#d9ab00', { r: 0.4, m: 0.2 });
      crista.position.set(0, 1.1, 0.02);
      const lanterna = esf(0.04, '#fff6c2', [0, 0.95, 0.28], [1, 1, 0.6], { e: '#fff1a6', ei: 0.9 });
      corpo.add(aba, crista, lanterna);
    },
    gorro: ({ corpo }) => {
      corpo.add(cupula(0.3, '#c2410c', 0.86, [1.04, 0.95, 1.02], { r: 0.9 }));
      const barra = malha(new THREE.TorusGeometry(0.305, 0.045, 12, 56), '#9a3412', { r: 0.95 });
      barra.rotation.x = Math.PI / 2; barra.position.set(0, 0.87, 0.01); barra.scale.set(1.04, 1.02, 1);
      corpo.add(barra, esf(0.065, '#fef3c7', [0, 1.18, 0], [1, 1, 1], { r: 1 }));
    },
    bone: ({ corpo }) => {
      corpo.add(cupula(0.3, '#2563eb', 0.86, [1.04, 0.75, 1.02], { r: 0.7 }));
      const aba = malha(new THREE.CylinderGeometry(0.2, 0.2, 0.02, 32, 1, false, -Math.PI / 2, Math.PI), '#1d4ed8', { r: 0.7 });
      aba.position.set(0, 0.87, 0.24); aba.rotation.x = 0.12;
      corpo.add(aba, esf(0.025, '#1d4ed8', [0, 1.085, 0], [1, 0.6, 1]));
    },
    chapeu: ({ corpo }) => {
      const aba = malha(new THREE.CylinderGeometry(0.42, 0.42, 0.022, 48), '#57534e', { r: 0.85 });
      aba.position.set(0, 0.92, 0);
      const copa = malha(new THREE.CylinderGeometry(0.21, 0.24, 0.22, 40), '#78716c', { r: 0.85 });
      copa.position.set(0, 1.04, 0);
      const fita = malha(new THREE.CylinderGeometry(0.245, 0.245, 0.05, 40), '#292524', { r: 0.7 });
      fita.position.set(0, 0.955, 0);
      corpo.add(aba, copa, fita);
    },
    // rosto
    oculos: ({ corpo }) => {
      [-1, 1].forEach((s) => {
        const aro = malha(new THREE.TorusGeometry(0.104, 0.013, 12, 44), '#1b2a45', { m: 0.55, r: 0.3 });
        aro.position.set(0.14 * s, 0.67, 0.43);
        const lente = new THREE.Mesh(new THREE.CircleGeometry(0.1, 32), mat('#cfe6ff', { t: true, o: 0.14, r: 0.05 }));
        lente.position.set(0.14 * s, 0.67, 0.434);
        corpo.add(aro, lente);
      });
      const ponte = malha(new THREE.CylinderGeometry(0.009, 0.009, 0.075, 10), '#1b2a45', { m: 0.55, r: 0.3 });
      ponte.rotation.z = Math.PI / 2; ponte.position.set(0, 0.68, 0.44);
      corpo.add(ponte);
    },
    escuros: ({ corpo }) => {
      [-1, 1].forEach((s) => {
        const lente = malha(new THREE.BoxGeometry(0.21, 0.13, 0.03), '#141218', { r: 0.12, m: 0.5 });
        lente.position.set(0.14 * s, 0.675, 0.44);
        corpo.add(lente);
        const reflexo = new THREE.Mesh(new THREE.PlaneGeometry(0.06, 0.012), mat('#ffffff', { e: '#ffffff', ei: 0.6, t: true, o: 0.6 }));
        reflexo.position.set(0.14 * s - 0.04, 0.705, 0.457); reflexo.rotation.z = 0.35;
        corpo.add(reflexo);
      });
      const ponte = malha(new THREE.BoxGeometry(0.07, 0.018, 0.02), '#141218', { r: 0.2, m: 0.5 });
      ponte.position.set(0, 0.69, 0.445);
      corpo.add(ponte);
    },
    monoculo: ({ corpo }) => {
      const aro = malha(new THREE.TorusGeometry(0.104, 0.015, 12, 44), '#b45309', { m: 0.7, r: 0.3 });
      aro.position.set(0.14, 0.67, 0.43);
      const lente = new THREE.Mesh(new THREE.CircleGeometry(0.1, 32), mat('#fff3d6', { t: true, o: 0.18, r: 0.05 }));
      lente.position.set(0.14, 0.67, 0.434);
      const corrente = malha(new THREE.TorusGeometry(0.16, 0.006, 6, 30, Math.PI * 0.8), '#b45309', { m: 0.7, r: 0.3 });
      corrente.position.set(0.26, 0.52, 0.36); corrente.rotation.set(0.2, 0.5, -1.9);
      corpo.add(aro, lente, corrente);
    },
    // ouvidos
    fone: ({ corpo }) => {
      const c = '#2d2a26';
      const arco = malha(new THREE.TorusGeometry(0.44, 0.03, 12, 56, Math.PI), c, { r: 0.4, m: 0.2 });
      arco.position.set(0, 0.6, -0.02);
      corpo.add(arco);
      [-1, 1].forEach((s) => {
        const concha = malha(new THREE.CylinderGeometry(0.09, 0.09, 0.08, 28), c, { r: 0.4, m: 0.2 });
        concha.rotation.z = Math.PI / 2; concha.position.set(0.44 * s, 0.6, -0.02);
        const almofada = malha(new THREE.CylinderGeometry(0.075, 0.075, 0.03, 24), '#57534e', { r: 0.9 });
        almofada.rotation.z = Math.PI / 2; almofada.position.set(0.4 * s, 0.6, -0.02);
        corpo.add(concha, almofada);
      });
      const mic = malha(new THREE.CylinderGeometry(0.01, 0.01, 0.3, 8), c, { r: 0.4 });
      mic.position.set(-0.42, 0.5, 0.15); mic.rotation.set(1.15, 0, 0.25);
      corpo.add(mic, esf(0.025, c, [-0.4, 0.44, 0.29]));
    },
    // pescoço
    gravata: ({ corpo }) => {
      const no = malha(new THREE.BoxGeometry(0.07, 0.05, 0.04), '#2d2a26', { r: 0.6 });
      no.position.set(0, 0.47, 0.39);
      const lamina = malha(new THREE.ConeGeometry(0.06, 0.22, 4), '#2d2a26', { r: 0.6 });
      lamina.position.set(0, 0.33, 0.405); lamina.rotation.set(-0.25, Math.PI / 4, Math.PI);
      lamina.scale.set(1, 1, 0.35);
      corpo.add(no, lamina);
    },
    borboleta: ({ corpo }) => {
      [-1, 1].forEach((s) => {
        const asa = malha(new THREE.ConeGeometry(0.06, 0.12, 3), '#b91c1c', { r: 0.6 });
        asa.position.set(0.065 * s, 0.46, 0.4); asa.rotation.z = (Math.PI / 2) * s;
        asa.scale.set(1, 1, 0.45);
        corpo.add(asa);
      });
      corpo.add(esf(0.03, '#7f1d1d', [0, 0.46, 0.41], [1, 1, 0.7]));
    },
    cachecol: ({ corpo }) => {
      const c = '#c2410c';
      const anel = malha(new THREE.TorusGeometry(0.375, 0.058, 16, 56), c, { r: 0.85 });
      anel.rotation.x = Math.PI / 2 - 0.16; anel.position.set(0, 0.4, 0.01); anel.scale.set(1.04, 1, 1);
      const ponta = malha(new THREE.BoxGeometry(0.1, 0.25, 0.05), '#9a3412', { r: 0.85 });
      ponta.position.set(0.15, 0.24, 0.36); ponta.rotation.set(0.25, 0, 0.12);
      corpo.add(anel, ponta);
    },
    cracha: ({ corpo }) => {
      [-1, 1].forEach((s) => {
        const fita = malha(new THREE.CylinderGeometry(0.008, 0.008, 0.26, 6), '#2563eb');
        fita.position.set(0.075 * s, 0.4, 0.36); fita.rotation.set(-0.35, 0, 0.45 * s);
        corpo.add(fita);
      });
      const cartao = malha(new THREE.BoxGeometry(0.15, 0.11, 0.012), MASCARA, { r: 0.8 });
      cartao.position.set(0, 0.26, 0.41); cartao.rotation.x = -0.2;
      const foto = malha(new THREE.BoxGeometry(0.045, 0.045, 0.004), '#93c5fd');
      foto.position.set(-0.035, 0.265, 0.418); foto.rotation.x = -0.2;
      corpo.add(cartao, foto);
    },
    // na asa
    chave: ({ asaD }) => {
      const g = new THREE.Group();
      const cabo = malha(new THREE.BoxGeometry(0.042, 0.27, 0.026), '#a3adbb', { m: 0.75, r: 0.3 });
      const boca = malha(new THREE.TorusGeometry(0.052, 0.02, 10, 24, Math.PI * 1.45), '#a3adbb', { m: 0.75, r: 0.3 });
      boca.position.set(0, 0.16, 0); boca.rotation.z = -Math.PI * 0.22;
      g.add(cabo, boca);
      g.position.set(0.05, -0.27, 0.17); g.rotation.set(0.2, 0, -0.55);
      asaD.add(g);
    },
    lupa: ({ asaE }) => {
      const g = new THREE.Group();
      const aro = malha(new THREE.TorusGeometry(0.078, 0.016, 12, 36), '#2d2a26', { m: 0.5, r: 0.35 });
      const vidro = new THREE.Mesh(new THREE.CircleGeometry(0.075, 32), mat('#e0f2fe', { t: true, o: 0.45, r: 0.05 }));
      const cabo = malha(new THREE.CylinderGeometry(0.016, 0.018, 0.15, 12), '#5a4632', { r: 0.6 });
      cabo.position.set(0, -0.15, 0);
      g.add(aro, vidro, cabo);
      g.position.set(-0.04, -0.2, 0.22); g.rotation.set(-0.2, 0.45, 0.35);
      asaE.add(g);
    },
    prancheta: ({ asaE }) => {
      const g = new THREE.Group();
      const tabua = malha(new THREE.BoxGeometry(0.21, 0.28, 0.024), '#b07a45', { r: 0.7 });
      const folha = malha(new THREE.BoxGeometry(0.165, 0.21, 0.006), '#fffdf6', { r: 0.9 });
      folha.position.set(0, -0.015, 0.016);
      const clipe = malha(new THREE.BoxGeometry(0.085, 0.035, 0.03), '#4b4540', { m: 0.4, r: 0.4 });
      clipe.position.set(0, 0.13, 0.02);
      g.add(tabua, folha, clipe);
      [0.04, 0, -0.04, -0.08].forEach((y) => {
        const l = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.008, 0.002), mat('#c9c0ac'));
        l.position.set(-0.01, y, 0.021); g.add(l);
      });
      g.position.set(-0.03, -0.25, 0.19); g.rotation.set(-0.1, 0.55, 0.1);
      asaE.add(g);
    },
    notebook: ({ asaD }) => {
      const g = new THREE.Group();
      const base = malha(new THREE.BoxGeometry(0.27, 0.018, 0.19), '#3f3f46', { m: 0.5, r: 0.35 });
      const tampa = new THREE.Group();
      const tela = malha(new THREE.BoxGeometry(0.27, 0.18, 0.014), '#3f3f46', { m: 0.5, r: 0.35 });
      tela.position.y = 0.09;
      const brilho = new THREE.Mesh(new THREE.PlaneGeometry(0.24, 0.15), mat('#1e3a5f', { e: '#93c5fd', ei: 0.45 }));
      brilho.position.set(0, 0.09, 0.008);
      tampa.add(tela, brilho);
      tampa.position.set(0, 0.01, -0.095); tampa.rotation.x = -0.25;
      g.add(base, tampa);
      g.position.set(0.02, -0.3, 0.2); g.rotation.set(0.25, -0.55, -0.15);
      asaD.add(g);
    },
    caneca: ({ asaE }) => {
      const g = new THREE.Group();
      const copo = malha(new THREE.CylinderGeometry(0.06, 0.055, 0.12, 28), MASCARA, { r: 0.5 });
      const cafe = new THREE.Mesh(new THREE.CircleGeometry(0.052, 24), mat('#6b3e1f', { r: 0.3 }));
      cafe.rotation.x = -Math.PI / 2; cafe.position.y = 0.055;
      const alca = malha(new THREE.TorusGeometry(0.035, 0.011, 8, 20), '#57534e', { r: 0.5 });
      alca.position.set(0.065, 0, 0);
      g.add(copo, cafe, alca);
      g.position.set(-0.02, -0.28, 0.2); g.rotation.set(0.1, 0.4, 0.1);
      asaE.add(g);
    },
    escudo: ({ asaE }) => {
      const forma = new THREE.Shape();
      forma.moveTo(0, 0.14); forma.lineTo(0.11, 0.1); forma.lineTo(0.11, 0.01);
      forma.quadraticCurveTo(0.11, -0.1, 0, -0.15); forma.quadraticCurveTo(-0.11, -0.1, -0.11, 0.01);
      forma.lineTo(-0.11, 0.1); forma.closePath();
      const geo = new THREE.ExtrudeGeometry(forma, { depth: 0.03, bevelEnabled: true, bevelThickness: 0.01, bevelSize: 0.01, bevelSegments: 2 });
      const g = new THREE.Group();
      g.add(malha(geo, '#b91c1c', { r: 0.45, m: 0.15 }));
      const traco = (x: number, y: number, comp: number, ang: number) => {
        const t = malha(new THREE.BoxGeometry(comp, 0.022, 0.01), MASCARA);
        t.position.set(x, y, 0.045); t.rotation.z = ang; g.add(t);
      };
      traco(-0.025, -0.01, 0.06, -0.8); traco(0.03, 0.01, 0.1, 0.95);
      g.position.set(-0.06, -0.22, 0.2); g.rotation.set(-0.05, 0.5, 0.05);
      asaE.add(g);
    },
  };
  const CABECA = new Set(['capacete', 'gorro', 'bone', 'chapeu']);

  const modelos = new Map<string, Modelo>();

  function construir(c: CoresDaCoruja, acessorios: Record<string, string>): Modelo {
    const raiz = new THREE.Group();
    const corpo = new THREE.Group();
    raiz.add(corpo);
    corpo.add(esf(0.42, c.penas, [0, 0.5, 0], [1, 1.12, 0.86], { r: 0.78 }));
    corpo.add(esf(0.285, c.barriga, [0, 0.36, 0.20], [1, 1.02, 0.58], { r: 0.85 }));
    [-1, 0, 1].forEach(s => {
      const pena = esf(0.1, c.asas, [s * 0.04, 0.22, -0.29], [0.42, 0.55, 0.9], { r: 0.8 });
      pena.rotation.y = s * 0.12;
      corpo.add(pena);
    });
    [[-0.07, 0.42], [0.07, 0.42], [0, 0.32]].forEach(([x, y]) => {
      const v = new THREE.Mesh(new THREE.TorusGeometry(0.035, 0.007, 6, 16, Math.PI), mat(escurecer(c.barriga, 0.3), { r: 0.9 }));
      v.position.set(x, y, 0.385); v.rotation.z = Math.PI;
      corpo.add(v);
    });
    const pecas = Object.values(acessorios);
    const comChapeu = pecas.some(p => CABECA.has(p));
    [-1, 1].forEach((s) => {
      // Os tufos somem debaixo de chapéu e capacete.
      if (!comChapeu) {
        const tufo = malha(new THREE.ConeGeometry(0.09, 0.19, 20), c.asas, { r: 0.8 });
        tufo.position.set(0.2 * s, 0.93, -0.02); tufo.rotation.set(-0.12, 0, -0.35 * s);
        corpo.add(tufo);
      }
      corpo.add(esf(0.165, MASCARA, [0.14 * s, 0.665, 0.29], [1, 1, 0.56], { r: 0.8 }));
    });
    corpo.add(esf(0.1, MASCARA, [0, 0.585, 0.33], [1, 0.85, 0.56], { r: 0.8 }));
    const olhos = new THREE.Group();
    olhos.position.y = 0.67;
    [-1, 1].forEach((s) => {
      const o = new THREE.Group();
      o.position.set(0.14 * s, 0, 0.36);
      o.add(esf(0.092, '#141218', [0, 0, 0], [1, 1, 0.45], { r: 0.3 }));
      o.add(esf(0.064, c.olho, [0, 0, 0.03], [1, 1, 0.4], { r: 0.2, e: c.olho, ei: 0.3 }));
      o.add(esf(0.032, '#07060a', [0, 0, 0.052], [1, 1, 0.35], { r: 0.2 }));
      o.add(esf(0.021, '#ffffff', [0.03, 0.033, 0.066], [1, 1, 0.4], { e: '#ffffff', ei: 1 }));
      o.add(esf(0.009, '#ffffff', [-0.028, -0.026, 0.063], [1, 1, 0.4], { e: '#ffffff', ei: 1 }));
      olhos.add(o);
    });
    corpo.add(olhos);
    const fechados = new THREE.Group();
    [-1, 1].forEach((s) => {
      const m = new THREE.Mesh(new THREE.TorusGeometry(0.058, 0.013, 8, 20, Math.PI), mat('#141218'));
      m.position.set(0.14 * s, 0.665, 0.38); m.rotation.z = Math.PI;
      fechados.add(m);
    });
    fechados.visible = false;
    corpo.add(fechados);
    const bico = malha(new THREE.ConeGeometry(0.052, 0.11, 24), OURO, { r: 0.45 });
    bico.position.set(0, 0.585, 0.4); bico.rotation.x = Math.PI / 2 + 0.5;
    corpo.add(bico);
    const asa = (s: number) => {
      const piv = new THREE.Group();
      piv.position.set(0.37 * s, 0.63, 0.02);
      const m = esf(0.17, c.asas, [0.035 * s, -0.2, 0], [0.42, 1.25, 0.86], { r: 0.6 });
      m.rotation.z = 0.18 * s;
      piv.add(m);
      corpo.add(piv);
      return piv;
    };
    const asaE = asa(-1), asaD = asa(1);
    const pes = [-1, 1].map((s) => { const p = esf(0.07, OURO, [0.11 * s, 0.03, 0.12], [1, 0.45, 1.35], { r: 0.4 }); raiz.add(p); return p; });
    pecas.forEach(p => PECAS[p]?.({ corpo, asaE, asaD }));
    juntarMalhas(corpo, new Set([olhos, fechados, asaE, asaD]));
    [olhos, fechados, asaE, asaD].forEach(g => juntarMalhas(g));
    raiz.scale.setScalar(ESCALA_DA_CORUJA);
    cena.add(raiz);
    const coresOriginais = new Map<THREE.MeshStandardMaterial, THREE.Color>();
    raiz.traverse(obj => {
      if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial) {
        coresOriginais.set(obj.material, obj.material.color.clone());
      }
    });
    return { raiz, corpo, olhos, fechados, asaE, asaD, pes, coresOriginais, pausado: false };
  }

  function soltar(m: Modelo) {
    cena.remove(m.raiz);
    m.raiz.traverse((obj) => {
      if (obj instanceof THREE.Mesh) {
        obj.geometry.dispose();
        (Array.isArray(obj.material) ? obj.material : [obj.material]).forEach(x => x.dispose());
      }
    });
  }

  const difAng = (a: number, b: number) => { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; };

  function posar(chaveModelo: string, o: CorujaAnimada, dt: number, reduzir: boolean) {
    const m = modelos.get(chaveModelo);
    if (!m) return;
    const pausado = o.pose === 'pausado';
    if (m.pausado !== pausado) {
      m.pausado = pausado;
      m.coresOriginais.forEach((cor, material) => {
        material.color.copy(cor);
        if (pausado) {
          const cinza = (cor.r + cor.g + cor.b) / 3;
          material.color.setRGB(cinza * 0.7, cinza * 0.7, cinza * 0.7);
        }
      });
    }
    o.yaw += difAng(o.yaw, o.yawAlvo) * Math.min(1, dt * 7);
    m.raiz.rotation.y = o.yaw;
    const f = reduzir ? 0 : o.fase, dorme = o.pose === 'dormindo';
    let sobe = 0, rola = 0, inclina = 0, respira = 1, asaE = -0.04, asaD = 0.04;
    if (o.andando && !pausado) {
      sobe = Math.abs(Math.sin(f)) * 0.045;
      rola = Math.sin(f) * 0.09;
      asaE = -0.12 - Math.abs(Math.sin(f)) * 0.12; asaD = -asaE;
    } else if (o.pose === 'esperando') {
      sobe = Math.abs(Math.sin(f * 2.2)) * 0.07;
      asaD = 1.9 + Math.sin(f * 6) * 0.35;
    } else if (dorme || o.pose === 'pausado') {
      respira = 1 + Math.sin(f * 0.6) * 0.025;
      rola = 0.13; inclina = 0.08;
    } else if (o.falando) {
      respira = 1 + Math.sin(f) * 0.012;
      asaD = 0.35 + Math.sin(f * 4.5) * 0.3; inclina = 0.03;
    } else if (o.pose === 'trabalhando') {
      respira = 1 + Math.sin(f) * 0.012;
      asaD = 0.12 + Math.max(0, Math.sin(f * 4)) * 0.12;
      asaE = -0.12 - Math.max(0, Math.sin(f * 4 + 1.6)) * 0.08;
      inclina = 0.06;
    } else {
      respira = 1 + Math.sin(f) * 0.014;
    }
    if (reduzir) { sobe = 0; rola = 0; respira = 1; asaE = -0.04; asaD = 0.04; }
    m.corpo.position.y = sobe;
    m.corpo.rotation.set(inclina, 0, rola);
    m.corpo.scale.set(1, respira, 1);
    m.asaE.rotation.z = asaE;
    m.asaD.rotation.z = asaD;
    m.pes[0].position.y = 0.03 + (o.andando ? Math.max(0, Math.sin(f)) * 0.045 : 0);
    m.pes[1].position.y = 0.03 + (o.andando ? Math.max(0, -Math.sin(f)) * 0.045 : 0);
    const pisca = o.piscandoAte && performance.now() < o.piscandoAte;
    const fechado = dorme || o.pose === 'pausado';
    m.olhos.visible = !fechado;
    m.fechados.visible = fechado || !!pisca;
    m.olhos.scale.y = pisca ? 0.12 : 1;
  }

  // As máscaras escrevem só profundidade: o móvel visível permanece no SVG.
  const mascara = new THREE.MeshBasicMaterial({ colorWrite: false });
  const obstaculos = new THREE.Group();
  obstaculos.name = 'esc-obstaculos';
  cena.add(obstaculos);
  const bloco = (x: number, y: number, z: number, w: number, d: number, h: number) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mascara);
    m.position.set(x + w / 2, z + h / 2, y + d / 2);
    m.renderOrder = -1;
    obstaculos.add(m);
  };
  Object.values(TAMPOS).forEach(([x, y, z, w, d, h]) => bloco(x, y, z, w, d, h));
  bloco(0.12, 2.15, 0, 0.82, 0.55, 0.7);
  bloco(0.12, 3.85, 0, 0.82, 0.55, 0.7);
  bloco(1.55, 0.15, 0, 0.6, 0.95, 0.7);
  bloco(3.95, 0.15, 0, 0.6, 0.95, 0.7);
  bloco(0.3, 2.62, 1.04, 0.08, 1.3, 0.78);
  bloco(1.75, 0.34, 1, 1.1, 0.07, 0.72);
  bloco(3, 0.34, 1, 1.1, 0.07, 0.72);
  const tampo = new THREE.Mesh(new THREE.CylinderGeometry(MESA.r, MESA.r, 0.08, 48), mascara);
  tampo.position.set(MESA.x, 0.72, MESA.y);
  tampo.renderOrder = -1;
  obstaculos.add(tampo);
  bloco(MESA.x - 0.17, MESA.y - 0.17, 0, 0.34, 0.34, 0.68);
  bloco(0.12, 6.45, 0, 0.32, 2.9, 1);
  bloco(0.12, 6.3, 0, 1.15, 0.22, 0.62);
  bloco(0.12, 9.3, 0, 1.15, 0.22, 0.62);
  bloco(10.9, 4.6, 0, 0.95, 2, 0.85);
  bloco(11.2, 4.72, 0.92, 0.5, 0.42, 0.68);
  bloco(RACK.x, RACK.y, 0, RACK.w, RACK.d, RACK.h);
  bloco(MESINHA.x, MESINHA.y, 0, MESINHA.w, MESINHA.d, MESINHA.h);
  bloco(MESA.x - 0.75, MESA.y + 0.15, 0.79, 0.5, 0.04, 0.3);
  bloco(0.25, 4.68, 0, 0.62, 0.55, 0.7);
  bloco(5.2, 0, 0, 3.1, 0.85, 3.05);
  bloco(0.15, 0, 0, 1.15, 0.55, 2.7);
  bloco(9.3, 0, 0, 2.25, 0.32, 3.15);
  const cadeiras = new THREE.Group();
  cadeiras.name = 'esc-cadeiras';
  obstaculos.add(cadeiras);
  const limparCadeiras = () => {
    cadeiras.traverse(obj => { if (obj instanceof THREE.Mesh) obj.geometry.dispose(); });
    cadeiras.clear();
  };
  const recortes: THREE.Mesh[] = [];
  const recortar = (svg: string, x: number, y: number, z = 0) => {
    const m = recorte3D(svg, x, y, z, camera);
    if (m) { obstaculos.add(m); recortes.push(m); }
  };
  recortar(vaso(MESA.x + 0.15, MESA.y - 0.25, 0.5, 'arbusto', 'terra', 0.76), MESA.x + 0.15, MESA.y - 0.25, 0.76);
  recortar(vaso(11.3, 9.3, 1.1, 'figueira', 'terra'), 11.3, 9.3);
  recortar(vaso(6.6, 9.45, 1, 'costela', 'creme'), 6.6, 9.45);
  recortar(luminaria(3.6, 9.25), 3.6, 9.25);
  recortar(lixeira(), 4.88, 0.78);

  const sombras = new Map<string, THREE.Mesh>();
  const aneis = new Map<string, THREE.Mesh>();
  const geometriaDoAnel = new THREE.RingGeometry(0.52, 0.55, 40);
  const geometriaDaSombra = new THREE.CircleGeometry(0.45, 24);
  const materialDaSombra = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true,
    opacity: 0.2, depthWrite: false });
  let largura = QUADRO_DA_SALA.largura, altura = QUADRO_DA_SALA.altura;
  let vivo = true;

  return {
    canvas: renderer.domElement,
    assentos(lista) {
      limparCadeiras();
      for (const p of lista) {
        const cadeira = new THREE.Group();
        cadeira.position.set(p.x, 0, p.y);
        cadeira.rotation.y = -p.angulo;
        for (const [x, y, z, w, d, h] of PARTES_DA_CADEIRA) {
          const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mascara);
          m.position.set(x + w / 2, z + h / 2, y + d / 2);
          m.renderOrder = -1;
          cadeira.add(m);
        }
        cadeiras.add(cadeira);
      }
    },
    montar(chaveModelo, coruja) {
      const antigo = modelos.get(chaveModelo);
      if (antigo) soltar(antigo);
      const modelo = construir(coruja.cores, coruja.acessorios);
      modelo.raiz.name = 'esc-coruja3d';
      modelos.set(chaveModelo, modelo);
      const antigoAnel = aneis.get(chaveModelo);
      if (antigoAnel) { cena.remove(antigoAnel); (antigoAnel.material as THREE.Material).dispose(); }
      const anel = new THREE.Mesh(geometriaDoAnel, new THREE.MeshBasicMaterial({ color: coruja.cores.olho,
        transparent: true, opacity: 0.9, depthWrite: false, side: THREE.DoubleSide }));
      anel.rotation.x = -Math.PI / 2;
      anel.visible = antigoAnel?.visible ?? false;
      aneis.set(chaveModelo, anel);
      cena.add(anel);
      if (!sombras.has(chaveModelo)) {
        const sombra = new THREE.Mesh(geometriaDaSombra, materialDaSombra);
        sombra.rotation.x = -Math.PI / 2;
        sombras.set(chaveModelo, sombra);
        cena.add(sombra);
      }
    },
    posar,
    posicionar(chaveModelo, x, y, z) {
      const m = modelos.get(chaveModelo);
      if (m) m.raiz.position.set(x, z, y);
      sombras.get(chaveModelo)?.position.set(x, z + 0.01, y);
      aneis.get(chaveModelo)?.position.set(x, z + 0.015, y);
    },
    destacar(chaveModelo, visivel) {
      const anel = aneis.get(chaveModelo);
      if (anel) anel.visible = visivel;
    },
    desenhar() {
      if (vivo) renderer.render(cena, camera);
    },
    async preparar() {
      if (vivo) await renderer.compileAsync(cena, camera);
    },
    resolucao(w, h) {
      const novaLargura = Math.max(1, Math.round(w)), novaAltura = Math.max(1, Math.round(h));
      if (novaLargura === largura && novaAltura === altura) return;
      largura = novaLargura; altura = novaAltura;
      renderer.setSize(largura, altura, false);
    },
    medicao() {
      return { chamadas: renderer.info.render.calls, triangulos: renderer.info.render.triangles };
    },
    retrato(chaveModelo) {
      const m = modelos.get(chaveModelo);
      if (!m) return '';
      const retrato = new THREE.Scene();
      const corpo = m.raiz.clone(true);
      corpo.position.set(0, 0, 0);
      corpo.scale.setScalar(1);
      corpo.rotation.y = Math.PI / 4;
      retrato.add(corpo, new THREE.HemisphereLight(0xdfe8ff, 0x6b4a32, PI));
      const luz = new THREE.DirectionalLight(0xffe7c7, 1.25 * PI);
      luz.position.set(-1.4, 2.6, 2.4);
      retrato.add(luz);
      // A captura da ficha não altera posição, pose ou recursos do residente.
      try {
        renderer.setSize(176, 200, false);
        renderer.render(retrato, cam);
        return renderer.domElement.toDataURL('image/png');
      } finally {
        renderer.setSize(largura, altura, false);
        renderer.render(cena, camera);
      }
    },
    remover(chaveModelo) {
      const m = modelos.get(chaveModelo);
      if (m) soltar(m);
      modelos.delete(chaveModelo);
      const sombra = sombras.get(chaveModelo);
      if (sombra) cena.remove(sombra);
      sombras.delete(chaveModelo);
      const anel = aneis.get(chaveModelo);
      if (anel) { cena.remove(anel); (anel.material as THREE.Material).dispose(); }
      aneis.delete(chaveModelo);
    },
    destruir() {
      vivo = false;
      modelos.forEach(soltar);
      modelos.clear();
      sombras.clear();
      aneis.forEach(anel => (anel.material as THREE.Material).dispose());
      aneis.clear();
      geometriaDoAnel.dispose();
      geometriaDaSombra.dispose();
      materialDaSombra.dispose();
      obstaculos.traverse(obj => { if (obj instanceof THREE.Mesh) obj.geometry.dispose(); });
      recortes.forEach(m => (m.material as THREE.Material).dispose());
      mascara.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
}
