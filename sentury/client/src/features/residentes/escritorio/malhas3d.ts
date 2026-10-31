import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

/** Peças que não se movem entre si compartilham uma chamada de desenho por material. */
export function juntarMalhas(grupo: THREE.Group, preservar = new Set<THREE.Object3D>()) {
  grupo.updateMatrixWorld(true);
  const inversa = grupo.matrixWorld.clone().invert();
  const porMaterial = new Map<string, THREE.Mesh[]>();
  const visitar = (obj: THREE.Object3D) => {
    if (preservar.has(obj)) return;
    if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial && !obj.material.transparent) {
      const m = obj.material;
      const chave = [m.color.getHex(), m.roughness, m.metalness, m.emissive.getHex(), m.emissiveIntensity, m.side].join(':');
      const partes = porMaterial.get(chave) ?? [];
      partes.push(obj); porMaterial.set(chave, partes);
    }
    obj.children.forEach(visitar);
  };
  grupo.children.forEach(visitar);
  porMaterial.forEach(partes => {
    if (partes.length < 2) return;
    const geometrias = partes.map(p => {
      const geo = p.geometry.index ? p.geometry.toNonIndexed() : p.geometry.clone();
      return geo.applyMatrix4(inversa.clone().multiply(p.matrixWorld));
    });
    const unida = mergeGeometries(geometrias);
    geometrias.forEach(g => g.dispose());
    if (!unida) return;
    const materiais = new Set<THREE.Material>();
    partes.forEach(p => { p.removeFromParent(); p.geometry.dispose(); materiais.add(p.material as THREE.Material); });
    materiais.delete(partes[0].material as THREE.Material);
    materiais.forEach(m => m.dispose());
    grupo.add(new THREE.Mesh(unida, partes[0].material));
  });
}
