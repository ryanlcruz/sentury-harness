import * as THREE from 'three';
import { SVGLoader, type StrokeStyle } from 'three/addons/loaders/SVGLoader.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { iso, S } from './iso';

/** A silhueta do SVG cobre só o objeto, sem esconder os vãos entre as folhas. */
export function recorte3D(markup: string, x: number, y: number, z: number,
  camera: THREE.Camera): THREE.Mesh | null {
  const documento = new DOMParser().parseFromString(`<svg xmlns="http://www.w3.org/2000/svg">${markup}</svg>`, 'image/svg+xml');
  documento.querySelectorAll('[filter]').forEach(el => el.remove());
  const paths = new SVGLoader().parse(new XMLSerializer().serializeToString(documento)).paths;
  const geometrias: THREE.BufferGeometry[] = [];
  for (const path of paths) {
    const estilo = path.userData!.style as StrokeStyle & {
      fill: string; stroke: string; fillOpacity: number; strokeOpacity: number; opacity: number;
    };
    if (estilo.fill !== 'none' && estilo.fillOpacity > 0 && estilo.opacity > 0) {
      for (const forma of path.toShapes()) {
        const geo = new THREE.ShapeGeometry(forma, 8);
        geometrias.push(geo.toNonIndexed()); geo.dispose();
      }
    }
    if (estilo.stroke !== 'none' && estilo.strokeOpacity > 0 && estilo.opacity > 0) {
      for (const sub of path.subPaths) {
        const geo = SVGLoader.pointsToStroke(sub.getPoints(8), estilo);
        if (geo) geometrias.push(geo);
      }
    }
  }
  if (!geometrias.length) return null;
  const geometria = mergeGeometries(geometrias);
  geometrias.forEach(g => g.dispose());
  if (!geometria) return null;
  const [sx, sy] = iso(x, y, z), escala = S * Math.sqrt(1.5);
  const pos = geometria.getAttribute('position');
  for (let i = 0; i < pos.count; i++) {
    pos.setXYZ(i, (pos.getX(i) - sx) / escala, -(pos.getY(i) - sy) / escala, 0);
  }
  pos.needsUpdate = true;
  const mesh = new THREE.Mesh(geometria, new THREE.MeshBasicMaterial({ colorWrite: false, side: THREE.DoubleSide }));
  mesh.position.set(x, z, y);
  mesh.quaternion.copy(camera.quaternion);
  mesh.renderOrder = -1;
  return mesh;
}
