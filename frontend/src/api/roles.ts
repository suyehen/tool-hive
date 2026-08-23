import client from './client';

export interface RoleItem {
  id: string;
  code: string;
  name: string;
  sort_order: number;
  is_builtin: boolean;
  description: string | null;
  is_super_admin: boolean;
  status: string;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface RoleListResponse {
  items: RoleItem[];
  total: number;
}

export interface RoleListQuery {
  keyword?: string;
  status?: string;
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

export async function listRoles(
  offset = 0,
  limit = 50,
  query?: RoleListQuery,
): Promise<RoleListResponse> {
  const { data } = await client.get('/roles', {
    params: {
      offset,
      limit,
      keyword: query?.keyword || undefined,
      status: query?.status || undefined,
    },
  });
  return data;
}

export async function createRole(
  code: string,
  name: string,
  params?: { sort_order?: number; description?: string },
): Promise<RoleItem> {
  const { data } = await client.post('/roles', {
    code,
    name,
    sort_order: params?.sort_order,
    description: params?.description,
  });
  return data;
}

export async function updateRole(
  id: string,
  params: {
    name?: string;
    description?: string;
    sort_order?: number;
    row_version?: number;
  },
): Promise<RoleItem> {
  const { data } = await client.patch(`/roles/${id}`, params);
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
