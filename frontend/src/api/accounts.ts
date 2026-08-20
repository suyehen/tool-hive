import client from './client';

export interface AccountItem {
  id: string;
  username: string;
  external_user_id: string | null;
  status: string;
  login_failures: number;
  must_change_password: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface AccountListResponse {
  items: AccountItem[];
  total: number;
}

export interface CreateAccountResponse {
  id: string;
  username: string;
  status: string;
  temp_password: string;
}

export async function listAccounts(offset = 0, limit = 50): Promise<AccountListResponse> {
  const { data } = await client.get('/accounts', { params: { offset, limit } });
  return data;
}

export async function createAccount(
  username: string,
  external_user_id?: string,
): Promise<CreateAccountResponse> {
  const { data } = await client.post('/accounts', { username, external_user_id });
  return data;
}

export async function updateAccountStatus(
  id: string,
  action: 'enable' | 'disable' | 'unlock',
): Promise<void> {
  await client.patch(`/accounts/${id}/status`, { action });
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
