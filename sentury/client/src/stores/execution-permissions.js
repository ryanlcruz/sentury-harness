/**
 * Estado puro das aprovacoes ligadas a blocos de execucao.
 *
 * O id e o mesmo emitido por `plan_update`/`tool_start` (por exemplo p1s0).
 * Manter o mapa por id, em vez de uma unica permissao no stream, permite dois
 * blocos pendentes ao mesmo tempo e faz aprovar/negar remover somente a caixa
 * que originou a decisao.
 */

export function createExecutionPermissionState() {
  return { executionIds: [], pendingByExecutionId: {} };
}

export function registerExecution(state, executionId) {
  const id = String(executionId || '').trim();
  if (!id) throw new Error('executionId obrigatorio');
  if (state.executionIds.includes(id)) return state;
  return { ...state, executionIds: [...state.executionIds, id] };
}

export function attachExecutionPermission(state, executionId, permission) {
  const id = String(executionId || '').trim();
  if (!state.executionIds.includes(id)) {
    throw new Error(`permissao recebida para execucao desconhecida: ${id}`);
  }
  return {
    ...state,
    pendingByExecutionId: {
      ...state.pendingByExecutionId,
      [id]: { ...permission },
    },
  };
}

export function resolveExecutionPermission(state, executionId) {
  const id = String(executionId || '').trim();
  if (!(id in state.pendingByExecutionId)) return state;
  const pendingByExecutionId = { ...state.pendingByExecutionId };
  delete pendingByExecutionId[id];
  return { ...state, pendingByExecutionId };
}

export function permissionForExecution(state, executionId) {
  return state.pendingByExecutionId[String(executionId || '').trim()];
}
