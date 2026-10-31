import React from 'react';

/** O residente desenhado por camadas, todas no mesmo quadro de 120 por 120:
 * qualquer peça encaixa com qualquer outra. A ordem dos encaixes é fixa. */

export type EstadoCoruja = 'parado' | 'dormindo' | 'trabalhando' | 'esperando' | 'pausado';

export interface CoresCoruja {
  penas: string;
  asas: string;
  barriga: string;
  marcas?: string;
  /** A íris, da plumagem. Sem ela o olho fica preto com o brilho dourado, como o do Sentury. */
  olho?: string;
}

export const CORES_DO_SENTURY: CoresCoruja = { penas: '#161616', asas: '#232323', barriga: '#f5c400', marcas: '#8a6a00' };

const OURO = '#f5c400';
const TINTA = '#161616';
const MASCARA = '#fffdf8';
const ORDEM = ['pescoco', 'rosto', 'ouvidos', 'cabeca', 'asa'] as const;

type Peca = (lanterna: string) => React.ReactNode;

const PECAS: Record<string, Record<string, Peca>> = {
  cabeca: {
    capacete: lanterna => (
      <>
        <path d="M38 34 C38 11 82 11 82 34 Z" fill={OURO} />
        <rect x="57" y="12" width="6" height="22" rx="3" fill="#d9ab00" />
        <rect x="31" y="31" width="58" height="6" rx="3" fill="#d9ab00" />
        <circle className={lanterna} cx="60" cy="23" r="3.5" fill="#fff6c2" />
      </>
    ),
    gorro: () => (
      <>
        <path d="M37 35 C37 9 83 9 83 35 Z" fill="#c2410c" />
        <rect x="35" y="29" width="50" height="8" rx="4" fill="#9a3412" />
        <circle cx="60" cy="10" r="5" fill="#fef3c7" />
      </>
    ),
    bone: () => (
      <>
        <path d="M38 35 C38 13 82 13 82 35 Z" fill="#2563eb" />
        <path d="M60 31 L99 33 Q97 39 82 38 L60 36 Z" fill="#1d4ed8" />
        <circle cx="60" cy="14" r="2.5" fill="#1d4ed8" />
      </>
    ),
    chapeu: () => (
      <>
        <ellipse cx="60" cy="34" rx="32" ry="5" fill="#57534e" />
        <path d="M41 34 C41 14 79 14 79 34 Z" fill="#78716c" />
        <path d="M53 17 Q60 23 67 17" stroke="#57534e" strokeWidth="2" fill="none" />
        <rect x="41" y="27" width="38" height="5" fill="#292524" />
      </>
    ),
  },
  rosto: {
    oculos: () => (
      <>
        <circle cx="45" cy="54" r="12" stroke={TINTA} strokeWidth="2.5" fill="none" />
        <circle cx="75" cy="54" r="12" stroke={TINTA} strokeWidth="2.5" fill="none" />
        <line x1="57" y1="53" x2="63" y2="53" stroke={TINTA} strokeWidth="2.5" />
      </>
    ),
    escuros: () => (
      <>
        <rect x="32" y="46" width="25" height="15" rx="7" fill={TINTA} opacity=".94" />
        <rect x="63" y="46" width="25" height="15" rx="7" fill={TINTA} opacity=".94" />
        <line x1="57" y1="51" x2="63" y2="51" stroke={TINTA} strokeWidth="2.5" />
        <path d="M36 50 l5 -2 M67 50 l5 -2" stroke={MASCARA} strokeWidth="1.5" strokeLinecap="round" opacity=".7" />
      </>
    ),
    monoculo: () => (
      <>
        <circle cx="75" cy="54" r="12" stroke="#b45309" strokeWidth="2.5" fill="none" />
        <path d="M86 60 Q93 74 84 88" stroke="#b45309" strokeWidth="1.5" fill="none" />
      </>
    ),
  },
  ouvidos: {
    fone: () => (
      <>
        <path d="M21 60 C21 12 99 12 99 60" stroke="#2d2a26" strokeWidth="5" fill="none" strokeLinecap="round" />
        <rect x="13" y="52" width="11" height="20" rx="5.5" fill="#2d2a26" />
        <rect x="96" y="52" width="11" height="20" rx="5.5" fill="#2d2a26" />
        <path d="M18 71 C18 82 29 86 39 84" stroke="#2d2a26" strokeWidth="3" fill="none" strokeLinecap="round" />
        <circle cx="41" cy="84" r="3.5" fill="#2d2a26" />
      </>
    ),
  },
  pescoco: {
    gravata: () => (
      <>
        <path d="M56 77 L64 77 L62 82 L58 82 Z" fill="#2d2a26" />
        <path d="M58 82 L62 82 L65 96 L60 102 L55 96 Z" fill="#2d2a26" />
      </>
    ),
    borboleta: () => (
      <>
        <path d="M60 80 L48 73 L48 87 Z" fill="#b91c1c" />
        <path d="M60 80 L72 73 L72 87 Z" fill="#b91c1c" />
        <circle cx="60" cy="80" r="3.2" fill="#7f1d1d" />
      </>
    ),
    cachecol: () => (
      <>
        <path d="M30 74 Q60 88 90 74 L90 82 Q60 96 30 82 Z" fill="#c2410c" />
        <rect x="70" y="84" width="9" height="18" rx="3" fill="#9a3412" />
      </>
    ),
    cracha: () => (
      <>
        <path d="M42 74 L57 92 M78 74 L63 92" stroke="#2563eb" strokeWidth="2.5" strokeLinecap="round" />
        <rect x="51" y="90" width="18" height="14" rx="2" fill={MASCARA} stroke="#94a3b8" strokeWidth="1" />
        <rect x="54" y="93" width="6" height="6" rx="1" fill="#93c5fd" />
        <line x1="62" y1="95" x2="66" y2="95" stroke="#94a3b8" strokeWidth="1.5" />
      </>
    ),
  },
  asa: {
    chave: () => (
      <g transform="rotate(-20 20 96)">
        <path d="M14.5 78 v7 a5.5 5.5 0 0 0 11 0 v-7" stroke="#8a95a3" strokeWidth="4.5" fill="none" strokeLinecap="round" />
        <rect x="17.5" y="89" width="5" height="19" rx="2.5" fill="#8a95a3" />
      </g>
    ),
    lupa: () => (
      <>
        <circle cx="19" cy="88" r="7" stroke="#2d2a26" strokeWidth="3" fill="#e0f2fe" />
        <line x1="24" y1="93" x2="30" y2="100" stroke="#2d2a26" strokeWidth="4" strokeLinecap="round" />
      </>
    ),
    prancheta: () => (
      <>
        <rect x="9" y="82" width="19" height="24" rx="3" fill="#b07a45" />
        <rect x="12" y="87" width="13" height="16" rx="1" fill={MASCARA} />
        <rect x="14" y="80" width="9" height="4" rx="1.5" fill="#57534e" />
        <line x1="14" y1="91" x2="23" y2="91" stroke="#c9c0ac" strokeWidth="1.5" />
        <line x1="14" y1="95" x2="21" y2="95" stroke="#c9c0ac" strokeWidth="1.5" />
      </>
    ),
    notebook: () => (
      <>
        <rect x="8" y="80" width="24" height="17" rx="2" fill="#3f3f46" />
        <rect x="10.5" y="82.5" width="19" height="12" rx="1" fill="#93c5fd" />
        <rect x="5" y="96" width="30" height="4" rx="1.5" fill="#57534e" />
      </>
    ),
    caneca: () => (
      <>
        <rect x="10" y="87" width="15" height="17" rx="3" fill={MASCARA} stroke="#57534e" strokeWidth="2" />
        <path d="M25 91 q6 0 6 5 q0 5 -6 5" stroke="#57534e" strokeWidth="2.5" fill="none" />
        <path d="M14 83 q2 -3 0 -6 M20 83 q2 -3 0 -6" stroke="#a8a29e" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      </>
    ),
    escudo: () => (
      <>
        <path d="M20 80 L32 84 L32 94 Q32 104 20 108 Q8 104 8 94 L8 84 Z" fill="#b91c1c" stroke="#7f1d1d" strokeWidth="1.5" />
        <path d="M14.5 94 l4 4 l7 -8" stroke={MASCARA} strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
  },
};

const ROTULO_DO_ESTADO: Record<EstadoCoruja, string> = {
  parado: 'acordado', dormindo: 'dormindo', trabalhando: 'trabalhando', esperando: 'esperando você', pausado: 'pausado',
};

const Olhos: React.FC<{ estado: EstadoCoruja; iris?: string }> = ({ estado, iris }) => {
  if (estado === 'dormindo') {
    return (
      <>
        <path d="M37 55 q8 6 16 0" stroke={TINTA} strokeWidth="3" fill="none" strokeLinecap="round" />
        <path d="M67 55 q8 6 16 0" stroke={TINTA} strokeWidth="3" fill="none" strokeLinecap="round" />
      </>
    );
  }
  if (estado === 'pausado') {
    return (
      <>
        <rect x="38" y="53" width="14" height="3.5" rx="1.75" fill={TINTA} />
        <rect x="68" y="53" width="14" height="3.5" rx="1.75" fill={TINTA} />
      </>
    );
  }
  const r = estado === 'esperando' ? 9.5 : 8.5;
  return (
    <>
      {[45, 75].map(cx => (
        <g key={cx} className="res-pisca">
          <circle cx={cx} cy="54" r={r} fill={TINTA} />
          {iris ? (
            <>
              <circle cx={cx} cy="54" r={r * 0.7} fill={iris} />
              <circle cx={cx} cy="54" r={r * 0.36} fill={TINTA} />
              <circle cx={cx + 2.6} cy="51" r="2.2" fill="#fff" />
            </>
          ) : <circle cx={cx + 3} cy="51" r="3" fill={OURO} />}
        </g>
      ))}
    </>
  );
};

const PorFora: React.FC<{ estado: EstadoCoruja }> = ({ estado }) => {
  if (estado === 'dormindo') {
    return (
      <>
        {[[94, 34, 14, 'res-z'], [102, 24, 11, 'res-z res-z2'], [108, 15, 9, 'res-z res-z3']].map(([x, y, tamanho, classe]) => (
          <text key={String(classe)} className={String(classe)} x={x} y={y} fontSize={tamanho} fontWeight="700" fill="#7a7263" fontFamily="Geist, sans-serif">z</text>
        ))}
      </>
    );
  }
  if (estado === 'trabalhando') {
    return (
      <>
        <path className="res-luz" d="M104 30 l2 5 l5 2 l-5 2 l-2 5 l-2 -5 l-5 -2 l5 -2 Z" fill={OURO} />
        <path className="res-luz" style={{ animationDelay: '.6s' }} d="M12 34 l1.5 3.5 l3.5 1.5 l-3.5 1.5 l-1.5 3.5 l-1.5 -3.5 l-3.5 -1.5 l3.5 -1.5 Z" fill={OURO} />
      </>
    );
  }
  if (estado === 'esperando') {
    return (
      <g className="res-balao">
        <circle cx="104" cy="16" r="12" fill={OURO} />
        <path d="M96 24 L93 32 L102 27 Z" fill={OURO} />
        <rect x="102.5" y="8" width="3" height="10" rx="1.5" fill="#1a1a1a" />
        <circle cx="104" cy="22" r="1.8" fill="#1a1a1a" />
      </g>
    );
  }
  return null;
};

interface CorujaProps {
  cores: CoresCoruja;
  acessorios?: Record<string, string>;
  estado?: EstadoCoruja;
  tamanho?: number;
  /** Nome para leitor de tela; o estado entra junto. */
  rotulo: string;
  className?: string;
}

export const Coruja: React.FC<CorujaProps> = ({ cores, acessorios = {}, estado = 'parado', tamanho = 120, rotulo, className }) => {
  const anim = estado === 'dormindo' ? 'res-respira' : estado === 'trabalhando' ? 'res-trabalha' : estado === 'esperando' ? 'res-pula' : undefined;
  const lanterna = estado === 'trabalhando' ? 'res-luz' : '';
  return (
    <svg
      width={tamanho}
      height={tamanho}
      viewBox="0 0 120 120"
      role="img"
      aria-label={`${rotulo}, ${ROTULO_DO_ESTADO[estado]}`}
      // Avatar pequeno fica parado: piscar e respirar nem se veem nesse tamanho, e
      // cada animação vira uma camada que o navegador pode desenhar fora do lugar
      // quando a página rola.
      className={[className, tamanho < 64 ? 'res-parada' : ''].filter(Boolean).join(' ') || undefined}
      style={estado === 'pausado' ? { filter: 'grayscale(1)', opacity: 0.55 } : undefined}
    >
      <ellipse cx="60" cy="113" rx="30" ry="4.5" fill="#1a1a1a" opacity=".13" />
      <g className={anim}>
        <ellipse cx="51" cy="108" rx="6" ry="3" fill={OURO} />
        <ellipse cx="69" cy="108" rx="6" ry="3" fill={OURO} />
        <path d="M30 44 L24 17 L46 33 Z" fill={cores.penas} />
        <path d="M90 44 L96 17 L74 33 Z" fill={cores.penas} />
        <ellipse cx="60" cy="70" rx="36" ry="40" fill={cores.penas} />
        <ellipse cx="60" cy="90" rx="21" ry="17" fill={cores.barriga} />
        <path d="M52 86 q3 3 6 0 M62 86 q3 3 6 0 M57 94 q3 3 6 0" stroke={cores.marcas || cores.penas} strokeWidth="1.5" fill="none" opacity=".45" />
        <ellipse cx="26" cy="80" rx="9" ry="20" fill={cores.asas} />
        {estado === 'esperando'
          ? <g className="res-acena"><ellipse cx="99" cy="60" rx="8" ry="18" fill={cores.asas} transform="rotate(35 99 74)" /></g>
          : <ellipse cx="94" cy="80" rx="9" ry="20" fill={cores.asas} />}
        <circle cx="45" cy="54" r="17" fill={MASCARA} />
        <circle cx="75" cy="54" r="17" fill={MASCARA} />
        <ellipse cx="60" cy="63" rx="11" ry="9" fill={MASCARA} />
        <Olhos estado={estado} iris={cores.olho} />
        <path d="M60 60 L65.5 67 L60 75 L54.5 67 Z" fill={OURO} stroke={TINTA} strokeWidth="1.5" strokeLinejoin="round" />
        {ORDEM.map(encaixe => {
          const peca = PECAS[encaixe]?.[acessorios[encaixe] || ''];
          return peca ? <g key={encaixe}>{peca(lanterna)}</g> : null;
        })}
      </g>
      <PorFora estado={estado} />
    </svg>
  );
};

/** O lugar do próximo residente: o contorno, sem cara ainda. */
export const CorujaVazia: React.FC<{ tamanho?: number }> = ({ tamanho = 120 }) => {
  const traco = { fill: 'none', stroke: '#b5ab95', strokeWidth: 2, strokeDasharray: '5 4' };
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 120 120" role="img" aria-label="Lugar para um novo residente">
      <ellipse cx="60" cy="113" rx="30" ry="4.5" fill="#1a1a1a" opacity=".08" />
      <path d="M30 44 L24 17 L46 33" {...traco} />
      <path d="M90 44 L96 17 L74 33" {...traco} />
      <ellipse cx="60" cy="70" rx="36" ry="40" {...traco} />
      <path d="M53 60 q0 -7 7 -7 q7 0 7 7 q0 5 -7 7 v4" stroke="#b5ab95" strokeWidth="3" fill="none" strokeLinecap="round" />
      <circle cx="60" cy="79" r="2" fill="#b5ab95" />
    </svg>
  );
};
