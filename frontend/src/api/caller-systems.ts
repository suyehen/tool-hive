import client from './client';

export interface CallerSystemItem {
  id: string;
  system_id: string;
  name: string;
  description: string | null;
  environment: string;
  department: string | null;
  owner: string | null;
  contact: string | null;
  status: string;
  effective_state: string;
  effective_from: string | null;
  effective_to: string | null;
  deactivated_reason: string | null;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface CallerSystemListResponse {
  items: CallerSystemItem[];
  total: number;
}

export interface PublicKeyItem {
  id: string;
  key_id: string;
  system_id: string;
  fingerprint: string;
  algorithm: string;
  status: string;
  effective_from: string;
  effective_to: string | null;
  created_at: string;
}

export interface IPRuleItem {
  id: string;
  system_id: string;
  ip_cidr: string;
  description: string | null;
  status: string;
  created_at: string;
}

export async function listCallerSystems(offset = 0, limit = 50): Promise<CallerSystemListResponse> {
  const { data } = await client.get('/caller-systems', { params: { offset, limit } });
  return data;
}

export async function createCallerSystem(params: {
  name: string;
  environment: string;
  description?: string;
  department?: string;
  owner?: string;
  contact?: string;
  effective_from?: string | null;
  effective_to?: string | null;
}): Promise<CallerSystemItem> {
  const { data } = await client.post('/caller-systems', params);
  return data;
}

export async function updateCallerSystem(
  systemId: string,
  params: Record<string, unknown>,
): Promise<CallerSystemItem> {
  const { data } = await client.patch(`/caller-systems/${systemId}`, params);
  return data;
}

export async function enableCallerSystem(systemId: string): Promise<void> {
  await client.post(`/caller-systems/${systemId}/enable`);
}

export async function disableCallerSystem(systemId: string, reason: string): Promise<void> {
  await client.post(`/caller-systems/${systemId}/disable`, { reason });
}

export async function reviveCallerSystem(systemId: string): Promise<void> {
  await client.post(`/caller-systems/${systemId}/revive`);
}

export async function revokeCallerSystem(systemId: string, reason: string): Promise<void> {
  await client.post(`/caller-systems/${systemId}/revoke`, { reason });
}

export async function listPublicKeys(systemId: string): Promise<PublicKeyItem[]> {
  const { data } = await client.get(`/caller-systems/${systemId}/keys`);
  return data;
}

export async function addPublicKey(systemId: string, publicKey: string, effectiveTo?: string): Promise<PublicKeyItem> {
  const { data } = await client.post(`/caller-systems/${systemId}/keys`, {
    public_key: publicKey,
    effective_to: effectiveTo || null,
  });
  return data;
}

export async function enablePublicKey(keyId: string): Promise<void> {
  await client.post(`/caller-systems/keys/${keyId}/enable`);
}

export async function disablePublicKey(keyId: string): Promise<void> {
  await client.post(`/caller-systems/keys/${keyId}/disable`);
}

export async function revokePublicKey(keyId: string): Promise<void> {
  await client.post(`/caller-systems/keys/${keyId}/revoke`);
}

export async function listIPRules(systemId: string): Promise<IPRuleItem[]> {
  const { data } = await client.get(`/caller-systems/${systemId}/ip-rules`);
  return data;
}

export async function addIPRule(systemId: string, ipCidr: string, description?: string): Promise<IPRuleItem> {
  const { data } = await client.post(`/caller-systems/${systemId}/ip-rules`, {
    ip_cidr: ipCidr,
    description: description || null,
  });
  return data;
}

export async function updateIPRuleStatus(ruleId: string, reason?: string): Promise<void> {
  await client.patch(`/caller-systems/ip-rules/${ruleId}/status`, { reason: reason || '' });
}
