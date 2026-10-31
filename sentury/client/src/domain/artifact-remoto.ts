import type { FileArtifact } from '../contracts/domain/artifact';

export function referenciaDeArtefato(item: {
  id: string; sessionId: string; title: string; type: string; createdAt: number;
}): FileArtifact {
  return {
    id: item.id, sessionId: item.sessionId, title: item.title,
    createdAt: new Date(item.createdAt).toISOString(),
    type: 'file', formato: item.type,
    attachment: {
      artifact_id: item.id, type: item.type, filename: item.title, payload_persisted: true,
    },
  };
}
