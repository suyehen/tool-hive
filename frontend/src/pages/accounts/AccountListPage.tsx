import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, message, Space, Tag, Typography, Dropdown,
} from 'antd';
import { PlusOutlined, ReloadOutlined, EllipsisOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import type { MenuProps } from 'antd';
import {
  listAccounts, createAccount, updateAccountStatus, resetPassword, forceLogout,
  offboardAccount,
  type AccountItem,
} from '../../api/accounts';
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
  const [resetResult, setResetResult] = useState<string | null>(null);

  const fetchAccounts = async () => {
    setLoading(true);
    try {
      const { items, total: t } = await listAccounts();
      setAccounts(items);
      setTotal(t);
    } catch {
      message.error('加载账号列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAccounts(); }, []);

  const handleCreate = async (values: { username: string; external_user_id?: string }) => {
    try {
      const result = await createAccount(values.username, values.external_user_id);
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
    { title: '工号', dataIndex: 'external_user_id', key: 'external_user_id', render: (v) => v || '-' },
    { title: '用户名', dataIndex: 'username', key: 'username' },
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
        if (record.status === 'disabled') {
          items.push({
            key: 'enable',
            label: '启用',
            onClick: () => confirmAction('启用账号', `确认启用 ${record.username}？`, () => handleAction(record.id, 'enable')),
          });
        }
        if (record.status === 'enabled') {
          items.push({
            key: 'disable',
            label: '禁用',
            danger: true,
            onClick: () => confirmAction('禁用账号', `确认禁用 ${record.username}？`, () => handleAction(record.id, 'disable')),
          });
        }
        if (record.status === 'locked') {
          items.push({
            key: 'unlock',
            label: '解锁',
            onClick: () => confirmAction('解锁账号', `确认解锁 ${record.username}？`, () => handleAction(record.id, 'unlock')),
          });
        }
        if (record.status !== 'offboarded') {
          if (items.length > 0) {
            items.push({ type: 'divider' });
          }
          items.push({
            key: 'reset-password',
            label: '重置密码',
            onClick: () => confirmAction('重置密码', `确认重置 ${record.username} 的密码？`, () => handleResetPassword(record.id)),
          });
          items.push({
            key: 'force-logout',
            label: '强制下线',
            onClick: () => confirmAction('强制下线', `确认将 ${record.username} 强制下线？`, () => handleForceLogout(record.id)),
          });
          items.push({
            key: 'offboard',
            label: '离职',
            danger: true,
            onClick: () => confirmAction(
              '离职处理',
              `确认对 ${record.username} 执行离职处理？账号将标记为已离职并撤销全部会话。`,
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
          <Button icon={<ReloadOutlined />} onClick={fetchAccounts}>刷新</Button>
          {hasOperation('admin_account:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建账号
            </Button>
          )}
        </Space>
      </div>

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
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="external_user_id" label="工号（可选）">
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
