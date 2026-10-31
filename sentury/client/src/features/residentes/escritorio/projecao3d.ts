import { OrthographicCamera } from 'three';
import { S } from './iso';

export const QUADRO_DA_SALA = { x: -400, y: -215, largura: 840, altura: 700 };
export const ESCALA_DA_CORUJA = 1.35;

/** A câmera usa a mesma projeção do SVG; x e y da sala ficam no chão. */
export function cameraDaSala() {
  const { x, y, largura, altura } = QUADRO_DA_SALA;
  const escala = S * Math.sqrt(1.5);
  const camera = new OrthographicCamera(x / escala, (x + largura) / escala,
    -y / escala, -(y + altura) / escala, 0.1, 150);
  camera.position.set(40, 40, 40);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  return camera;
}
