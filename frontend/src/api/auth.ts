import client from './client';

export interface LoginResponse {
  session_id: string;
  csrf_token: string;
  username: string;
  is_super_admin: boolean;
}

export interface MfaRequiredResponse {
  require_mfa: boolean;
  step: string;
}

export interface MfaSetupRequiredResponse {
  require_mfa_setup: boolean;
  totp_uri: string;
  secret: string;
  step: string;
}

export type LoginStep1Result = LoginResponse | MfaRequiredResponse | MfaSetupRequiredResponse;

export async function loginPassword(username: string, password: string): Promise<LoginStep1Result> {
  const { data } = await client.post('/auth/login', { username, password });
  return data;
}

export async function verifyMfa(code: string): Promise<LoginResponse> {
  const { data } = await client.post('/auth/login/verify-mfa', { code });
  return data;
}

export async function loginRecovery(username: string, password: string, recoveryCode: string): Promise<LoginResponse> {
  const { data } = await client.post('/auth/login/recovery', { username, password, recovery_code: recoveryCode });
  return data;
}

export async function bindMfa(secret: string, code: string): Promise<{ recovery_codes: string[] }> {
  const { data } = await client.post('/auth/mfa/bind', { secret, code });
  return data;
}

export async function logout(): Promise<void> {
  await client.post('/auth/logout');
}

export interface SessionInfo {
  account_id: string;
  username: string;
  is_super_admin: boolean;
  source_ip: string;
  created_at: string;
}

export async function getSession(): Promise<SessionInfo> {
  const { data } = await client.get('/auth/session');
  return data;
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await client.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword });
}

export async function fetchCsrfToken(): Promise<string> {
  const { data } = await client.get('/auth/csrf-token');
  return data.csrf_token;
}
