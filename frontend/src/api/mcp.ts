import client from './client';

export interface ServerConfig {
  id: string;
  server_name: string;
  description: string | null;
  enabled: boolean;
  endpoint_path: string;
  allowed_hosts: string[];
  protocol_versions: string[] | null;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export async function getServerConfig(): Promise<ServerConfig> {
  const { data } = await client.get('/mcp/server-config');
  return data;
}

export async function updateServerConfig(
  params: Record<string, unknown>,
): Promise<ServerConfig> {
  const { data } = await client.put('/mcp/server-config', params);
  return data;
}

export interface McpClientItem {
  id: string;
  client_code: string;
  name: string;
  description: string | null;
  status: string;
  deactivated_reason: string | null;
  row_version: number;
  created_at: string;
  updated_at: string | null;
}

export interface McpClientListResponse {
  items: McpClientItem[];
  total: number;
}

export async function listMcpClients(
  offset = 0,
  limit = 50,
  query?: { keyword?: string; status?: string },
): Promise<McpClientListResponse> {
  const { data } = await client.get('/mcp/clients', {
    params: {
      offset,
      limit,
      keyword: query?.keyword || undefined,
      status: query?.status || undefined,
    },
  });
  return data;
}

export async function createMcpClient(params: {
  name: string;
  description?: string;
}): Promise<McpClientItem> {
  const { data } = await client.post('/mcp/clients', params);
  return data;
}

export async function updateMcpClient(
  clientCode: string,
  params: Record<string, unknown>,
): Promise<McpClientItem> {
  const { data } = await client.patch(`/mcp/clients/${clientCode}`, params);
  return data;
}

export async function mcpClientAction(
  clientCode: string,
  action: 'enable' | 'disable' | 'revive' | 'revoke',
  reason?: string,
): Promise<McpClientItem> {
  const { data } = await client.post(`/mcp/clients/${clientCode}/${action}`, {
    reason: reason || null,
  });
  return data;
}

export async function issueMcpToken(clientCode: string): Promise<{
  token: string;
  token_id: string;
  client_code: string;
}> {
  const { data } = await client.post(`/mcp/clients/${clientCode}/token`);
  return data;
}

export async function revokeMcpToken(clientCode: string): Promise<void> {
  await client.post(`/mcp/clients/${clientCode}/token/revoke`, { reason: '管理端吊销' });
}

export interface IpRule {
  id: string;
  client_id: string;
  ip_cidr: string;
  description: string | null;
  status: string;
  row_version: number;
  created_at: string;
}

export async function listMcpIpRules(clientCode: string): Promise<IpRule[]> {
  const { data } = await client.get(`/mcp/clients/${clientCode}/ip-rules`);
  return data;
}

export async function addMcpIpRule(
  clientCode: string,
  params: { ip_cidr: string; description?: string },
): Promise<IpRule> {
  const { data } = await client.post(
    `/mcp/clients/${clientCode}/ip-rules`,
    params,
  );
  return data;
}

export async function updateMcpIpRuleStatus(
  ruleId: string,
  enabled: boolean,
): Promise<void> {
  await client.patch(`/mcp/ip-rules/${ruleId}/status`, { enabled });
}

export interface ScopeItem {
  id: string;
  client_id: string;
  scope_type: string;
  scope_code: string;
  status: string;
  row_version: number;
  created_at: string;
  reference_exists: boolean;
  reference_archived: boolean;
}

export async function listMcpScopes(clientCode: string): Promise<ScopeItem[]> {
  const { data } = await client.get(`/mcp/clients/${clientCode}/scopes`);
  return data;
}

export async function replaceMcpScopes(
  clientCode: string,
  items: Array<{ scope_type: string; scope_code: string; status: string }>,
): Promise<ScopeItem[]> {
  const { data } = await client.put(`/mcp/clients/${clientCode}/scopes`, {
    items,
  });
  return data;
}

export interface ExposedTool {
  id: string;
  full_code: string;
  name: string;
  risk_level: string;
  status: string;
  mcp_enabled: boolean;
  version: string;
}

export async function listExposedTools(): Promise<ExposedTool[]> {
  const { data } = await client.get('/mcp/exposed-tools');
  return data;
}

export interface TraceEvent {
  id: string;
  trace_id: string;
  action: string;
  status: string;
  error_code: string | null;
  summary: Record<string, unknown> | null;
  source_ip: string | null;
  mcp_client_id: string | null;
  occurred_at: string;
}

export interface CallRecordListResponse {
  items: TraceEvent[];
  total: number;
}

export async function listCallRecords(
  offset = 0,
  limit = 50,
  query?: { status?: string; client_id?: string },
): Promise<CallRecordListResponse> {
  const { data } = await client.get('/mcp/call-records', {
    params: {
      offset,
      limit,
      status: query?.status || undefined,
      client_id: query?.client_id || undefined,
    },
  });
  return data;
}

export async function getCallRecordDetail(
  traceId: string,
): Promise<{ trace_id: string; events: TraceEvent[] }> {
  const { data } = await client.get(`/mcp/call-records/${traceId}`);
  return data;
}

export interface ConsoleDebugResult {
  ok: boolean;
  server_name: string;
  discovered: string[];
  call_text: string;
  call_is_error: boolean;
  trace_id: string | null;
  detail: string | null;
}

export async function runMcpTestDebug(
  toolCode: string,
  argumentsJson: Record<string, unknown>,
): Promise<ConsoleDebugResult> {
  const { data } = await client.post('/mcp/test-debug', {
    tool_code: toolCode,
    arguments: argumentsJson,
  });
  return data;
}
