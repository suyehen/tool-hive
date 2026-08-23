import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, Select, message, Space, Tag, Typography, Tabs, Popconfirm, Descriptions, DatePicker, Dropdown,
} from 'antd';
import { PlusOutlined, ReloadOutlined, EllipsisOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { MenuProps } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import {
  listCallerSystems, createCallerSystem, updateCallerSystem, enableCallerSystem, disableCallerSystem,
  reviveCallerSystem, revokeCallerSystem,
  listPublicKeys, addPublicKey, enablePublicKey, disablePublicKey, revokePublicKey,
  listIPRules, addIPRule, updateIPRuleStatus,
  type CallerSystemItem, type PublicKeyItem, type IPRuleItem,
} from '../../api/caller-systems';
import { useAuth } from '../../contexts/AuthContext';

const { Title, Paragraph } = Typography;

const statusColor: Record<string, string> = {
  draft: 'default', enabled: 'green', disabled: 'orange', revoked: 'red',
};

const effectiveStateTag: Record<string, { text: string; color: string }> = {
  not_started: { text: '未生效', color: 'blue' },
  effective: { text: '生效中', color: 'green' },
  expired: { text: '已过期', color: 'red' },
};

interface CallerSystemFormValues {
  name: string;
  environment: string;
  description?: string;
  department?: string;
  owner?: string;
  contact?: string;
  effectiveFrom?: Dayjs | null;
  effectiveTo?: Dayjs | null;
}

const renderEffectiveState = (s: string) => {
  const t = effectiveStateTag[s] || { text: s || '-', color: 'default' };
  return <Tag color={t.color}>{t.text}</Tag>;
};

export default function CallerSystemListPage() {
  const { hasOperation } = useAuth();
  const [systems, setSystems] = useState<CallerSystemItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editRowVersion, setEditRowVersion] = useState<number | null>(null);
  const [editForm] = Form.useForm();
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

  const openEdit = (record: CallerSystemItem) => {
    setEditId(record.system_id);
    setEditRowVersion(record.row_version);
    editForm.setFieldsValue({
      name: record.name,
      description: record.description ?? undefined,
      department: record.department ?? undefined,
      owner: record.owner ?? undefined,
      contact: record.contact ?? undefined,
      effectiveFrom: record.effective_from ? dayjs(record.effective_from) : null,
      effectiveTo: record.effective_to ? dayjs(record.effective_to) : null,
    });
    setEditOpen(true);
  };

  const handleCreate = async (values: CallerSystemFormValues) => {
    try {
      await createCallerSystem({
        name: values.name,
        environment: values.environment,
        description: values.description,
        department: values.department,
        owner: values.owner,
        contact: values.contact,
        effective_from: values.effectiveFrom ? values.effectiveFrom.toISOString() : null,
        effective_to: values.effectiveTo ? values.effectiveTo.toISOString() : null,
      });
      message.success('调用系统创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      fetchSystems();
    } catch (err: unknown) {
      message.error((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '创建失败');
    }
  };

  const handleEdit = async (values: CallerSystemFormValues) => {
    if (!editId) return;
    try {
      await updateCallerSystem(editId, {
        name: values.name,
        description: values.description,
        department: values.department,
        owner: values.owner,
        contact: values.contact,
        effective_from: values.effectiveFrom ? values.effectiveFrom.toISOString() : null,
        effective_to: values.effectiveTo ? values.effectiveTo.toISOString() : null,
        row_version: editRowVersion,
      });
      message.success('调用系统修改成功');
      setEditOpen(false);
      editForm.resetFields();
      fetchSystems();
    } catch (err: unknown) {
      message.error((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '修改失败');
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

  const confirmLifecycle = (systemId: string, action: 'enable' | 'revive') => {
    Modal.confirm({
      title: action === 'enable' ? '确认启用？' : '确认恢复？',
      content: action === 'enable' ? '确认启用该系统？' : '确认恢复该系统？',
      onOk: () => handleLifecycle(systemId, action),
    });
  };

  const confirmLifecycleWithReason = (
    systemId: string,
    action: 'disable' | 'revoke',
  ) => {
    Modal.confirm({
      title: action === 'disable' ? '确认停用？' : '确认注销？',
      content: action === 'disable' ? '确认停用该系统？' : '确认注销该系统？注销后 system_id 不可复用！',
      onOk: () => {
        const reason = prompt(action === 'revoke' ? '注销原因（必填）：' : '停用原因（可选）：') || '';
        if (action === 'revoke' && !reason) {
          message.warning('注销原因必填');
          return;
        }
        handleLifecycle(systemId, action, reason);
      },
    });
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
    { title: '有效期', dataIndex: 'effective_state', key: 'effective_state', width: 90,
      render: (s) => renderEffectiveState(s) },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_, record) => {
        const items: MenuProps['items'] = [];
        if (hasOperation('caller_system:edit')) {
          items.push({ key: 'edit', label: '编辑', onClick: () => openEdit(record) });
        }
        if (hasOperation('caller_system:view')) {
          items.push({ key: 'detail', label: '详情', onClick: () => openDetail(record.system_id) });
        }
        if (hasOperation('caller_system:manage')) {
          if (record.status === 'draft') {
            items.push({ key: 'enable', label: '启用', onClick: () => confirmLifecycle(record.system_id, 'enable') });
          }
          if (record.status === 'enabled') {
            items.push({
              key: 'disable',
              label: '停用',
              danger: true,
              onClick: () => confirmLifecycleWithReason(record.system_id, 'disable'),
            });
          }
          if (record.status === 'disabled') {
            items.push({ key: 'revive', label: '恢复', onClick: () => confirmLifecycle(record.system_id, 'revive') });
            items.push({
              key: 'revoke',
              label: '注销',
              danger: true,
              onClick: () => confirmLifecycleWithReason(record.system_id, 'revoke'),
            });
          }
        }

        if (items.length === 0) return null;
        return (
          <Dropdown menu={{ items }} trigger={['click']} placement="bottomRight">
            <Button type="text" size="small" icon={<EllipsisOutlined />} />
          </Dropdown>
        );
      },
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
          {hasOperation('caller_system:manage') && record.status === 'pending' && (
            <Popconfirm title="确认启用？" onConfirm={() => enablePublicKey(record.key_id).then(() => openDetail(detailId!))}>
              <Button size="small">启用</Button>
            </Popconfirm>
          )}
          {hasOperation('caller_system:manage') && (record.status === 'pending' || record.status === 'active') && (
            <Popconfirm title="确认停用？" onConfirm={() => disablePublicKey(record.key_id).then(() => openDetail(detailId!))}>
              <Button size="small">停用</Button>
            </Popconfirm>
          )}
          {hasOperation('caller_system:manage') && record.status !== 'revoked' && (
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
        hasOperation('caller_system:manage') ? (
          <Popconfirm title="切换启用/停用" onConfirm={() => updateIPRuleStatus(record.id, 'toggle').then(() => openDetail(detailId!))}>
            <Button size="small">{record.status === 'active' ? '停用' : '启用'}</Button>
          </Popconfirm>
        ) : null
      ),
    },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>调用系统 ({total})</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchSystems}>刷新</Button>
          {hasOperation('caller_system:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              登记调用系统
            </Button>
          )}
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
          <Form.Item name="effectiveFrom" label="生效时间（可选）">
            <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="留空表示不限" />
          </Form.Item>
          <Form.Item name="effectiveTo" label="失效时间（可选）">
            <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="留空表示不限" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑调用系统"
        open={editOpen}
        onCancel={() => { setEditOpen(false); editForm.resetFields(); }}
        onOk={() => editForm.submit()}
      >
        <Form form={editForm} onFinish={handleEdit} layout="vertical">
          <Form.Item name="name" label="系统名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea /></Form.Item>
          <Form.Item name="department" label="部门"><Input /></Form.Item>
          <Form.Item name="owner" label="负责人"><Input /></Form.Item>
          <Form.Item name="contact" label="联系方式"><Input /></Form.Item>
          <Form.Item name="effectiveFrom" label="生效时间（可选）">
            <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="留空表示不限" />
          </Form.Item>
          <Form.Item name="effectiveTo" label="失效时间（可选）">
            <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="留空表示不限" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="调用系统详情"
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={800}
      >
        {(() => {
          const detailSystem = systems.find((s) => s.system_id === detailId) ?? null;
          if (!detailSystem) return null;
          return (
            <Descriptions size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="system_id">{detailSystem.system_id}</Descriptions.Item>
              <Descriptions.Item label="名称">{detailSystem.name}</Descriptions.Item>
              <Descriptions.Item label="环境">{detailSystem.environment === 'production' ? '生产' : '开发'}</Descriptions.Item>
              <Descriptions.Item label="生命周期状态">
                <Tag color={statusColor[detailSystem.status]}>{detailSystem.status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="有效期状态">
                {renderEffectiveState(detailSystem.effective_state)}
              </Descriptions.Item>
              <Descriptions.Item label="生效时间">
                {detailSystem.effective_from ? dayjs(detailSystem.effective_from).format('YYYY-MM-DD HH:mm') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="失效时间">
                {detailSystem.effective_to ? dayjs(detailSystem.effective_to).format('YYYY-MM-DD HH:mm') : '-'}
              </Descriptions.Item>
            </Descriptions>
          );
        })()}
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
                      {hasOperation('caller_system:manage') && (
                        <Button type="primary" onClick={handleAddKey}>添加公钥</Button>
                      )}
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
                      {hasOperation('caller_system:manage') && (
                        <Button type="primary" onClick={handleAddRule}>添加规则</Button>
                      )}
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
