import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, Select, message, Space, Tag, Typography, Popconfirm,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listProviders, createProvider, updateProvider, setProviderStatus,
  type ProviderItem, type ProviderTargetSecurityConfig,
} from '../../api/catalog';
import { useAuth } from '../../contexts/AuthContext';

const { Title } = Typography;

const statusLabel: Record<string, string> = {
  enabled: '已启用', disabled: '已停用', archived: '已归档',
};
const statusColor: Record<string, string> = {
  enabled: 'green', disabled: 'orange', archived: 'default',
};
const typeLabel: Record<string, string> = { builtin: '内置', http: 'HTTP' };

interface ProviderFormValues {
  provider_code: string;
  name: string;
  provider_type: string;
  description?: string;
  allowed_domains?: string;
  allowed_ports?: string;
  path_prefix?: string;
  allowed_cidrs?: string;
}

function parseList(value?: string): string[] {
  return (value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function ProvidersPage() {
  const { hasOperation } = useAuth();
  const [items, setItems] = useState<ProviderItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editItem, setEditItem] = useState<ProviderItem | null>(null);
  const [form] = Form.useForm<ProviderFormValues>();
  const [providerType, setProviderType] = useState('http');

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { items: list, total: t } = await listProviders(0, 100);
      setItems(list);
      setTotal(t);
    } catch {
      message.error('加载 Provider 失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchItems(); }, []);

  const openCreate = () => {
    form.resetFields();
    setProviderType('http');
    setCreateOpen(true);
  };

  const openEdit = (item: ProviderItem) => {
    setEditItem(item);
    setProviderType(item.provider_type);
    form.setFieldsValue({
      provider_code: item.provider_code,
      name: item.name,
      provider_type: item.provider_type,
      description: item.description || undefined,
      allowed_domains: item.target_security_config?.allowed_domains.join(',') || undefined,
      allowed_ports: item.target_security_config?.allowed_ports.join(',') || undefined,
      path_prefix: item.target_security_config?.path_prefix || undefined,
      allowed_cidrs: item.target_security_config?.allowed_cidrs.join(',') || undefined,
    });
    setEditOpen(true);
  };

  const buildConfig = (values: ProviderFormValues): ProviderTargetSecurityConfig | null => {
    if (values.provider_type !== 'http') return null;
    return {
      allowed_domains: parseList(values.allowed_domains),
      allowed_ports: parseList(values.allowed_ports).map(Number),
      path_prefix: values.path_prefix || null,
      protocols: ['https'],
      dns_tls_verification: true,
      allowed_cidrs: parseList(values.allowed_cidrs),
    };
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      await createProvider({
        provider_code: values.provider_code,
        name: values.name,
        provider_type: values.provider_type,
        description: values.description,
        target_security_config: buildConfig(values),
      });
      message.success('Provider 已创建');
      setCreateOpen(false);
      fetchItems();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '创建失败');
    }
  };

  const handleUpdate = async () => {
    if (!editItem) return;
    const values = await form.validateFields();
    try {
      await updateProvider(editItem.id, {
        name: values.name,
        description: values.description,
        target_security_config: buildConfig(values),
        row_version: editItem.row_version,
      });
      message.success('Provider 已更新');
      setEditOpen(false);
      fetchItems();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '更新失败');
    }
  };

  const handleStatus = async (item: ProviderItem, action: 'enable' | 'disable' | 'archive') => {
    try {
      await setProviderStatus(item.id, action);
      message.success('操作成功');
      fetchItems();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '操作失败');
    }
  };

  const columns: ColumnsType<ProviderItem> = [
    { title: '编码', dataIndex: 'provider_code', width: 160 },
    { title: '名称', dataIndex: 'name', width: 200 },
    {
      title: '类型', dataIndex: 'provider_type', width: 90,
      render: (v: string) => typeLabel[v] || v,
    },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={statusColor[v]}>{statusLabel[v] || v}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 260,
      render: (_, record) => (
        <Space>
          {hasOperation('provider:edit') && (
            <Button size="small" onClick={() => openEdit(record)}>编辑</Button>
          )}
          {hasOperation('provider:manage') && record.status === 'enabled' && (
            <Popconfirm title="确认停用？" onConfirm={() => handleStatus(record, 'disable')}>
              <Button size="small">停用</Button>
            </Popconfirm>
          )}
          {hasOperation('provider:manage') && record.status === 'disabled' && (
            <Button size="small" onClick={() => handleStatus(record, 'enable')}>启用</Button>
          )}
          {hasOperation('provider:manage') && record.status !== 'archived' && (
            <Popconfirm title="归档后不可恢复，确认？" onConfirm={() => handleStatus(record, 'archive')}>
              <Button size="small" danger>归档</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4}>Provider 管理</Title>
      <Space style={{ marginBottom: 16 }}>
        {hasOperation('provider:create') && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建 Provider</Button>
        )}
        <Button icon={<ReloadOutlined />} onClick={fetchItems}>刷新</Button>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{ total, pageSize: 100, showTotal: (t) => `共 ${t} 条` }}
      />
      <Modal
        title="新建 Provider"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="provider_code" label="编码" rules={[{ required: true, message: '请输入编码' }]}>
            <Input placeholder="如 builtin-math" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="provider_type" label="类型" rules={[{ required: true }]}>
            <Select
              options={[{ value: 'builtin', label: '内置' }, { value: 'http', label: 'HTTP' }]}
              onChange={(v: string) => setProviderType(v)}
            />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
          {providerType === 'http' && (
            <>
              <Form.Item name="allowed_domains" label="允许域名（逗号分隔）" rules={[{ required: true, message: '必填' }]}>
                <Input placeholder="api.example.com" />
              </Form.Item>
              <Form.Item name="allowed_ports" label="允许端口（逗号分隔）">
                <Input placeholder="443" />
              </Form.Item>
              <Form.Item name="path_prefix" label="路径前缀">
                <Input placeholder="/v1" />
              </Form.Item>
              <Form.Item name="allowed_cidrs" label="允许内网 CIDR（逗号分隔，公网 HTTPS 无需填写）">
                <Input placeholder="10.0.0.0/8" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
      <Modal
        title="编辑 Provider"
        open={editOpen}
        onOk={handleUpdate}
        onCancel={() => setEditOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item label="编码">
            <Input value={editItem?.provider_code} disabled />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
          {providerType === 'http' && (
            <>
              <Form.Item name="allowed_domains" label="允许域名（逗号分隔）" rules={[{ required: true, message: '必填' }]}>
                <Input />
              </Form.Item>
              <Form.Item name="allowed_ports" label="允许端口（逗号分隔）">
                <Input />
              </Form.Item>
              <Form.Item name="path_prefix" label="路径前缀">
                <Input />
              </Form.Item>
              <Form.Item name="allowed_cidrs" label="允许内网 CIDR（逗号分隔）">
                <Input />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>
    </div>
  );
}
