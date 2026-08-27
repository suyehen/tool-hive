import client from './client';

// ── Provider ──

export interface ProviderTargetSecurityConfig {
  allowed_domains: string[];
  allowed_ports: number[];
  path_prefix?: string | null;
  protocols: string[];
  dns_tls_verification: boolean;
  allowed_cidrs: string[];
}

export interface ProviderItem {
  id: string;
  provider_code: string;
  name: string;
  provider_type: string;
  status: string;
  description: string | null;
  target_security_config: ProviderTargetSecurityConfig | null;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface ProviderListResponse {
  items: ProviderItem[];
  total: number;
}

export async function listProviders(
  offset = 0,
  limit = 50,
  query?: { keyword?: string; status?: string; provider_type?: string },
): Promise<ProviderListResponse> {
  const { data } = await client.get('/catalog/providers', {
    params: {
      offset,
      limit,
      keyword: query?.keyword || undefined,
      status: query?.status || undefined,
      provider_type: query?.provider_type || undefined,
    },
  });
  return data;
}

export async function createProvider(params: {
  provider_code: string;
  name: string;
  provider_type: string;
  description?: string;
  target_security_config?: ProviderTargetSecurityConfig | null;
}): Promise<ProviderItem> {
  const { data } = await client.post('/catalog/providers', params);
  return data;
}

export async function updateProvider(
  providerId: string,
  params: Record<string, unknown>,
): Promise<ProviderItem> {
  const { data } = await client.patch(`/catalog/providers/${providerId}`, params);
  return data;
}

export async function setProviderStatus(
  providerId: string,
  action: 'enable' | 'disable' | 'archive',
): Promise<ProviderItem> {
  const { data } = await client.post(`/catalog/providers/${providerId}/${action}`);
  return data;
}

// ── 能力包 ──

export interface CapabilityPackItem {
  id: string;
  pack_code: string;
  name: string;
  description: string | null;
  status: string;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface CapabilityPackListResponse {
  items: CapabilityPackItem[];
  total: number;
}

export async function listCapabilityPacks(
  offset = 0,
  limit = 50,
  query?: { keyword?: string; status?: string },
): Promise<CapabilityPackListResponse> {
  const { data } = await client.get('/catalog/capability-packs', {
    params: {
      offset,
      limit,
      keyword: query?.keyword || undefined,
      status: query?.status || undefined,
    },
  });
  return data;
}

export async function createCapabilityPack(params: {
  pack_code: string;
  name: string;
  description?: string;
}): Promise<CapabilityPackItem> {
  const { data } = await client.post('/catalog/capability-packs', params);
  return data;
}

export async function updateCapabilityPack(
  packId: string,
  params: Record<string, unknown>,
): Promise<CapabilityPackItem> {
  const { data } = await client.patch(`/catalog/capability-packs/${packId}`, params);
  return data;
}

export async function setCapabilityPackStatus(
  packId: string,
  action: 'enable' | 'disable' | 'archive',
): Promise<CapabilityPackItem> {
  const { data } = await client.post(`/catalog/capability-packs/${packId}/${action}`);
  return data;
}

export async function listPackTools(packId: string): Promise<ToolItem[]> {
  const { data } = await client.get(`/catalog/capability-packs/${packId}/tools`);
  return data;
}

export async function replacePackTools(packId: string, toolIds: string[]): Promise<ToolItem[]> {
  const { data } = await client.put(`/catalog/capability-packs/${packId}/tools`, {
    tool_ids: toolIds,
  });
  return data;
}

export async function listPackSystems(packId: string): Promise<CallerSystemLite[]> {
  const { data } = await client.get(`/catalog/capability-packs/${packId}/systems`);
  return data;
}

export async function replacePackSystems(
  packId: string,
  systemIds: string[],
): Promise<CallerSystemLite[]> {
  const { data } = await client.put(`/catalog/capability-packs/${packId}/systems`, {
    system_ids: systemIds,
  });
  return data;
}

export interface CallerSystemLite {
  id: string;
  system_id: string;
  name: string;
  code: string;
  environment: string;
  status: string;
}

// ── 工具 ──

export interface ToolItem {
  id: string;
  namespace: string;
  tool_code: string;
  full_code: string;
  name: string;
  description: string | null;
  risk_level: string;
  discoverable: boolean;
  executable: boolean;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  status: string;
  default_version_id: string | null;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface ToolListResponse {
  items: ToolItem[];
  total: number;
}

export interface BindingItem {
  id: string;
  version_id: string;
  provider_id: string;
  provider_code: string;
  provider_name: string;
  method: string;
  path_template: string;
  parameter_mapping: Record<string, unknown> | null;
  allowed_headers: string[] | null;
  response_handling: Record<string, unknown> | null;
  timeout_seconds: number | null;
  retry_max: number | null;
  idempotent: boolean;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface VersionItem {
  id: string;
  tool_id: string;
  version: string;
  status: string;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  release_note: string | null;
  review_comment: string | null;
  row_version: number;
  is_default: boolean;
  created_at: string;
  updated_at: string | null;
  binding: BindingItem | null;
}

export interface ToolDetail extends ToolItem {
  versions: VersionItem[];
}

export async function listTools(
  offset = 0,
  limit = 50,
  query?: { keyword?: string; namespace?: string; status?: string; risk_level?: string },
): Promise<ToolListResponse> {
  const { data } = await client.get('/catalog/tools', {
    params: {
      offset,
      limit,
      keyword: query?.keyword || undefined,
      namespace: query?.namespace || undefined,
      status: query?.status || undefined,
      risk_level: query?.risk_level || undefined,
    },
  });
  return data;
}

export async function createTool(params: {
  namespace: string;
  tool_code: string;
  name: string;
  description?: string;
  risk_level: string;
  discoverable: boolean;
  executable: boolean;
  input_schema?: Record<string, unknown> | null;
  output_schema?: Record<string, unknown> | null;
}): Promise<ToolItem> {
  const { data } = await client.post('/catalog/tools', params);
  return data;
}

export async function updateTool(toolId: string, params: Record<string, unknown>): Promise<ToolItem> {
  const { data } = await client.patch(`/catalog/tools/${toolId}`, params);
  return data;
}

export async function setToolStatus(
  toolId: string,
  action: 'enable' | 'disable' | 'archive',
): Promise<ToolItem> {
  const { data } = await client.post(`/catalog/tools/${toolId}/${action}`);
  return data;
}

export async function getTool(toolId: string): Promise<ToolDetail> {
  const { data } = await client.get(`/catalog/tools/${toolId}`);
  return data;
}

export interface BindingPayload {
  provider_id: string;
  method: string;
  path_template: string;
  parameter_mapping?: Record<string, unknown> | null;
  allowed_headers?: string[] | null;
  response_handling?: Record<string, unknown> | null;
  timeout_seconds?: number | null;
  retry_max?: number | null;
  idempotent?: boolean;
}

export async function createVersion(
  toolId: string,
  params: {
    version: string;
    input_schema?: Record<string, unknown> | null;
    output_schema?: Record<string, unknown> | null;
    release_note?: string | null;
    binding?: BindingPayload | null;
  },
): Promise<VersionItem> {
  const { data } = await client.post(`/catalog/tools/${toolId}/versions`, params);
  return data;
}

export async function updateVersion(
  toolId: string,
  versionId: string,
  params: Record<string, unknown>,
): Promise<VersionItem> {
  const { data } = await client.patch(
    `/catalog/tools/${toolId}/versions/${versionId}`,
    params,
  );
  return data;
}

export async function submitReview(toolId: string, versionId: string): Promise<VersionItem> {
  const { data } = await client.post(
    `/catalog/tools/${toolId}/versions/${versionId}/submit-review`,
    { comment: null },
  );
  return data;
}

export async function publishVersion(
  toolId: string,
  versionId: string,
  setDefault: boolean,
  comment?: string,
): Promise<VersionItem> {
  const { data } = await client.post(
    `/catalog/tools/${toolId}/versions/${versionId}/publish`,
    { set_default: setDefault, comment: comment || null },
  );
  return data;
}

export async function setDefaultVersion(toolId: string, versionId: string): Promise<VersionItem> {
  const { data } = await client.post(
    `/catalog/tools/${toolId}/versions/${versionId}/set-default`,
  );
  return data;
}

export async function versionTransition(
  toolId: string,
  versionId: string,
  action: 'disable' | 'enable' | 'withdraw' | 'archive',
  comment?: string,
): Promise<VersionItem> {
  const { data } = await client.post(
    `/catalog/tools/${toolId}/versions/${versionId}/${action}`,
    { comment: comment || null },
  );
  return data;
}

export interface HistoryItem {
  kind: string;
  id: string;
  version_id: string;
  action: string;
  comment: string | null;
  operator_account_id: string | null;
  from_status: string | null;
  to_status: string | null;
  created_at: string;
}

export async function getToolHistory(toolId: string): Promise<HistoryItem[]> {
  const { data } = await client.get(`/catalog/tools/${toolId}/history`);
  return data;
}

// ── 审核 ──

export interface PendingReviewItem {
  version_id: string;
  tool_id: string;
  tool_name: string;
  full_code: string;
  version: string;
  release_note: string | null;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  submitter_account_id: string | null;
  created_at: string;
}

export interface PendingReviewListResponse {
  items: PendingReviewItem[];
  total: number;
}

export async function listPendingReviews(offset = 0, limit = 50): Promise<PendingReviewListResponse> {
  const { data } = await client.get('/catalog/reviews/pending', { params: { offset, limit } });
  return data;
}

export async function approveReview(versionId: string, comment?: string): Promise<void> {
  await client.post(`/catalog/reviews/${versionId}/approve`, { comment: comment || null });
}

export async function rejectReview(versionId: string, comment?: string): Promise<void> {
  await client.post(`/catalog/reviews/${versionId}/reject`, { comment: comment || null });
}

// ── 索引任务 ──

export interface IndexTaskItem {
  delivery_id: string;
  event_id: string;
  event_type: string;
  object_type: string;
  object_id: string;
  event_status: string;
  target: string;
  status: string;
  attempts: number;
  last_error: string | null;
  duration_ms: number | null;
  worker_instance: string | null;
  create_time: string;
  update_time: string | null;
}

export interface IndexTaskListResponse {
  items: IndexTaskItem[];
  total: number;
}

export async function listIndexTasks(
  offset = 0,
  limit = 50,
  status?: string,
): Promise<IndexTaskListResponse> {
  const { data } = await client.get('/catalog/index-tasks', {
    params: { offset, limit, status: status || undefined },
  });
  return data;
}

export async function retryIndexTask(deliveryId: string): Promise<IndexTaskItem> {
  const { data } = await client.post(`/catalog/index-tasks/${deliveryId}/retry`);
  return data;
}
