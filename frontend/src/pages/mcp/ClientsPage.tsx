import { useEffect, useState } from 'react';
import {
  Button,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { useAuth } from '../../contexts/AuthContext';
import {
  addMcpIpRule,
  createMcpClient,
  issueMcpToken,
  listMcpClients,
  listMcpIpRules,
  listMcpScopes,
  mcpClientAction,
  replaceMcpScopes,
  revokeMcpToken,
  type IpRule,
  type McpClientItem,
} from '../../api/mcp';

const { Title } = Typography;

const statusLabel: Record<string, string> = {
  draft: '草稿',
  enabled: '已启用',
  disabled: '已停用',
  revoked: '已注销',
};

export default function ClientsPage() {
  const { hasOperation } = useAuth();
  const [items, setItems] = useState<McpClientItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [tokenResult, setTokenResult] = useState<string>();
  const [active, setActive] = useState<McpClientItem | null>(null);
  const [ipRules, setIpRules] = useState<IpRule[]>([]);
  const [ipOpen, setIpOpen] = useState(false);
  const [scopesOpen, setScopesOpen] = useState(false);
  const [scopesText, setScopesText] = useState('');
  const [form] = Form.useForm();
  const [ipForm] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      const data = await listMcpClients(0, 100);
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载 MCP 客户端失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const create = async () => {
    const values = await form.validateFields();
    try {
      await createMcpClient({
        name: values.name,
        description: values.description || undefined,
      });
      message.success('客户端已创建');
      setCreateOpen(false);
      void load();
    } catch {
      message.error('创建失败');
    }
  };

  const action = async (client: McpClientItem, op: 'enable' | 'disable' | 'revive' | 'revoke') => {
    try {
      await mcpClientAction(client.client_code, op);
      message.success('操作成功');
      void load();
    } catch {
      message.error('操作失败');
    }
  };

  const issueToken = async (client: McpClientItem) => {
    try {
      const result = await issueMcpToken(client.client_code);
      setTokenResult(result.token);
      void load();
    } catch {
      message.error('签发失败');
    }
  };

  const revokeToken = async (client: McpClientItem) => {
    try {
      await revokeMcpToken(client.client_code);
      message.success('令牌已吊销');
    } catch {
      message.error('吊销失败');
    }
  };

  const openIpRules = async (client: McpClientItem) => {
    setActive(client);
    setIpOpen(true);
    try {
      setIpRules(await listMcpIpRules(client.client_code));
    } catch {
      setIpRules([]);
    }
  };

  const addRule = async () => {
    if (!active) return;
    const values = await ipForm.validateFields();
    try {
      await addMcpIpRule(active.client_code, {
        ip_cidr: values.ip_cidr,
        description: values.description,
      });
      ipForm.resetFields();
      setIpRules(await listMcpIpRules(active.client_code));
    } catch {
      message.error('新增来源规则失败');
    }
  };

  const openScopes = async (client: McpClientItem) => {
    setActive(client);
    setScopesOpen(true);
    try {
      const scopes = await listMcpScopes(client.client_code);
      setScopesText(
        scopes
          .map((s) => JSON.stringify({ scope_type: s.scope_type, scope_code: s.scope_code, status: s.status }))
          .join('\n'),
      );
    } catch {
      setScopesText('');
    }
  };

  const saveScopes = async () => {
    if (!active) return;
    try {
      const parsed = scopesText
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => JSON.parse(line) as { scope_type: string; scope_code: string; status: string });
      await replaceMcpScopes(active.client_code, parsed);
      message.success('授权范围已保存');
      setScopesOpen(false);
    } catch {
      message.error('保存失败：请检查每行 JSON（scope_type/scope_code/status）');
    }
  };

  return (
    <div>
      <Title level={4}>MCP 客户端与授权</Title>
      <Space style={{ marginBottom: 16 }}>
        {hasOperation('mcp_client:manage') && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              setCreateOpen(true);
            }}
          >
            新建客户端
          </Button>
        )}
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
      </Space>
      <Table
        rowKey="client_code"
        loading={loading}
        dataSource={items}
        pagination={{ pageSize: 100, total, showTotal: (t) => `共 ${t} 条` }}
        columns={[
          { title: '客户端编码', dataIndex: 'client_code', width: 210 },
          { title: '名称', dataIndex: 'name', width: 180 },
          {
            title: '状态',
            dataIndex: 'status',
            width: 90,
            render: (v: string) => <Tag>{statusLabel[v] || v}</Tag>,
          },
          {
            title: '操作',
            key: 'actions',
            width: 620,
            render: (_, record: McpClientItem) => (
              <Space wrap size="small">
                {hasOperation('mcp_client:manage') && (
                  <>
                    {record.status === 'draft' || record.status === 'disabled' ? (
                      <Button size="small" onClick={() => action(record, 'enable')}>
                        启用
                      </Button>
                    ) : null}
                    {record.status === 'enabled' ? (
                      <Button size="small" onClick={() => action(record, 'disable')}>
                        停用
                      </Button>
                    ) : null}
                    {record.status === 'revoked' ? (
                      <Button size="small" onClick={() => action(record, 'revive')}>
                        恢复
                      </Button>
                    ) : null}
                    {record.status !== 'revoked' && (
                      <Button size="small" onClick={() => issueToken(record)}>
                        签发 Token
                      </Button>
                    )}
                    <Button size="small" onClick={() => revokeToken(record)}>
                      吊销 Token
                    </Button>
                    <Button size="small" onClick={() => openIpRules(record)}>
                      来源规则
                    </Button>
                    <Popconfirm
                      title="确认注销？"
                      onConfirm={() => action(record, 'revoke')}
                    >
                      <Button size="small" danger>
                        注销
                      </Button>
                    </Popconfirm>
                  </>
                )}
                {hasOperation('mcp_auth:manage') && (
                  <Button size="small" onClick={() => openScopes(record)}>
                    授权范围
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="新建 MCP 客户端"
        open={createOpen}
        onOk={create}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '必填' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Token 签发成功"
        open={tokenResult !== undefined}
        footer={null}
        onCancel={() => setTokenResult(undefined)}
      >
        <Typography.Paragraph type="warning">
          明文只显示这一次，请立即复制保存。
        </Typography.Paragraph>
        <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 6, userSelect: 'all' }}>
          {tokenResult}
        </pre>
      </Modal>

      <Modal
        title={`来源 IP 规则 ${active ? `- ${active.name}` : ''}`}
        open={ipOpen}
        footer={null}
        onCancel={() => setIpOpen(false)}
        width={720}
      >
        <Table
          size="small"
          rowKey="id"
          dataSource={ipRules}
          pagination={false}
          columns={[
            { title: 'IP/CIDR', dataIndex: 'ip_cidr' },
            { title: '说明', dataIndex: 'description' },
            { title: '状态', dataIndex: 'status' },
          ]}
        />
        <Form form={ipForm} layout="inline" style={{ marginTop: 16 }}>
          <Form.Item name="ip_cidr" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="10.0.0.0/8 或 *" style={{ width: 240 }} />
          </Form.Item>
          <Form.Item name="description">
            <Input placeholder="说明" style={{ width: 220 }} />
          </Form.Item>
          <Button type="primary" onClick={addRule}>
            新增
          </Button>
        </Form>
      </Modal>

      <Modal
        title={`授权范围 ${active ? `- ${active.name}` : ''}`}
        open={scopesOpen}
        onOk={saveScopes}
        onCancel={() => setScopesOpen(false)}
        width={720}
      >
        <Typography.Paragraph type="secondary">
          每行一个 JSON：{`{"scope_type":"namespace|capability|tool","scope_code":"math.basic","status":"active"}`}
        </Typography.Paragraph>
        <Input.TextArea
          rows={10}
          value={scopesText}
          onChange={(e) => setScopesText(e.target.value)}
        />
      </Modal>
    </div>
  );
}
