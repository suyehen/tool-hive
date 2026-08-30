import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, Select, message, Space, Tag, Typography,
  Popconfirm, Tabs, Switch, InputNumber, Descriptions,
} from 'antd';
import { PlusOutlined, ReloadOutlined, HistoryOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listTools, createTool, updateTool, setToolStatus, getTool,
  createVersion, updateVersion, submitReview, publishVersion,
  setDefaultVersion, versionTransition, getToolHistory,
  listProviders,
  testExecuteTool,
  type ToolItem, type ToolDetail, type VersionItem, type BindingPayload,
  type ProviderItem, type HistoryItem,
} from '../../api/catalog';
import { useAuth } from '../../contexts/AuthContext';

const { Title, Paragraph } = Typography;

const statusLabel: Record<string, string> = {
  enabled: '已启用', disabled: '已停用', archived: '已归档',
};
const statusColor: Record<string, string> = {
  enabled: 'green', disabled: 'orange', archived: 'default',
};
const riskLabel: Record<string, string> = {
  low: '低', medium: '中', high: '高',
};
const versionStatusLabel: Record<string, string> = {
  draft: '草稿', pending_review: '待审核', approved: '已通过',
  rejected: '已驳回', published: '已发布', disabled: '已停用',
  withdrawn: '已撤回', archived: '已归档',
};
const versionStatusColor: Record<string, string> = {
  draft: 'default', pending_review: 'blue', approved: 'cyan',
  rejected: 'red', published: 'green', disabled: 'orange',
  withdrawn: 'purple', archived: 'default',
};
const historyActionLabel: Record<string, string> = {
  submit_review: '送审', approve: '审核通过', reject: '驳回',
  publish: '发布', enable: '重新启用', disable: '停用',
  withdraw: '撤回', archive: '归档', set_default: '设为默认',
};

interface ToolFormValues {
  namespace: string;
  tool_code: string;
  name: string;
  description?: string;
  risk_level: string;
  discoverable: boolean;
  executable: boolean;
  input_schema?: string;
  output_schema?: string;
}

interface VersionFormValues {
  version: string;
  release_note?: string;
  input_schema?: string;
  output_schema?: string;
  provider_id?: string;
  method?: string;
  path_template?: string;
  parameter_mapping?: string;
  timeout_seconds?: number;
  retry_max?: number;
  idempotent?: boolean;
}

function parseJson(value?: string): Record<string, unknown> | null {
  if (!value || !value.trim()) return null;
  try {
    const parsed = JSON.parse(value);
    if (typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('must be object');
    }
    return parsed;
  } catch {
    throw new Error('JSON 格式错误');
  }
}

function dumpJson(value: Record<string, unknown> | null | undefined): string {
  if (!value) return '';
  return JSON.stringify(value, null, 2);
}

export default function ToolsPage() {
  const { hasOperation } = useAuth();
  const [items, setItems] = useState<ToolItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editItem, setEditItem] = useState<ToolItem | null>(null);
  const [detail, setDetail] = useState<ToolDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [versionModalOpen, setVersionModalOpen] = useState(false);
  const [editVersion, setEditVersion] = useState<VersionItem | null>(null);
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishVersionItem, setPublishVersionItem] = useState<VersionItem | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [testOpen, setTestOpen] = useState(false);
  const [testVersion, setTestVersion] = useState<VersionItem | null>(null);
  const [testArguments, setTestArguments] = useState('');
  const [testConfirm, setTestConfirm] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [toolForm] = Form.useForm<ToolFormValues>();
  const [versionForm] = Form.useForm<VersionFormValues>();
  const [publishForm] = Form.useForm<{ set_default: boolean; comment?: string }>();

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { items: list, total: t } = await listTools(0, 100);
      setItems(list);
      setTotal(t);
    } catch {
      message.error('加载工具失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchItems(); }, []);

  const loadProviders = async () => {
    try {
      const { items: list } = await listProviders(0, 200);
      setProviders(list);
    } catch {
      setProviders([]);
    }
  };

  const openDetail = async (toolId: string) => {
    setDetailOpen(true);
    try {
      setDetail(await getTool(toolId));
    } catch {
      message.error('加载工具详情失败');
      setDetailOpen(false);
    }
  };

  const handleCreate = async () => {
    const values = await toolForm.validateFields();
    try {
      await createTool({
        namespace: values.namespace,
        tool_code: values.tool_code,
        name: values.name,
        description: values.description,
        risk_level: values.risk_level,
        discoverable: values.discoverable,
        executable: values.executable,
        input_schema: parseJson(values.input_schema),
        output_schema: parseJson(values.output_schema),
      });
      message.success('工具已创建');
      setCreateOpen(false);
      fetchItems();
    } catch (e: unknown) {
      const err = e as { message?: string; response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || err.message || '创建失败');
    }
  };

  const handleUpdate = async () => {
    if (!editItem) return;
    const values = await toolForm.validateFields();
    try {
      await updateTool(editItem.id, {
        name: values.name,
        description: values.description,
        risk_level: values.risk_level,
        discoverable: values.discoverable,
        executable: values.executable,
        input_schema: parseJson(values.input_schema),
        output_schema: parseJson(values.output_schema),
        row_version: editItem.row_version,
      });
      message.success('工具已更新');
      setEditOpen(false);
      fetchItems();
    } catch (e: unknown) {
      const err = e as { message?: string; response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || err.message || '更新失败');
    }
  };

  const handleToolStatus = async (toolId: string, action: 'enable' | 'disable' | 'archive') => {
    try {
      await setToolStatus(toolId, action);
      message.success('操作成功');
      fetchItems();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '操作失败');
    }
  };

  const openVersionModal = async (version?: VersionItem) => {
    await loadProviders();
    setEditVersion(version || null);
    versionForm.resetFields();
    if (version) {
      versionForm.setFieldsValue({
        version: version.version,
        release_note: version.release_note || undefined,
        input_schema: dumpJson(version.input_schema),
        output_schema: dumpJson(version.output_schema),
        provider_id: version.binding?.provider_id,
        method: version.binding?.method,
        path_template: version.binding?.path_template,
        parameter_mapping: dumpJson(version.binding?.parameter_mapping),
        timeout_seconds: version.binding?.timeout_seconds ?? undefined,
        retry_max: version.binding?.retry_max ?? undefined,
        idempotent: version.binding?.idempotent ?? true,
      });
    } else {
      versionForm.setFieldsValue({ idempotent: true, method: 'COMPUTE', timeout_seconds: 5, retry_max: 1 });
    }
    setVersionModalOpen(true);
  };

  const buildBinding = (values: VersionFormValues): BindingPayload | null => {
    if (!values.provider_id) return null;
    return {
      provider_id: values.provider_id,
      method: values.method || 'COMPUTE',
      path_template: values.path_template || '',
      parameter_mapping: parseJson(values.parameter_mapping),
      timeout_seconds: values.timeout_seconds ?? 5,
      retry_max: values.retry_max ?? 1,
      idempotent: values.idempotent ?? true,
    };
  };

  const handleVersionSave = async () => {
    if (!detail) return;
    const values = await versionForm.validateFields();
    try {
      if (editVersion) {
        await updateVersion(detail.id, editVersion.id, {
          input_schema: parseJson(values.input_schema),
          output_schema: parseJson(values.output_schema),
          release_note: values.release_note || null,
          binding: buildBinding(values),
          row_version: editVersion.row_version,
        });
      } else {
        await createVersion(detail.id, {
          version: values.version,
          input_schema: parseJson(values.input_schema),
          output_schema: parseJson(values.output_schema),
          release_note: values.release_note || null,
          binding: buildBinding(values),
        });
      }
      message.success('版本已保存');
      setVersionModalOpen(false);
      setDetail(await getTool(detail.id));
    } catch (e: unknown) {
      const err = e as { message?: string; response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || err.message || '保存失败');
    }
  };

  const handleVersionAction = async (version: VersionItem, action: string, comment?: string) => {
    if (!detail) return;
    try {
      if (action === 'submit-review') {
        await submitReview(detail.id, version.id);
      } else if (action === 'publish') {
        const values = await publishForm.validateFields();
        await publishVersion(detail.id, version.id, values.set_default, values.comment);
        setPublishOpen(false);
      } else if (action === 'set-default') {
        await setDefaultVersion(detail.id, version.id);
      } else {
        await versionTransition(detail.id, version.id, action as 'disable' | 'enable' | 'withdraw' | 'archive', comment);
      }
      message.success('操作成功');
      setDetail(await getTool(detail.id));
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '操作失败');
    }
  };

  const openHistory = async () => {
    if (!detail) return;
    try {
      setHistoryItems(await getToolHistory(detail.id));
      setHistoryOpen(true);
    } catch {
      message.error('加载历史失败');
    }
  };

  const handleTestExecute = async () => {
    if (!detail || !testVersion) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = testArguments.trim() ? JSON.parse(testArguments) : {};
      if (typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('must be object');
      }
    } catch {
      message.error('参数 JSON 格式错误');
      return;
    }
    setTestLoading(true);
    try {
      const result = await testExecuteTool(detail.id, {
        arguments: parsed,
        version: testVersion.version,
        confirm: testConfirm,
      });
      setTestResult(JSON.stringify(result, null, 2));
      message.success('测试执行成功');
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '测试执行失败');
    } finally {
      setTestLoading(false);
    }
  };

  const toolColumns: ColumnsType<ToolItem> = [
    { title: '完整标识', dataIndex: 'full_code', width: 200 },
    { title: '名称', dataIndex: 'name', width: 180 },
    { title: '风险', dataIndex: 'risk_level', width: 70, render: (v: string) => riskLabel[v] || v },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={statusColor[v]}>{statusLabel[v] || v}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 320,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => openDetail(record.id)}>详情</Button>
          {hasOperation('tool:edit') && (
            <Button
              size="small"
              onClick={() => {
                setEditItem(record);
                toolForm.setFieldsValue({
                  namespace: record.namespace,
                  tool_code: record.tool_code,
                  name: record.name,
                  description: record.description || undefined,
                  risk_level: record.risk_level,
                  discoverable: record.discoverable,
                  executable: record.executable,
                  input_schema: dumpJson(record.input_schema),
                  output_schema: dumpJson(record.output_schema),
                });
                setEditOpen(true);
              }}
            >
              编辑
            </Button>
          )}
          {hasOperation('tool:manage') && record.status === 'enabled' && (
            <Popconfirm title="确认停用？" onConfirm={() => handleToolStatus(record.id, 'disable')}>
              <Button size="small">停用</Button>
            </Popconfirm>
          )}
          {hasOperation('tool:manage') && record.status === 'disabled' && (
            <Button size="small" onClick={() => handleToolStatus(record.id, 'enable')}>启用</Button>
          )}
          {hasOperation('tool:manage') && record.status !== 'archived' && (
            <Popconfirm title="归档后不可恢复，确认？" onConfirm={() => handleToolStatus(record.id, 'archive')}>
              <Button size="small" danger>归档</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const versionColumns: ColumnsType<VersionItem> = [
    { title: '版本', dataIndex: 'version', width: 100 },
    {
      title: '状态', dataIndex: 'status', width: 110,
      render: (v: string, record) => (
        <Space>
          <Tag color={versionStatusColor[v]}>{versionStatusLabel[v] || v}</Tag>
          {record.is_default && <Tag color="gold">默认</Tag>}
        </Space>
      ),
    },
    { title: '执行绑定', dataIndex: 'binding', width: 260, render: (b: VersionItem['binding']) => (b ? `${b.provider_code} ${b.method} ${b.path_template}` : '-') },
    { title: '版本说明', dataIndex: 'release_note', ellipsis: true },
    { title: '创建时间', dataIndex: 'created_at', width: 170 },
    {
      title: '操作', key: 'actions', width: 380,
      render: (_, record) => (
        <Space wrap>
          {hasOperation('tool:edit') && (record.status === 'draft' || record.status === 'rejected') && (
            <Button size="small" onClick={() => openVersionModal(record)}>编辑</Button>
          )}
          {hasOperation('tool:edit') && (record.status === 'draft' || record.status === 'rejected') && (
            <Popconfirm title="确认送审？" onConfirm={() => handleVersionAction(record, 'submit-review')}>
              <Button size="small" type="primary">送审</Button>
            </Popconfirm>
          )}
          {hasOperation('tool:publish') && record.status === 'approved' && (
            <Button
              size="small"
              onClick={() => {
                setPublishVersionItem(record);
                publishForm.setFieldsValue({ set_default: true });
                setPublishOpen(true);
              }}
            >
              发布
            </Button>
          )}
          {hasOperation('tool:publish') && record.status === 'published' && !record.is_default && (
            <Popconfirm title="切换为默认版本？" onConfirm={() => handleVersionAction(record, 'set-default')}>
              <Button size="small">设默认</Button>
            </Popconfirm>
          )}
          {hasOperation('tool:manage') && record.status === 'published' && (
            <Button
              size="small"
              onClick={() => {
                setTestVersion(record);
                setTestArguments('');
                setTestConfirm(false);
                setTestResult(null);
                setTestOpen(true);
              }}
            >
              测试
            </Button>
          )}
          {hasOperation('tool:manage') && record.status === 'published' && (
            <Popconfirm title="确认停用？" onConfirm={() => handleVersionAction(record, 'disable')}>
              <Button size="small">停用</Button>
            </Popconfirm>
          )}
          {hasOperation('tool:manage') && record.status === 'disabled' && (
            <Button size="small" onClick={() => handleVersionAction(record, 'enable')}>启用</Button>
          )}
          {hasOperation('tool:manage') && (record.status === 'published' || record.status === 'disabled') && (
            <Popconfirm title="确认撤回？" onConfirm={() => handleVersionAction(record, 'withdraw')}>
              <Button size="small">撤回</Button>
            </Popconfirm>
          )}
          {hasOperation('tool:manage') && record.status !== 'archived' && (
            <Popconfirm title="归档后不可恢复，确认？" onConfirm={() => handleVersionAction(record, 'archive')}>
              <Button size="small" danger>归档</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const providerOptions = providers.map((p) => ({
    value: p.id,
    label: `${p.provider_code}（${p.name} / ${p.provider_type}）`,
  }));

  return (
    <div>
      <Title level={4}>工具目录</Title>
      <Space style={{ marginBottom: 16 }}>
        {hasOperation('tool:create') && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              toolForm.resetFields();
              toolForm.setFieldsValue({ risk_level: 'low', discoverable: true, executable: true });
              setCreateOpen(true);
            }}
          >
            新建工具
          </Button>
        )}
        <Button icon={<ReloadOutlined />} onClick={fetchItems}>刷新</Button>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        columns={toolColumns}
        dataSource={items}
        pagination={{ total, pageSize: 100, showTotal: (t) => `共 ${t} 条` }}
      />

      {/* 工具创建 / 编辑 */}
      <Modal title={editItem ? '编辑工具' : '新建工具'} open={createOpen || editOpen} onOk={editItem ? handleUpdate : handleCreate} onCancel={() => { setCreateOpen(false); setEditOpen(false); }} width={720} destroyOnClose>
        <Form form={toolForm} layout="vertical" preserve={false}>
          <Space.Compact block>
            <Form.Item name="namespace" label="命名空间" rules={[{ required: true, message: '请输入命名空间' }]} style={{ width: '50%' }}>
              <Input placeholder="math.basic" disabled={!!editItem} />
            </Form.Item>
            <Form.Item name="tool_code" label="工具编码" rules={[{ required: true, message: '请输入工具编码' }]} style={{ width: '50%' }}>
              <Input placeholder="calculator" disabled={!!editItem} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Space size="large">
            <Form.Item name="risk_level" label="风险等级">
              <Select options={[{ value: 'low', label: '低' }, { value: 'medium', label: '中' }, { value: 'high', label: '高' }]} style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="discoverable" label="可发现" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item name="executable" label="可执行" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item name="input_schema" label="输入 Schema（JSON）">
            <Input.TextArea rows={5} placeholder='{"type":"object"}' />
          </Form.Item>
          <Form.Item name="output_schema" label="输出 Schema（JSON）">
            <Input.TextArea rows={5} placeholder='{"type":"object"}' />
          </Form.Item>
        </Form>
      </Modal>

      {/* 工具详情 */}
      <Modal title={detail ? `${detail.full_code}（${detail.name}）` : '工具详情'} open={detailOpen} onCancel={() => setDetailOpen(false)} footer={null} width={980} destroyOnClose>
        {detail && (
          <>
            <Space style={{ marginBottom: 12 }}>
              <Button icon={<HistoryOutlined />} onClick={openHistory}>发布历史</Button>
              {hasOperation('tool:edit') && (
                <Button type="primary" icon={<PlusOutlined />} onClick={() => openVersionModal()}>新建版本</Button>
              )}
            </Space>
            <Tabs
              items={[
                {
                  key: 'versions',
                  label: `版本（${detail.versions.length}）`,
                  children: (
                    <Table
                      rowKey="id"
                      size="small"
                      columns={versionColumns}
                      dataSource={detail.versions}
                      pagination={false}
                    />
                  ),
                },
                {
                  key: 'info',
                  label: '工具信息',
                  children: (
                    <Descriptions column={2} bordered size="small">
                      <Descriptions.Item label="命名空间">{detail.namespace}</Descriptions.Item>
                      <Descriptions.Item label="工具编码">{detail.tool_code}</Descriptions.Item>
                      <Descriptions.Item label="风险等级">{riskLabel[detail.risk_level]}</Descriptions.Item>
                      <Descriptions.Item label="状态">{statusLabel[detail.status]}</Descriptions.Item>
                      <Descriptions.Item label="可发现">{detail.discoverable ? '是' : '否'}</Descriptions.Item>
                      <Descriptions.Item label="可执行">{detail.executable ? '是' : '否'}</Descriptions.Item>
                      <Descriptions.Item label="描述" span={2}>{detail.description || '-'}</Descriptions.Item>
                    </Descriptions>
                  ),
                },
              ]}
            />
          </>
        )}
      </Modal>

      {/* 版本创建 / 编辑 */}
      <Modal
        title={editVersion ? `编辑版本 ${editVersion.version}` : '新建版本'}
        open={versionModalOpen}
        onOk={handleVersionSave}
        onCancel={() => setVersionModalOpen(false)}
        width={760}
        destroyOnClose
      >
        <Form form={versionForm} layout="vertical" preserve={false}>
          <Form.Item name="version" label="版本号" rules={[{ required: true, message: '请输入版本号' }]}>
            <Input placeholder="1.0.0" disabled={!!editVersion} />
          </Form.Item>
          <Form.Item name="release_note" label="版本说明">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="input_schema" label="输入 Schema（JSON）">
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="output_schema" label="输出 Schema（JSON）">
            <Input.TextArea rows={4} />
          </Form.Item>
          <Paragraph type="secondary">执行绑定（送审前必填）</Paragraph>
          <Form.Item name="provider_id" label="Provider">
            <Select options={providerOptions} showSearch optionFilterProp="label" placeholder="选择 Provider" />
          </Form.Item>
          <Space.Compact block>
            <Form.Item name="method" label="方法" style={{ width: '30%' }}>
              <Select
                options={[
                  { value: 'COMPUTE', label: 'COMPUTE' },
                  { value: 'GET', label: 'GET' },
                  { value: 'POST', label: 'POST' },
                  { value: 'PUT', label: 'PUT' },
                  { value: 'DELETE', label: 'DELETE' },
                ]}
              />
            </Form.Item>
            <Form.Item name="path_template" label="路径模板" rules={[{ required: true, message: '必填' }]} style={{ width: '70%' }}>
              <Input placeholder="builtin://math/add 或 /v1/calc" />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="parameter_mapping" label="参数映射（JSON）">
            <Input.TextArea rows={3} placeholder='{"a":"input.a","b":"input.b"}' />
          </Form.Item>
          <Space size="large">
            <Form.Item name="timeout_seconds" label="超时（秒）">
              <InputNumber min={1} max={300} />
            </Form.Item>
            <Form.Item name="retry_max" label="最大重试">
              <InputNumber min={0} max={10} />
            </Form.Item>
            <Form.Item name="idempotent" label="幂等" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 发布 */}
      <Modal
        title={`发布版本 ${publishVersionItem?.version ?? ''}`}
        open={publishOpen}
        onOk={() => publishVersionItem && handleVersionAction(publishVersionItem, 'publish')}
        onCancel={() => setPublishOpen(false)}
        destroyOnClose
      >
        <Form form={publishForm} layout="vertical" preserve={false}>
          <Form.Item name="set_default" label="设为默认版本" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="comment" label="发布说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 历史 */}
      <Modal title="发布历史" open={historyOpen} onCancel={() => setHistoryOpen(false)} footer={null} width={760}>
        <Table
          rowKey={(r) => `${r.kind}-${r.id}`}
          size="small"
          pagination={false}
          dataSource={historyItems}
          columns={[
            { title: '版本', dataIndex: 'version_id', width: 240 },
            { title: '动作', dataIndex: 'action', width: 110, render: (v: string) => historyActionLabel[v] || v },
            { title: '说明', dataIndex: 'comment' },
            { title: '操作人', dataIndex: 'operator_account_id', width: 120, render: (v: string | null) => v || '-' },
            { title: '时间', dataIndex: 'created_at', width: 170 },
          ]}
        />
      </Modal>

      {/* 工具测试 */}
      <Modal
        title={`测试工具 ${detail?.full_code ?? ''}${testVersion ? `（${testVersion.version}）` : ''}`}
        open={testOpen}
        onCancel={() => setTestOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form layout="vertical">
          <Form.Item label="参数（JSON）">
            <Input.TextArea
              rows={6}
              value={testArguments}
              onChange={(e) => setTestArguments(e.target.value)}
              placeholder='{"a":1,"b":2,"operation":"add"}'
            />
          </Form.Item>
          <Form.Item label="高风险 / 写操作确认" valuePropName="checked">
            <Switch checked={testConfirm} onChange={setTestConfirm} />
          </Form.Item>
          <Button type="primary" loading={testLoading} onClick={handleTestExecute}>
            执行测试
          </Button>
          {testResult !== null && (
            <pre
              style={{
                marginTop: 16,
                background: '#f5f5f5',
                padding: 12,
                borderRadius: 6,
                maxHeight: 300,
                overflow: 'auto',
              }}
            >
              {testResult}
            </pre>
          )}
        </Form>
      </Modal>
    </div>
  );
}
