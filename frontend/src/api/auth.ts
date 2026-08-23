import client from './client';

export interface LoginResponse {
  session_id: string;
  csrf_token: string;
  account: string;
  must_change_password: boolean;
}

export interface CaptchaChallenge {
  captcha_id: string;
  image: string;
  expires_in_seconds: number;
}

export async function getCaptchaChallenge(): Promise<CaptchaChallenge> {
  const { data } = await client.post('/auth/captcha/challenge');
  return data;
}

export async function loginPassword(
  account: string,
  password: string,
  captchaId: string,
  captchaCode: string,
): Promise<LoginResponse> {
  const { data } = await client.post('/auth/login', {
    account,
    password,
    captcha_id: captchaId,
    captcha_code: captchaCode,
  });
  return data;
}

export async function logout(): Promise<void> {
  await client.post('/auth/logout');
}

export interface SessionInfo {
  account_id: string;
  account: string;
  source_ip: string;
  created_at: string;
}

export interface MeInfo {
  account_id: string;
  account: string;
  external_user_id: string | null;
  status: string;
  must_change_password: boolean;
  is_super_admin: boolean;
}

export interface OperationItemsResponse {
  operation_items: string[];
}

export async function getSession(): Promise<SessionInfo> {
  const { data } = await client.get('/auth/session');
  return data;
}

export async function getMe(): Promise<MeInfo> {
  const { data } = await client.get('/auth/me');
  return data;
}

export async function getOperationItems(): Promise<string[]> {
  const { data } = await client.get<OperationItemsResponse>('/auth/me/operation-items');
  return data.operation_items;
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await client.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword });
}

export async function fetchCsrfToken(): Promise<string> {
  const { data } = await client.get('/auth/csrf-token');
  return data.csrf_token;
}
