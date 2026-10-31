/** Reserva o espaço antes de importar o motor e mantém as camadas no mesmo plano. */
export const QUADRO_DO_ESCRITORIO = {
  position: 'relative', isolation: 'isolate', contain: 'layout paint',
  transform: 'translateZ(0)', overflow: 'hidden',
  width: 'min(100%, calc(clamp(260px, calc(100dvh - 16rem), 560px) * 1.2))',
  aspectRatio: '1.2', marginInline: 'auto',
} as const;

/** As animações do Escritório. Tudo preso a `.esc-raiz`, para não vazar no app. */
export const ESTILO_DO_ESCRITORIO = `
.esc-raiz {
  --esc-altura: clamp(260px, calc(100dvh - 16rem), 560px);
  position: relative; isolation: isolate; contain: layout paint;
  transform: translateZ(0); overflow: hidden;
  width: min(100%, calc(var(--esc-altura) * var(--esc-proporcao, 1.2)));
  aspect-ratio: var(--esc-proporcao, 1.2);
  margin-inline: auto;
}
.esc-raiz > svg, .esc-raiz > .esc-canvas3d {
  display: block; position: absolute; inset: 0;
  width: 100%; height: 100%; margin: 0; pointer-events: none;
}
.esc-raiz .esc-canvas3d { z-index: 1; }
.esc-raiz svg.esc-overlay { z-index: 2; }
.esc-raiz .esc-coruja { cursor: pointer; outline: none; pointer-events: all; }
.esc-raiz .esc-coruja:focus-visible .esc-anel { opacity: 1; }
.esc-raiz .esc-anel { opacity: 0; transition: opacity .2s; }
.esc-raiz .esc-coruja.esc-selecionada .esc-anel, .esc-raiz .esc-coruja:hover .esc-anel { opacity: 1; }
.esc-raiz .esc-pausada .esc-corpo3d, .esc-raiz .esc-pausada .esc-plana { filter: grayscale(1) brightness(.85); opacity: .6; }
.esc-raiz .esc-etiqueta, .esc-raiz .esc-balao { pointer-events: none; }
.esc-raiz .esc-etiqueta { transition: opacity .45s ease; }
.esc-raiz .esc-z { animation: esc-sobe 2.6s ease-in infinite; opacity: 0; }
.esc-raiz .esc-z2 { animation-delay: .85s; } .esc-raiz .esc-z3 { animation-delay: 1.7s; }
@keyframes esc-sobe { 0% { opacity: 0; transform: translate(0, 4px); } 25% { opacity: .9; } 100% { opacity: 0; transform: translate(6px, -14px); } }
.esc-raiz .esc-brilho { animation: esc-brilha 1.6s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
.esc-raiz .esc-b2 { animation-delay: .7s; }
@keyframes esc-brilha { 0%, 100% { opacity: .2; transform: scale(.6); } 50% { opacity: 1; transform: scale(1); } }
.esc-raiz .esc-exclama { animation: esc-pulsa 1s ease-in-out infinite; transform-box: fill-box; transform-origin: 30% 100%; }
@keyframes esc-pulsa { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.12); } }
.esc-raiz .esc-celula { animation: esc-respira 4.5s ease-in-out infinite; }
@keyframes esc-respira { 0%, 100% { opacity: .78; } 50% { opacity: 1; } }
.esc-raiz .esc-rede { transform-box: fill-box; transform-origin: center; animation: esc-gira 40s linear infinite; }
@keyframes esc-gira { to { transform: rotate(360deg); } }
.esc-raiz .esc-linhas-codigo { animation: esc-rola 7s linear infinite; }
@keyframes esc-rola { from { transform: translateY(0); } to { transform: translateY(-1.6px); } }
.esc-raiz .esc-vapor { opacity: 0; transition: opacity .4s; }
.esc-raiz .esc-vapor.esc-ligado { opacity: 1; }
.esc-raiz .esc-vapor path { animation: esc-fumaca 1.8s ease-in-out infinite; }
.esc-raiz .esc-vapor path:nth-child(2) { animation-delay: .6s; } .esc-raiz .esc-vapor path:nth-child(3) { animation-delay: 1.2s; }
@keyframes esc-fumaca { 0% { opacity: 0; transform: translateY(3px); } 40% { opacity: .8; } 100% { opacity: 0; transform: translateY(-9px); } }
.esc-raiz .esc-led { opacity: .16; }
.esc-raiz .esc-led-linha.esc-ativo .esc-led { animation: esc-led .8s steps(2, jump-none) infinite; }
@keyframes esc-led { 0% { opacity: .3; } 100% { opacity: 1; } }
.esc-raiz .esc-pulsando { animation: esc-chama 1.4s ease-in-out infinite; }
@keyframes esc-chama { 0%, 100% { opacity: .12; } 50% { opacity: .6; } }
.esc-raiz #esc-farol { fill: #4a4232; transition: fill .3s; }
.esc-raiz #esc-farol.esc-aceso { fill: #f5c400; }
.esc-raiz #esc-farol-brilho { opacity: 0; }
.esc-raiz #esc-farol-brilho.esc-aceso { animation: esc-chama 1s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .esc-raiz .esc-z, .esc-raiz .esc-brilho, .esc-raiz .esc-exclama, .esc-raiz .esc-celula, .esc-raiz .esc-rede,
  .esc-raiz .esc-linhas-codigo, .esc-raiz .esc-led, .esc-raiz .esc-pulsando, .esc-raiz .esc-vapor path,
  .esc-raiz #esc-farol-brilho { animation: none !important; }
  .esc-raiz .esc-z { opacity: .8; }
  .esc-raiz .esc-led-linha.esc-ativo .esc-led { opacity: .9; }
  .esc-raiz .esc-pulsando, .esc-raiz #esc-farol-brilho.esc-aceso { opacity: .4; }
}
`;
