import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, InputNumber, Select, message, Space, Tag, Typography, Tabs, Popconfirm, Descriptions, DatePicker, Dropdown, Switch,
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
  getRuntimePolicy, saveRuntimePolicy,
  listToolScopes, replaceToolScopes, emergencyDisable, emergencyEnable,
  type CallerSystemItem, type PublicKeyItem, type IPRuleItem, type RuntimePolicy, type ToolScopeItem,
} from '../../api/caller-systems';
import { useAuth } from '../../contexts/AuthContext';

const { Title, Paragraph } = Typography;

const statusColor: Record<string, string> = {
  draft: 'default', enabled: 'green', disabled: 'orange', revoked: 'red',
};
const statusLabel: Record<string, string> = {
  draft: '草稿', enabled: '已启用', disabled: '已停用', revoked: '已注销',
};
const keyStatusLabel: Record<string, string> = {
  pending: '待启用', active: '已启用', disabled: '已停用', expired: '已过期', revoked: '已撤销',
};
const ruleStatusLabel: Record<string, string> = {
  active: '已启用', disabled: '已停用',
};

const effectiveStateTag: Record<string, { text: string; color: string }> = {
  not_started: { text: '未生效', color: 'blue' },
  effective: { text: '生效中', color: 'green' },
  expired: { text: '已过期', color: 'red' },
};

interface CallerSystemFormValues {
  code: string;
  name: string;
  environment: string;
  description?: string;
  belongingParty?: string;
  owner?: string;
  contact?: string;
  ownerEmail?: string;
  tags?: string[];
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
  const [runtimePolicy, setRuntimePolicy] = useState<RuntimePolicy | null>(null);
  const [policyForm] = Form.useForm();
  const [toolScopes, setToolScopes] = useState<ToolScopeItem[]>([]);
  const [scopeForm] = Form.useForm();
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [envFilter, setEnvFilter] = useState<string | undefined>(undefined);

  const fetchSystems = async (override?: {
    keyword?: string;
    status?: string;
    environment?: string;
  }) => {
    // 未传 override 时使用当前筛选状态；传了则完全以 override 为准（重置场景）
    const kw = override === undefined ? keyword : (override.keyword ?? '');
    const st = override === undefined ? statusFilter : override.status;
    const env = override === undefined ? envFilter : override.environment;
    setLoading(true);
    try {
      const { items, total: t } = await listCallerSystems(0, 50, {
        keyword: kw.trim() || undefined,
        status: st,
        environment: env,
      });
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
    if (hasOperation('caller_system:policy')) {
      try {
        const policy = await getRuntimePolicy(systemId);
        setRuntimePolicy(policy);
        policyForm.setFieldsValue({
          allowed_api_patterns: policy.allowed_api_patterns,
          qps_limit: policy.qps_limit,
          concurrency_limit: policy.concurrency_limit,
          quota_per_day: policy.quota_per_day,
          request_timeout_seconds: policy.request_timeout_seconds,
          circuit_breaker_enabled: policy.circuit_breaker_enabled,
          effectiveFrom: policy.effective_from ? dayjs(policy.effective_from) : null,
          effectiveTo: policy.effective_to ? dayjs(policy.effective_to) : null,
        });
      } catch {
        setRuntimePolicy(null);
        policyForm.resetFields();
      }
      try {
        setToolScopes(await listToolScopes(systemId));
      } catch {
        setToolScopes([]);
      }
    }
    setDetailOpen(true);
  };

  const handleSavePolicy = async () => {
    if (!detailId) return;
    const values = await policyForm.validateFields();
    try {
      await saveRuntimePolicy(detailId, {
        allowed_api_patterns: values.allowed_api_patterns || [],
        qps_limit: values.qps_limit,
        concurrency_limit: values.concurrency_limit,
        quota_per_day: values.quota_per_day,
        request_timeout_seconds: values.request_timeout_seconds,
        circuit_breaker_enabled: values.circuit_breaker_enabled,
        effective_from: values.effectiveFrom ? values.effectiveFrom.toISOString() : null,
        effective_to: values.effectiveTo ? values.effectiveTo.toISOString() : null,
        row_version: runtimePolicy?.row_version,
      });
      message.success('运行策略已保存');
      const policy = await getRuntimePolicy(detailId);
      setRuntimePolicy(policy);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '保存失败';
      message.error(msg);
    }
  };

  const handleAddScope = async () => {
    const values = await scopeForm.validateFields();
    const tempId = `new-${Date.now()}`;
    setToolScopes((prev) => [
      ...prev,
      {
        id: tempId,
        system_id: detailId ?? '',
        scope_type: values.scope_type,
        scope_code: values.scope_code,
        status: values.status,
        row_version: 0,
        created_at: '',
      },
    ]);
    scopeForm.resetFields();
  };

  const handleRemoveScope = (id: string) => {
    setToolScopes((prev) => prev.filter((item) => item.id !== id));
  };

  const handleSaveScopes = async () => {
    if (!detailId) return;
    try {
      const items = toolScopes.map((item) => ({
        scope_type: item.scope_type,
        scope_code: item.scope_code,
        status: item.status,
      }));
      const saved = await replaceToolScopes(detailId, items);
      setToolScopes(saved);
      message.success('工具范围已保存');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '保存失败';
      message.error(msg);
    }
  };

  const handleEmergencyDisable = (systemId: string) => {
    Modal.confirm({
      title: '确认紧急禁用？',
      content: '紧急禁用将立即影响运行侧校验，需填写原因。',
      onOk: () => {
        const reason = prompt('紧急禁用原因（必填）：') || '';
        if (!reason) {
          message.warning('紧急禁用原因必填');
          return;
        }
        return emergencyDisable(systemId, reason).then(() => {
          message.success('已紧急禁用');
          fetchSystems();
        });
      },
    });
  };

  const handleEmergencyEnable = (systemId: string) => {
    Modal.confirm({
      title: '解除紧急禁用？',
      content: '确认解除该系统的紧急禁用？',
      onOk: () => emergencyEnable(systemId).then(() => {
        message.success('已解除紧急禁用');
        fetchSystems();
      }),
    });
  };

  const openEdit = (record: CallerSystemItem) => {
    setEditId(record.system_id);
    setEditRowVersion(record.row_version);
    editForm.setFieldsValue({
      code: record.code,
      name: record.name,
      description: record.description ?? undefined,
      belongingParty: record.belonging_party ?? undefined,
      owner: record.owner ?? undefined,
      contact: record.contact ?? undefined,
      ownerEmail: record.owner_email ?? undefined,
      tags: record.tags ?? [],
      effectiveFrom: record.effective_from ? dayjs(record.effective_from) : null,
      effectiveTo: record.effective_to ? dayjs(record.effective_to) : null,
    });
    setEditOpen(true);
  };

  const handleCreate = async (values: CallerSystemFormValues) => {
    try {
      await createCallerSystem({
        code: values.code,
        name: values.name,
        environment: values.environment,
        description: values.description,
        belonging_party: values.belongingParty,
        owner: values.owner,
        contact: values.contact,
        owner_email: values.ownerEmail,
        tags: values.tags,
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
        belonging_party: values.belongingParty,
        owner: values.owner,
        contact: values.contact,
        owner_email: values.ownerEmail,
        tags: values.tags,
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
      content: action === 'disable'
        ? '确认停用该系统？'
        : '确认注销该系统？该操作无法撤销，注销后 system_id 永久失效且不可复用！',
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
    { title: '编码', dataIndex: 'code', key: 'code' },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '归属方', dataIndex: 'belonging_party', key: 'belonging_party', render: (v) => v || '-' },
    { title: '环境', dataIndex: 'environment', key: 'environment', width: 80,
      render: (v) => v === 'production' ? <Tag color="blue">生产</Tag>
        : v === 'staging' ? <Tag color="orange">测试</Tag>
          : <Tag>开发</Tag> },
    { title: '负责人', dataIndex: 'owner', key: 'owner', render: (v) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s, record) => (
        <Space size={4}>
          {record.emergency_disabled ? (
            <>
              <Tag color="red" style={{ textDecoration: 'line-through' }}>已启用</Tag>
              <Tag color="red">紧急禁用</Tag>
            </>
          ) : (
            <Tag color={statusColor[s]}>{statusLabel[s] || s}</Tag>
          )}
        </Space>
      ) },
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
            if (hasOperation('caller_system:policy')) {
              items.push(
                record.emergency_disabled
                  ? {
                      key: 'emergency-enable',
                      label: '解除紧急禁用',
                      onClick: () => handleEmergencyEnable(record.system_id),
                    }
                  : {
                      key: 'emergency-disable',
                      label: '紧急禁用',
                      danger: true,
                      onClick: () => handleEmergencyDisable(record.system_id),
                    },
              );
            }
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
    { title: '状态', dataIndex: 'status', key: 'status', render: (s) => <Tag>{keyStatusLabel[s] || s}</Tag> },
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
            <Popconfirm
              title="确认撤销？该操作无法撤销，撤销后公钥将永久失效、不可恢复！"
              onConfirm={() => revokePublicKey(record.key_id).then(() => openDetail(detailId!))}
            >
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
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s) => <Tag>{ruleStatusLabel[s] || s}</Tag>,
    },
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
          <Button icon={<ReloadOutlined />} onClick={() => fetchSystems()}>刷新</Button>
          {hasOperation('caller_system:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              登记调用系统
            </Button>
          )}
        </Space>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="编码/名称/system_id"
          style={{ width: 240 }}
          allowClear
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onPressEnter={() => fetchSystems()}
        />
        <Select
          placeholder="状态"
          style={{ width: 130 }}
          allowClear
          value={statusFilter}
          onChange={setStatusFilter}
          options={Object.keys(statusLabel).map((s) => ({ label: statusLabel[s], value: s }))}
        />
        <Select
          placeholder="环境"
          style={{ width: 110 }}
          allowClear
          value={envFilter}
          onChange={setEnvFilter}
          options={[
            { label: '开发', value: 'development' },
            { label: '测试', value: 'staging' },
            { label: '生产', value: 'production' },
          ]}
        />
        <Button type="primary" onClick={() => fetchSystems()}>查询</Button>
        <Button onClick={() => {
          setKeyword('');
          setStatusFilter(undefined);
          setEnvFilter(undefined);
          fetchSystems({ keyword: '', status: undefined, environment: undefined });
        }}>
          重置
        </Button>
      </Space>

      <Table columns={columns} dataSource={systems} rowKey="id" loading={loading} />

      <Modal
        title="登记调用系统"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        onOk={() => createForm.submit()}
      >
        <Form form={createForm} onFinish={handleCreate} layout="vertical">
          <Form.Item name="code" label="系统编码" rules={[{ required: true }]}>
            <Input placeholder="如 erp-order" />
          </Form.Item>
          <Form.Item name="name" label="系统名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="environment" label="环境" rules={[{ required: true }]} initialValue="development">
            <Select options={[
              { label: '开发', value: 'development' },
              { label: '测试', value: 'staging' },
              { label: '生产', value: 'production' },
            ]} />
          </Form.Item>
          <Form.Item name="belongingParty" label="归属方（可选）">
            <Input placeholder="如 xx 事业部 / xx 客户" />
          </Form.Item>
          <Form.Item name="owner" label="负责人"><Input /></Form.Item>
          <Form.Item name="contact" label="联系方式"><Input /></Form.Item>
          <Form.Item name="ownerEmail" label="负责人邮箱（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="tags" label="标签（可选）">
            <Select mode="tags" placeholder="输入后回车添加" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="effectiveFrom" label="生效时间（可选）">
            <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="留空表示不限" />
          </Form.Item>
          <Form.Item name="effectiveTo" label="失效时间（可选）">
            <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="留空表示不限" />
          </Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑调用系统"
        open={editOpen}
        onCancel={() => { setEditOpen(false); editForm.resetFields(); }}
        onOk={() => editForm.submit()}
      >
        <Form form={editForm} onFinish={handleEdit} layout="vertical">
          <Form.Item name="code" label="系统编码">
            <Input disabled />
          </Form.Item>
          <Form.Item name="name" label="系统名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="belongingParty" label="归属方（可选）">
            <Input placeholder="如 xx 事业部 / xx 客户" />
          </Form.Item>
          <Form.Item name="owner" label="负责人"><Input /></Form.Item>
          <Form.Item name="contact" label="联系方式"><Input /></Form.Item>
          <Form.Item name="ownerEmail" label="负责人邮箱（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="tags" label="标签（可选）">
            <Select mode="tags" placeholder="输入后回车添加" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="effectiveFrom" label="生效时间（可选）">
            <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="留空表示不限" />
          </Form.Item>
          <Form.Item name="effectiveTo" label="失效时间（可选）">
            <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} placeholder="留空表示不限" />
          </Form.Item>
          <Form.Item name="description" label="说明"><Input.TextArea /></Form.Item>
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
              <Descriptions.Item label="环境">
                {detailSystem.environment === 'production' ? '生产'
                  : detailSystem.environment === 'staging' ? '测试'
                    : '开发'}
              </Descriptions.Item>
              <Descriptions.Item label="编码">{detailSystem.code || '-'}</Descriptions.Item>
              <Descriptions.Item label="归属方">{detailSystem.belonging_party || '-'}</Descriptions.Item>
              <Descriptions.Item label="负责人邮箱">{detailSystem.owner_email || '-'}</Descriptions.Item>
              <Descriptions.Item label="标签">
                {detailSystem.tags?.length ? detailSystem.tags.join('、') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="生命周期状态">
                <Tag color={statusColor[detailSystem.status]}>{statusLabel[detailSystem.status] || detailSystem.status}</Tag>
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
            ...(hasOperation('caller_system:policy') ? [{
              key: 'policy',
              label: '运行策略',
              children: (
                <>
                  {runtimePolicy === null && (
                    <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                      尚未配置运行策略，启用前必须配置运行 API 范围。
                    </Typography.Text>
                  )}
                  <Form
                    form={policyForm}
                    layout="vertical"
                    style={{ maxWidth: 520 }}
                    initialValues={{
                      allowed_api_patterns: [],
                      qps_limit: 10,
                      concurrency_limit: 5,
                      quota_per_day: 1000,
                      request_timeout_seconds: 30,
                      circuit_breaker_enabled: true,
                    }}
                  >
                    <Form.Item
                      name="allowed_api_patterns"
                      label="运行 API 范围"
                      rules={[{ required: true, message: '至少配置一个运行 API 范围' }]}
                    >
                      <Select
                        mode="tags"
                        placeholder="如 /api/runtime/v1/tools/execute，输入后回车添加"
                      />
                    </Form.Item>
                    <Space size="large" wrap>
                      <Form.Item name="qps_limit" label="QPS 上限" rules={[{ required: true }]}>
                        <InputNumber min={1} style={{ width: 140 }} />
                      </Form.Item>
                      <Form.Item name="concurrency_limit" label="并发上限" rules={[{ required: true }]}>
                        <InputNumber min={1} style={{ width: 140 }} />
                      </Form.Item>
                      <Form.Item name="quota_per_day" label="每日配额" rules={[{ required: true }]}>
                        <InputNumber min={1} style={{ width: 140 }} />
                      </Form.Item>
                      <Form.Item name="request_timeout_seconds" label="请求超时（秒）" rules={[{ required: true }]}>
                        <InputNumber min={1} max={300} style={{ width: 140 }} />
                      </Form.Item>
                    </Space>
                    <Form.Item name="circuit_breaker_enabled" label="启用熔断" valuePropName="checked">
                      <Switch />
                    </Form.Item>
                    <Form.Item name="effectiveFrom" label="策略生效时间（可选）">
                      <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="effectiveTo" label="策略失效时间（可选）">
                      <DatePicker showTime format="YYYY-MM-DD HH:mm" style={{ width: '100%' }} />
                    </Form.Item>
                    <Button type="primary" onClick={handleSavePolicy}>
                      {runtimePolicy === null ? '保存策略' : '更新策略'}
                    </Button>
                  </Form>
                </>
              ),
            }] : []),
            ...(hasOperation('caller_system:policy') ? [{
              key: 'tool-scopes',
              label: `工具范围 (${toolScopes.length})`,
              children: (
                <>
                  <Table
                    columns={[
                      {
                        title: '类型', dataIndex: 'scope_type', key: 'scope_type', width: 100,
                        render: (v) => (v === 'capability' ? <Tag>能力包</Tag> : <Tag color="blue">工具</Tag>),
                      },
                      {
                        title: '编码', dataIndex: 'scope_code', key: 'scope_code',
                        render: (v, record: ToolScopeItem) => (
                          <Space>
                            <span>{v}</span>
                            {record.reference_exists === false && (
                              <Tag color="red">引用不存在</Tag>
                            )}
                            {record.reference_archived && (
                              <Tag color="red">已归档</Tag>
                            )}
                          </Space>
                        ),
                      },
                      {
                        title: '状态', dataIndex: 'status', key: 'status', width: 100,
                        render: (s) => <Tag>{ruleStatusLabel[s] || s}</Tag>,
                      },
                      {
                        title: '操作', key: 'actions', width: 80,
                        render: (_, record) => (
                          <Button size="small" danger onClick={() => handleRemoveScope(record.id)}>
                            删除
                          </Button>
                        ),
                      },
                    ]}
                    dataSource={toolScopes}
                    rowKey="id"
                    size="small"
                    pagination={{ pageSize: 10 }}
                  />
                  <Form form={scopeForm} layout="inline" style={{ marginTop: 16 }}>
                    <Form.Item name="scope_type" label="类型" rules={[{ required: true }]} initialValue="tool">
                      <Select
                        style={{ width: 110 }}
                        options={[
                          { label: '工具', value: 'tool' },
                          { label: '能力包', value: 'capability' },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item name="scope_code" rules={[{ required: true }]}>
                      <Input placeholder="工具/能力包编码" style={{ width: 220 }} />
                    </Form.Item>
                    <Form.Item name="status" label="状态" rules={[{ required: true }]} initialValue="active">
                      <Select
                        style={{ width: 110 }}
                        options={[
                          { label: '已启用', value: 'active' },
                          { label: '已停用', value: 'disabled' },
                        ]}
                      />
                    </Form.Item>
                    <Button type="primary" onClick={handleAddScope}>添加</Button>
                    <Button onClick={handleSaveScopes}>保存范围</Button>
                  </Form>
                </>
              ),
            }] : []),
          ]}
        />
      </Modal>
    </>
  );
}
