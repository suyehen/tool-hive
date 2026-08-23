import client from './client';

export interface RoleItem {
  id: string;
  name: string;
  description: string | null;
  is_super_admin: boolean;
  status: string;
  created_at: string;
  updated_at: string | null;
}

export interface RoleListResponse {
  items: RoleItem[];
  total: number;
}

export interface OperationItem {
  operation_code: string;
  display_name: string;
  category: string;
  sort_order: number;
  description: string | null;
  status: string;
}

export interface RoleAccountItem {
  id: string;
  account: string;
  real_name: string;
  status: string;
}

export async function listRoles(offset = 0, limit = 50): Promise<RoleListResponse> {
  const { data } = await client.get('/roles', { params: { offset, limit } });
  return data;
}

export async function createRole(name: string, description?: string): Promise<RoleItem> {
  const { data } = await client.post('/roles', { name, description });
  return data;
}

export async function updateRole(id: string, name?: string, description?: string): Promise<RoleItem> {
  const { data } = await client.patch(`/roles/${id}`, { name, description });
  return data;
}

export async function updateRoleStatus(id: string, status: string): Promise<void> {
  await client.patch(`/roles/${id}/status`, { status });
}

export async function getRoleOperations(roleId: string): Promise<OperationItem[]> {
  const { data } = await client.get(`/roles/${roleId}/operations`);
  return data;
}

export async function assignOperations(roleId: string, operationCodes: string[]): Promise<void> {
  await client.post(`/roles/${roleId}/operations`, { operation_codes: operationCodes });
}

export async function removeOperations(roleId: string, operationCodes: string[]): Promise<void> {
  await client.delete(`/roles/${roleId}/operations`, { data: { operation_codes: operationCodes } });
}

export async function listAllOperations(): Promise<OperationItem[]> {
  const { data } = await client.get('/operations');
  return data;
}

export async function listRoleAccounts(roleId: string): Promise<RoleAccountItem[]> {
  const { data } = await client.get(`/roles/${roleId}/accounts`);
  return data;
}
