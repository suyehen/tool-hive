import client from './client';

export interface CallerSystemItem {
  id: string;
  system_id: string;
  name: string;
  description: string | null;
  environment: string;
  belonging_party: string | null;
  code: string;
  owner: string | null;
  contact: string | null;
  owner_email: string | null;
  tags: string[];
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

export interface CallerSystemListQuery {
  keyword?: string;
  status?: string;
  environment?: string;
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

export interface RuntimePolicy {
  system_id: string;
  allowed_api_patterns: string[];
  qps_limit: number;
  concurrency_limit: number;
  quota_per_day: number;
  request_timeout_seconds: number;
  circuit_breaker_enabled: boolean;
  effective_from: string | null;
  effective_to: string | null;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export async function listCallerSystems(
  offset = 0,
  limit = 50,
  query?: CallerSystemListQuery,
): Promise<CallerSystemListResponse> {
  const { data } = await client.get('/caller-systems', {
    params: {
      offset,
      limit,
      keyword: query?.keyword || undefined,
      status: query?.status || undefined,
      environment: query?.environment || undefined,
    },
  });
  return data;
}

export async function createCallerSystem(params: {
  code: string;
  name: string;
  environment: string;
  description?: string;
  belonging_party?: string;
  owner?: string;
  contact?: string;
  owner_email?: string;
  tags?: string[];
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

export async function getRuntimePolicy(systemId: string): Promise<RuntimePolicy> {
  const { data } = await client.get(`/caller-systems/${systemId}/runtime-policy`);
  return data;
}

export async function saveRuntimePolicy(
  systemId: string,
  params: {
    allowed_api_patterns: string[];
    qps_limit: number;
    concurrency_limit: number;
    quota_per_day: number;
    request_timeout_seconds: number;
    circuit_breaker_enabled: boolean;
    effective_from?: string | null;
    effective_to?: string | null;
    row_version?: number;
  },
): Promise<RuntimePolicy> {
  const { data } = await client.put(`/caller-systems/${systemId}/runtime-policy`, params);
  return data;
}
