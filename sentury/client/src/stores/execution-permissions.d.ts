import type { PermissaoPayload } from '../contracts/events/session-events';

export interface ExecutionPermissionState {
  executionIds: string[];
  pendingByExecutionId: Record<string, PermissaoPayload>;
}

export function createExecutionPermissionState(): ExecutionPermissionState;
export function registerExecution(
  state: ExecutionPermissionState,
  executionId: string,
): ExecutionPermissionState;
export function attachExecutionPermission(
  state: ExecutionPermissionState,
  executionId: string,
  permission: PermissaoPayload,
): ExecutionPermissionState;
export function resolveExecutionPermission(
  state: ExecutionPermissionState,
  executionId: string,
): ExecutionPermissionState;
export function permissionForExecution(
  state: ExecutionPermissionState,
  executionId: string,
): PermissaoPayload | undefined;
