import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, message, Space, Tag, Typography, Select, Dropdown,
} from 'antd';
import { PlusOutlined, ReloadOutlined, EllipsisOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { MenuProps } from 'antd';
import {
  listRoles, createRole, updateRole, updateRoleStatus,
  getRoleOperations, assignOperations, removeOperations, listAllOperations,
  listRoleAccounts, type RoleItem, type OperationItem, type RoleAccountItem,
} from '../../api/roles';
import {
  listAccounts, assignRoleToAccount, removeRoleFromAccount, type AccountItem,
} from '../../api/accounts';
import { useAuth } from '../../contexts/AuthContext';

const { Title } = Typography;

const statusColor: Record<string, string> = { active: 'green', disabled: 'orange', archived: 'red' };

export default function RoleListPage() {
  const { hasOperation } = useAuth();
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [opsModalOpen, setOpsModalOpen] = useState(false);
  const [opsRoleId, setOpsRoleId] = useState<string | null>(null);
  const [allOps, setAllOps] = useState<OperationItem[]>([]);
  const [roleOps, setRoleOps] = useState<OperationItem[]>([]);
  const [opsVersion, setOpsVersion] = useState(0);
  const [accountsOpen, setAccountsOpen] = useState(false);
  const [accountsRoleId, setAccountsRoleId] = useState<string | null>(null);
  const [roleAccounts, setRoleAccounts] = useState<RoleAccountItem[]>([]);
  const [allAccounts, setAllAccounts] = useState<AccountItem[]>([]);
  const [accountsVersion, setAccountsVersion] = useState(0);

  const fetchRoles = async () => {
    setLoading(true);
    try {
      const { items, total: t } = await listRoles();
      setRoles(items);
      setTotal(t);
    } catch {
      message.error('加载角色列表失败');
    } finally {
      setLoading(false);
    }
  };

  const fetchAllOps = async () => {
    try {
      setAllOps(await listAllOperations());
    } catch { /* ignore */ }
  };

  useEffect(() => { fetchRoles(); fetchAllOps(); }, []);

  const handleCreate = async (values: { name: string; description?: string }) => {
    try {
      await createRole(values.name, values.description);
      message.success('角色创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      fetchRoles();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '创建失败';
      message.error(msg);
    }
  };

  const handleStatus = async (id: string, status: string) => {
    try {
      await updateRoleStatus(id, status);
      message.success('操作成功');
      fetchRoles();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '操作失败';
      message.error(msg);
    }
  };

  const confirmStatus = (record: RoleItem, status: string, action: string) => {
    Modal.confirm({
      title: `确认${action}？`,
      content: `确认${action}角色「${record.name}」？`,
      onOk: () => handleStatus(record.id, status),
    });
  };

  const openOpsModal = async (roleId: string) => {
    setOpsRoleId(roleId);
    try {
      setRoleOps(await getRoleOperations(roleId));
    } catch {
      setRoleOps([]);
    }
    setOpsModalOpen(true);
  };

  const handleAssignOps = async (codes: string[]) => {
    if (!opsRoleId) return;
    try {
      await assignOperations(opsRoleId, codes);
      message.success('操作项已分配');
      setRoleOps(await getRoleOperations(opsRoleId));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '分配失败';
      message.error(msg);
    }
  };

  const handleRemoveOp = async (code: string) => {
    if (!opsRoleId) return;
    try {
      await removeOperations(opsRoleId, [code]);
      message.success('已移除');
      setRoleOps(await getRoleOperations(opsRoleId));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '移除失败';
      message.error(msg);
      // 后端拒绝时恢复真实状态：重取操作项并强制重挂载 Tag（antd Tag 关闭后会自行隐藏）
      try {
        setRoleOps(await getRoleOperations(opsRoleId));
        setOpsVersion((v) => v + 1);
      } catch { /* 忽略恢复失败 */ }
    }
  };

  const openAccountsModal = async (roleId: string) => {
    setAccountsRoleId(roleId);
    try {
      setRoleAccounts(await listRoleAccounts(roleId));
      const { items } = await listAccounts();
      setAllAccounts(items);
    } catch {
      setRoleAccounts([]);
      setAllAccounts([]);
    }
    setAccountsOpen(true);
  };

  const handleAssignAccount = async (accountId: string) => {
    if (!accountsRoleId) return;
    try {
      await assignRoleToAccount(accountId, accountsRoleId);
      message.success('已分配');
      setRoleAccounts(await listRoleAccounts(accountsRoleId));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '分配失败';
      message.error(msg);
    }
  };

  const handleRemoveAccount = async (accountId: string) => {
    if (!accountsRoleId) return;
    try {
      await removeRoleFromAccount(accountId, accountsRoleId);
      message.success('已移除');
      setRoleAccounts(await listRoleAccounts(accountsRoleId));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '移除失败';
      message.error(msg);
      // 后端拒绝时恢复真实状态：重取账号列表并强制重挂载 Tag
      try {
        setRoleAccounts(await listRoleAccounts(accountsRoleId));
        setAccountsVersion((v) => v + 1);
      } catch { /* 忽略恢复失败 */ }
    }
  };

  const columns: ColumnsType<RoleItem> = [
    { title: '角色名', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description', render: (v) => v || '-' },
    {
      title: '超管', dataIndex: 'is_super_admin', key: 'is_super_admin', width: 80,
      render: (v) => v ? <Tag color="red">是</Tag> : <Tag>否</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s) => <Tag color={statusColor[s]}>{s}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_, record) => {
        const items: MenuProps['items'] = [];
        if (hasOperation('role:edit') && !record.is_super_admin && record.status !== 'archived') {
          items.push({
            key: 'ops',
            label: '操作权限',
            onClick: () => openOpsModal(record.id),
          });
        }
        if (hasOperation('role:view') && !record.is_super_admin && record.status !== 'archived') {
          items.push({
            key: 'accounts',
            label: '分配账号',
            onClick: () => openAccountsModal(record.id),
          });
        }
        if (hasOperation('role:manage') && !record.is_super_admin && record.status === 'active') {
          items.push({
            key: 'disable',
            label: '停用',
            onClick: () => confirmStatus(record, 'disabled', '停用'),
          });
        }
        if (hasOperation('role:manage') && record.status === 'disabled') {
          items.push({
            key: 'enable',
            label: '启用',
            onClick: () => confirmStatus(record, 'active', '启用'),
          });
        }
        if (hasOperation('role:manage') && record.status !== 'archived' && !record.is_super_admin) {
          items.push({
            key: 'archive',
            label: '归档',
            danger: true,
            onClick: () => confirmStatus(record, 'archived', '归档'),
          });
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

  const assignedCodes = new Set(roleOps.map((o) => o.operation_code));
  const availableOps = allOps.filter((o) => !assignedCodes.has(o.operation_code));
  const currentRole = roles.find((r) => r.id === opsRoleId);
  const isSuperAdminRole = currentRole?.is_super_admin ?? false;

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>后台角色 ({total})</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchRoles}>刷新</Button>
          {hasOperation('role:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建角色
            </Button>
          )}
        </Space>
      </div>

      <Table columns={columns} dataSource={roles} rowKey="id" loading={loading} />

      <Modal
        title="创建角色"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        onOk={() => createForm.submit()}
      >
        <Form form={createForm} onFinish={handleCreate} layout="vertical">
          <Form.Item name="name" label="角色名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="管理操作权限"
        open={opsModalOpen}
        onCancel={() => setOpsModalOpen(false)}
        footer={null}
        width={600}
      >
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong>已分配的操作权限：</Typography.Text>
          {roleOps.length === 0 && <div style={{ color: '#999', marginTop: 8 }}>暂无</div>}
          <div style={{ marginTop: 8 }}>
            {roleOps.map((op) => (
              <Tag
                key={`${op.operation_code}-${opsVersion}`}
                closable={!isSuperAdminRole}
                onClose={() => handleRemoveOp(op.operation_code)}
                style={{ marginBottom: 8 }}
              >
                {op.display_name}
              </Tag>
            ))}
          </div>
        </div>
        {!isSuperAdminRole && (
          <div>
            <Typography.Text strong>添加操作权限：</Typography.Text>
            <Select
              mode="multiple"
              style={{ width: '100%', marginTop: 8 }}
              placeholder="搜索并选择操作权限"
              options={availableOps.map((op) => ({
                label: `${op.display_name} (${op.operation_code})`,
                value: op.operation_code,
              }))}
              onChange={handleAssignOps}
              value={[]}
            />
          </div>
        )}
      </Modal>

      <Modal
        title="分配账号"
        open={accountsOpen}
        onCancel={() => setAccountsOpen(false)}
        footer={null}
        width={520}
      >
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong>已分配的账号：</Typography.Text>
          {roleAccounts.length === 0 && <div style={{ color: '#999', marginTop: 8 }}>暂无</div>}
          <div style={{ marginTop: 8 }}>
            {roleAccounts.map((item) => (
              <Tag
                key={`${item.id}-${accountsVersion}`}
                closable={hasOperation('role:assign')}
                onClose={() => handleRemoveAccount(item.id)}
                style={{ marginBottom: 8 }}
              >
                {item.account}（{item.real_name}）
              </Tag>
            ))}
          </div>
        </div>
        {hasOperation('role:assign') && (
          <div>
            <Typography.Text strong>添加账号：</Typography.Text>
            <Select
              style={{ width: '100%', marginTop: 8 }}
              placeholder="选择要分配的角色所属账号"
              options={allAccounts
                .filter((item) => item.status !== 'offboarded'
                  && !roleAccounts.some((assigned) => assigned.id === item.id))
                .map((item) => ({
                  label: `${item.account}（${item.real_name}）`,
                  value: item.id,
                }))}
              onChange={handleAssignAccount}
              value={null}
            />
          </div>
        )}
      </Modal>
    </>
  );
}
