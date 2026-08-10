import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, Select, message, Space, Tag, Typography, Tabs, Popconfirm, Descriptions,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listCallerSystems, createCallerSystem, enableCallerSystem, disableCallerSystem,
  reviveCallerSystem, revokeCallerSystem,
  listPublicKeys, addPublicKey, enablePublicKey, disablePublicKey, revokePublicKey,
  listIPRules, addIPRule, updateIPRuleStatus,
  type CallerSystemItem, type PublicKeyItem, type IPRuleItem,
} from '../../api/caller-systems';

const { Title, Paragraph } = Typography;

const statusColor: Record<string, string> = {
  draft: 'default', enabled: 'green', disabled: 'orange', revoked: 'red',
};

export default function CallerSystemListPage() {
  const [systems, setSystems] = useState<CallerSystemItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [keys, setKeys] = useState<PublicKeyItem[]>([]);
  const [rules, setRules] = useState<IPRuleItem[]>([]);
  const [keyForm] = Form.useForm();
  const [ruleForm] = Form.useForm();

  const fetchSystems = async () => {
    setLoading(true);
    try {
      const { items, total: t } = await listCallerSystems();
      setSystems(items);
      setTotal(t);
    } catch {
      message.error('加载调用系统失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSystems(); }, []);

  const openDetail = async (systemId: string) => {
    setDetailId(systemId);
    try {
      setKeys(await listPublicKeys(systemId));
      setRules(await listIPRules(systemId));
    } catch {
      setKeys([]);
      setRules([]);
    }
    setDetailOpen(true);
  };

  const handleCreate = async (values: Record<string, unknown>) => {
    try {
      await createCallerSystem(values as { name: string; environment: string });
      message.success('调用系统创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      fetchSystems();
    } catch (err: unknown) {
      message.error((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '创建失败');
    }
  };

  const handleLifecycle = async (systemId: string, action: string, reason?: string) => {
    try {
      if (action === 'enable') await enableCallerSystem(systemId);
      else if (action === 'disable') await disableCallerSystem(systemId, reason || '');
      else if (action === 'revive') await reviveCallerSystem(systemId);
      else if (action === 'revoke') await revokeCallerSystem(systemId, reason || '');
      message.success('操作成功');
      fetchSystems();
    } catch (err: unknown) {
      message.error((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '操作失败');
    }
  };

  const handleAddKey = async () => {
    if (!detailId) return;
    const values = await keyForm.validateFields();
    try {
      await addPublicKey(detailId, values.public_key, values.effective_to);
      message.success('公钥已添加');
      keyForm.resetFields();
      setKeys(await listPublicKeys(detailId));
    } catch (err: unknown) {
      message.error((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '添加失败');
    }
  };

  const handleAddRule = async () => {
    if (!detailId) return;
    const values = await ruleForm.validateFields();
    try {
      await addIPRule(detailId, values.ip_cidr, values.description);
      message.success('IP 规则已添加');
      ruleForm.resetFields();
      setRules(await listIPRules(detailId));
    } catch (err: unknown) {
      message.error((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '添加失败');
    }
  };

  const columns: ColumnsType<CallerSystemItem> = [
    { title: 'system_id', dataIndex: 'system_id', key: 'system_id', width: 200, render: (v) => <Tag>{v}</Tag> },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '环境', dataIndex: 'environment', key: 'environment', width: 80,
      render: (v) => v === 'production' ? <Tag color="blue">生产</Tag> : <Tag>开发</Tag> },
    { title: '负责人', dataIndex: 'owner', key: 'owner', render: (v) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s) => <Tag color={statusColor[s]}>{s}</Tag> },
    {
      title: '操作', key: 'actions', width: 280,
      render: (_, record) => (
        <Space size="small">
          <Button size="small" onClick={() => openDetail(record.system_id)}>详情</Button>
          {record.status === 'draft' && (
            <Popconfirm title="确认启用？" onConfirm={() => handleLifecycle(record.system_id, 'enable')}>
              <Button size="small" type="primary">启用</Button>
            </Popconfirm>
          )}
          {record.status === 'enabled' && (
            <Popconfirm title="确认停用？" onConfirm={() => {
              const reason = prompt('停用原因（可选）：') || '';
              handleLifecycle(record.system_id, 'disable', reason);
            }}>
              <Button size="small" danger>停用</Button>
            </Popconfirm>
          )}
          {record.status === 'disabled' && (
            <Space size="small">
              <Popconfirm title="确认恢复？" onConfirm={() => handleLifecycle(record.system_id, 'revive')}>
                <Button size="small">恢复</Button>
              </Popconfirm>
              <Popconfirm title="确认注销？注销后 system_id 不可复用！" onConfirm={() => {
                const reason = prompt('注销原因（必填）：');
                if (reason) handleLifecycle(record.system_id, 'revoke', reason);
              }}>
                <Button size="small" danger>注销</Button>
              </Popconfirm>
            </Space>
          )}
        </Space>
      ),
    },
  ];

  const keyColumns: ColumnsType<PublicKeyItem> = [
    { title: 'key_id', dataIndex: 'key_id', key: 'key_id', render: (v) => <Tag>{v}</Tag> },
    { title: '指纹', dataIndex: 'fingerprint', key: 'fingerprint', render: (v) => v?.slice(0, 16) + '...' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (s) => <Tag>{s}</Tag> },
    {
      title: '操作', key: 'actions', width: 200,
      render: (_, record) => (
        <Space size="small">
          {record.status === 'pending' && (
            <Popconfirm title="确认启用？" onConfirm={() => enablePublicKey(record.key_id).then(() => openDetail(detailId!))}>
              <Button size="small">启用</Button>
            </Popconfirm>
          )}
          {(record.status === 'pending' || record.status === 'active') && (
            <Popconfirm title="确认停用？" onConfirm={() => disablePublicKey(record.key_id).then(() => openDetail(detailId!))}>
              <Button size="small">停用</Button>
            </Popconfirm>
          )}
          {record.status !== 'revoked' && (
            <Popconfirm title="确认撤销？不可恢复！" onConfirm={() => revokePublicKey(record.key_id).then(() => openDetail(detailId!))}>
              <Button size="small" danger>撤销</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const ruleColumns: ColumnsType<IPRuleItem> = [
    { title: 'IP/CIDR', dataIndex: 'ip_cidr', key: 'ip_cidr', render: (v) => <Tag color="purple">{v}</Tag> },
    { title: '描述', dataIndex: 'description', key: 'description', render: (v) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status' },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_, record) => (
        <Popconfirm title="切换启用/停用" onConfirm={() => updateIPRuleStatus(record.id, 'toggle').then(() => openDetail(detailId!))}>
          <Button size="small">{record.status === 'active' ? '停用' : '启用'}</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>调用系统 ({total})</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchSystems}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            登记调用系统
          </Button>
        </Space>
      </div>

      <Table columns={columns} dataSource={systems} rowKey="id" loading={loading} />

      <Modal
        title="登记调用系统"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        onOk={() => createForm.submit()}
      >
        <Form form={createForm} onFinish={handleCreate} layout="vertical">
          <Form.Item name="name" label="系统名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="environment" label="环境" rules={[{ required: true }]} initialValue="development">
            <Select options={[{ label: '开发', value: 'development' }, { label: '生产', value: 'production' }]} />
          </Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea /></Form.Item>
          <Form.Item name="department" label="部门"><Input /></Form.Item>
          <Form.Item name="owner" label="负责人"><Input /></Form.Item>
          <Form.Item name="contact" label="联系方式"><Input /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="调用系统详情"
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={800}
      >
        <Tabs
          items={[
            {
              key: 'keys',
              label: `公钥 (${keys.length})`,
              children: (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <Space>
                      <Form form={keyForm} layout="inline">
                        <Form.Item name="public_key" rules={[{ required: true }]}>
                          <Input.TextArea placeholder="粘贴 PEM 公钥" rows={3} style={{ width: 400 }} />
                        </Form.Item>
                      </Form>
                      <Button type="primary" onClick={handleAddKey}>添加公钥</Button>
                    </Space>
                  </div>
                  <Table columns={keyColumns} dataSource={keys} rowKey="key_id" size="small" />
                </>
              ),
            },
            {
              key: 'ip-rules',
              label: `IP 规则 (${rules.length})`,
              children: (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <Space>
                      <Form form={ruleForm} layout="inline">
                        <Form.Item name="ip_cidr" rules={[{ required: true }]}>
                          <Input placeholder="192.168.1.0/24 或 *" style={{ width: 200 }} />
                        </Form.Item>
                        <Form.Item name="description">
                          <Input placeholder="描述（可选）" />
                        </Form.Item>
                      </Form>
                      <Button type="primary" onClick={handleAddRule}>添加规则</Button>
                    </Space>
                  </div>
                  <Table columns={ruleColumns} dataSource={rules} rowKey="id" size="small" />
                </>
              ),
            },
          ]}
        />
      </Modal>
    </>
  );
}
