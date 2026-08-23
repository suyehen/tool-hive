import client from './client';
import type { RoleItem } from './roles';

export interface AccountItem {
  id: string;
  account: string;
  real_name: string;
  is_super_admin: boolean;
  email: string | null;
  mobile: string | null;
  department: string | null;
  remark: string | null;
  account_type: string | null;
  external_user_id: string | null;
  status: string;
  login_failures: number;
  must_change_password: boolean;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface AccountListResponse {
  items: AccountItem[];
  total: number;
}

export interface AccountListQuery {
  keyword?: string;
  status?: string;
  department?: string;
}

export interface CreateAccountResponse {
  id: string;
  account: string;
  real_name: string;
  status: string;
  temp_password: string;
}

export async function listAccounts(
  offset = 0,
  limit = 50,
  query?: AccountListQuery,
): Promise<AccountListResponse> {
  const { data } = await client.get('/accounts', {
    params: {
      offset,
      limit,
      keyword: query?.keyword || undefined,
      status: query?.status || undefined,
      department: query?.department || undefined,
    },
  });
  return data;
}

export async function createAccount(
  account: string,
  realName: string,
  extra?: {
    external_user_id?: string;
    email?: string;
    mobile?: string;
    department?: string;
    remark?: string;
  },
): Promise<CreateAccountResponse> {
  const { data } = await client.post('/accounts', {
    account,
    real_name: realName,
    external_user_id: extra?.external_user_id,
    email: extra?.email,
    mobile: extra?.mobile,
    department: extra?.department,
    remark: extra?.remark,
  });
  return data;
}

export async function updateAccountProfile(
  id: string,
  params: {
    real_name?: string;
    email?: string;
    mobile?: string;
    department?: string;
    remark?: string;
    row_version: number;
  },
): Promise<AccountItem> {
  const { data } = await client.patch(`/accounts/${id}`, params);
  return data;
}

export async function updateAccountStatus(
  id: string,
  action: 'enable' | 'disable' | 'unlock',
): Promise<void> {
  await client.patch(`/accounts/${id}/status`, { action });
}

export async function listAccountRoles(accountId: string): Promise<RoleItem[]> {
  const { data } = await client.get(`/accounts/${accountId}/roles`);
  return data;
}

export async function assignRoleToAccount(accountId: string, roleId: string): Promise<void> {
  await client.post(`/accounts/${accountId}/roles`, { role_id: roleId });
}

export async function removeRoleFromAccount(accountId: string, roleId: string): Promise<void> {
  await client.delete(`/accounts/${accountId}/roles/${roleId}`);
}

export async function resetPassword(id: string): Promise<{ temp_password: string }> {
  const { data } = await client.post(`/accounts/${id}/reset-password`);
  return data;
}

export async function forceLogout(id: string): Promise<void> {
  await client.post(`/accounts/${id}/force-logout`);
}

export async function offboardAccount(id: string): Promise<void> {
  await client.post(`/accounts/${id}/offboard`);
}
