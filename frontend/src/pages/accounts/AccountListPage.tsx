import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, message, Space, Tag, Typography, Dropdown, Select,
} from 'antd';
import { PlusOutlined, ReloadOutlined, EllipsisOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { MenuProps } from 'antd';
import {
  listAccounts, createAccount, updateAccountStatus, resetPassword, forceLogout,
  offboardAccount, updateAccountProfile, listAccountRoles, assignRoleToAccount,
  removeRoleFromAccount,
  type AccountItem,
} from '../../api/accounts';
import { listRoles, type RoleItem } from '../../api/roles';
import { useAuth } from '../../contexts/AuthContext';

const { Title } = Typography;

const statusColor: Record<string, string> = {
  enabled: 'green', disabled: 'red', locked: 'orange', offboarded: 'purple',
};
const statusLabel: Record<string, string> = {
  enabled: '已启用', disabled: '已禁用', locked: '已锁定', offboarded: '已离职',
};

export default function AccountListPage() {
  const { hasOperation } = useAuth();
  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editRowVersion, setEditRowVersion] = useState<number | null>(null);
  const [editForm] = Form.useForm();
  const [resetResult, setResetResult] = useState<string | null>(null);
  const [rolesOpen, setRolesOpen] = useState(false);
  const [rolesAccountId, setRolesAccountId] = useState<string | null>(null);
  const [accountRoles, setAccountRoles] = useState<RoleItem[]>([]);
  const [allRoles, setAllRoles] = useState<RoleItem[]>([]);
  const [rolesVersion, setRolesVersion] = useState(0);
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [department, setDepartment] = useState('');

  const fetchAccounts = async (override?: {
    keyword?: string;
    status?: string;
    department?: string;
  }) => {
    setLoading(true);
    try {
      const { items, total: t } = await listAccounts(0, 50, {
        keyword: (override?.keyword ?? keyword).trim() || undefined,
        status: override?.status ?? statusFilter,
        department: (override?.department ?? department).trim() || undefined,
      });
      setAccounts(items);
      setTotal(t);
    } catch {
      message.error('加载账号列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAccounts(); }, []);

  const handleCreate = async (values: {
    account: string;
    real_name: string;
    external_user_id?: string;
    email?: string;
    mobile?: string;
    department?: string;
    remark?: string;
  }) => {
    try {
      const result = await createAccount(values.account, values.real_name, {
        external_user_id: values.external_user_id || undefined,
        email: values.email || undefined,
        mobile: values.mobile || undefined,
        department: values.department || undefined,
        remark: values.remark || undefined,
      });
      message.success('账号创建成功');
      setResetResult(`临时密码：${result.temp_password}（请通知用户首次登录修改）`);
      setCreateOpen(false);
      createForm.resetFields();
      fetchAccounts();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '创建失败';
      message.error(msg);
    }
  };

  const openEdit = (record: AccountItem) => {
    setEditId(record.id);
    setEditRowVersion(record.row_version);
    editForm.setFieldsValue({
      real_name: record.real_name,
      email: record.email ?? undefined,
      mobile: record.mobile ?? undefined,
      department: record.department ?? undefined,
      remark: record.remark ?? undefined,
    });
    setEditOpen(true);
  };

  const handleEdit = async (values: {
    real_name: string;
    email?: string;
    mobile?: string;
    department?: string;
    remark?: string;
  }) => {
    if (!editId || editRowVersion === null) return;
    try {
      await updateAccountProfile(editId, {
        real_name: values.real_name,
        email: values.email || undefined,
        mobile: values.mobile || undefined,
        department: values.department || undefined,
        remark: values.remark || undefined,
        row_version: editRowVersion,
      });
      message.success('账号资料已更新');
      setEditOpen(false);
      editForm.resetFields();
      fetchAccounts();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '修改失败';
      message.error(msg);
    }
  };

  const openRolesModal = async (accountId: string) => {
    setRolesAccountId(accountId);
    try {
      setAccountRoles(await listAccountRoles(accountId));
      const { items } = await listRoles();
      setAllRoles(items);
    } catch {
      setAccountRoles([]);
      setAllRoles([]);
    }
    setRolesOpen(true);
  };

  const handleAssignRole = async (roleId: string) => {
    if (!rolesAccountId) return;
    try {
      await assignRoleToAccount(rolesAccountId, roleId);
      message.success('角色已分配');
      setAccountRoles(await listAccountRoles(rolesAccountId));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '分配失败';
      message.error(msg);
    }
  };

  const handleRemoveRole = async (roleId: string) => {
    if (!rolesAccountId) return;
    try {
      await removeRoleFromAccount(rolesAccountId, roleId);
      message.success('已移除');
      setAccountRoles(await listAccountRoles(rolesAccountId));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '移除失败';
      message.error(msg);
      // 后端拒绝时恢复真实状态：重取角色列表并强制重挂载 Tag
      try {
        setAccountRoles(await listAccountRoles(rolesAccountId));
        setRolesVersion((v) => v + 1);
      } catch { /* 忽略恢复失败 */ }
    }
  };

  const handleAction = async (id: string, action: 'enable' | 'disable' | 'unlock') => {
    try {
      await updateAccountStatus(id, action);
      message.success('操作成功');
      fetchAccounts();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '操作失败';
      message.error(msg);
    }
  };

  const handleResetPassword = async (id: string) => {
    try {
      const { temp_password } = await resetPassword(id);
      setResetResult(`新临时密码：${temp_password}`);
      message.success('密码已重置');
      fetchAccounts();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '重置失败';
      message.error(msg);
    }
  };

  const handleForceLogout = async (id: string) => {
    try {
      await forceLogout(id);
      message.success('已强制下线');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '操作失败';
      message.error(msg);
    }
  };

  const handleOffboard = async (id: string) => {
    try {
      await offboardAccount(id);
      message.success('已执行离职处理');
      fetchAccounts();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '操作失败';
      message.error(msg);
    }
  };

  const columns: ColumnsType<AccountItem> = [
    { title: '账号', dataIndex: 'account', key: 'account' },
    { title: '工号', dataIndex: 'external_user_id', key: 'external_user_id', render: (v) => v || '-' },
    { title: '姓名', dataIndex: 'real_name', key: 'real_name' },
    { title: '邮箱', dataIndex: 'email', key: 'email', render: (v) => v || '-' },
    { title: '手机号', dataIndex: 'mobile', key: 'mobile', render: (v) => v || '-' },
    { title: '部门', dataIndex: 'department', key: 'department', render: (v) => v || '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s) => <Tag color={statusColor[s] || 'default'}>{statusLabel[s] || s}</Tag>,
    },
    { title: '登录失败次数', dataIndex: 'login_failures', key: 'login_failures', width: 120 },
    {
      title: '密码', dataIndex: 'must_change_password', key: 'must_change_password', width: 100,
      render: (v) => v ? <Tag color="orange">需修改</Tag> : <Tag color="green">正常</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_, record) => {
        if (!hasOperation('admin_account:manage')) return null;

        const confirmAction = (title: string, content: string, onOk: () => void) => {
          Modal.confirm({ title, content, onOk });
        };

        const items: MenuProps['items'] = [];
        if (record.status !== 'offboarded') {
          items.push({
            key: 'edit',
            label: '编辑',
            onClick: () => openEdit(record),
          });
          if (hasOperation('role:view')) {
            items.push({
              key: 'roles',
              label: '分配角色',
              onClick: () => openRolesModal(record.id),
            });
          }
        }
        if (record.status === 'disabled') {
          items.push({
            key: 'enable',
            label: '启用',
            onClick: () => confirmAction('启用账号', `确认启用 ${record.account}？`, () => handleAction(record.id, 'enable')),
          });
        }
        if (record.status === 'enabled') {
          items.push({
            key: 'disable',
            label: '禁用',
            danger: true,
            onClick: () => confirmAction('禁用账号', `确认禁用 ${record.account}？`, () => handleAction(record.id, 'disable')),
          });
        }
        if (record.status === 'locked') {
          items.push({
            key: 'unlock',
            label: '解锁',
            onClick: () => confirmAction('解锁账号', `确认解锁 ${record.account}？`, () => handleAction(record.id, 'unlock')),
          });
        }
        if (record.status !== 'offboarded') {
          if (items.length > 0) {
            items.push({ type: 'divider' });
          }
          items.push({
            key: 'reset-password',
            label: '重置密码',
            onClick: () => confirmAction('重置密码', `确认重置 ${record.account} 的密码？`, () => handleResetPassword(record.id)),
          });
          items.push({
            key: 'force-logout',
            label: '强制下线',
            onClick: () => confirmAction('强制下线', `确认将 ${record.account} 强制下线？`, () => handleForceLogout(record.id)),
          });
          items.push({
            key: 'offboard',
            label: '离职',
            danger: true,
            onClick: () => confirmAction(
              '离职处理',
              `确认对 ${record.account} 执行离职处理？账号将标记为已离职并撤销全部会话。`,
              () => handleOffboard(record.id),
            ),
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

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>管理账号 ({total})</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => fetchAccounts()}>刷新</Button>
          {hasOperation('admin_account:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建账号
            </Button>
          )}
        </Space>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="账号/姓名/工号"
          style={{ width: 220 }}
          allowClear
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onPressEnter={() => fetchAccounts()}
        />
        <Select
          placeholder="状态"
          style={{ width: 140 }}
          allowClear
          value={statusFilter}
          onChange={setStatusFilter}
          options={Object.keys(statusLabel).map((s) => ({ label: statusLabel[s], value: s }))}
        />
        <Input
          placeholder="部门"
          style={{ width: 180 }}
          allowClear
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          onPressEnter={() => fetchAccounts()}
        />
        <Button type="primary" onClick={() => fetchAccounts()}>查询</Button>
        <Button onClick={() => fetchAccounts({ keyword: '', status: undefined, department: '' })}>
          重置
        </Button>
      </Space>

      {resetResult && (
        <div style={{ marginBottom: 16, padding: 12, background: '#fff7e6', borderRadius: 8, wordBreak: 'break-all' }}>
          <strong>{resetResult}</strong>
          <Button type="link" size="small" onClick={() => setResetResult(null)}>关闭</Button>
        </div>
      )}

      <Table columns={columns} dataSource={accounts} rowKey="id" loading={loading} />

      <Modal
        title="创建账号"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        onOk={() => createForm.submit()}
      >
        <Form form={createForm} onFinish={handleCreate} layout="vertical">
          <Form.Item name="account" label="账号" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="real_name" label="姓名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="external_user_id" label="工号（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="mobile" label="手机号（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="department" label="部门（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="remark" label="备注（可选）">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑账号资料"
        open={editOpen}
        onCancel={() => { setEditOpen(false); editForm.resetFields(); }}
        onOk={() => editForm.submit()}
      >
        <Form form={editForm} onFinish={handleEdit} layout="vertical">
          <Form.Item name="real_name" label="姓名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="mobile" label="手机号（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="department" label="部门（可选）">
            <Input />
          </Form.Item>
          <Form.Item name="remark" label="备注（可选）">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="角色分配"
        open={rolesOpen}
        onCancel={() => setRolesOpen(false)}
        footer={null}
        width={520}
      >
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong>已分配的角色：</Typography.Text>
          {accountRoles.length === 0 && <div style={{ color: '#999', marginTop: 8 }}>暂无</div>}
          <div style={{ marginTop: 8 }}>
            {accountRoles.map((role) => (
              <Tag
                key={`${role.id}-${rolesVersion}`}
                color={role.is_super_admin ? 'red' : undefined}
                closable={hasOperation('role:assign')}
                onClose={() => handleRemoveRole(role.id)}
                style={{ marginBottom: 8 }}
              >
                {role.name}
              </Tag>
            ))}
          </div>
        </div>
        {hasOperation('role:assign') && (
          <div>
            <Typography.Text strong>添加角色：</Typography.Text>
            <Select
              style={{ width: '100%', marginTop: 8 }}
              placeholder="选择要分配的角色"
              options={allRoles
                .filter((role) => role.status === 'active'
                  && !accountRoles.some((assigned) => assigned.id === role.id))
                .map((role) => ({ label: role.name, value: role.id }))}
              onChange={handleAssignRole}
              value={null}
            />
          </div>
        )}
      </Modal>
    </>
  );
}
