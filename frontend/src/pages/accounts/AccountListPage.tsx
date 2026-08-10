import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, message, Space, Tag, Typography, Popconfirm, Tooltip,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listAccounts, createAccount, updateAccountStatus, resetPassword, forceLogout,
  type AccountItem,
} from '../../api/accounts';

const { Title } = Typography;

const statusColor: Record<string, string> = {
  enabled: 'green', disabled: 'red', locked: 'orange',
};
const statusLabel: Record<string, string> = {
  enabled: '已启用', disabled: '已禁用', locked: '已锁定',
};

export default function AccountListPage() {
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

  const columns: ColumnsType<AccountItem> = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '工号', dataIndex: 'external_user_id', key: 'external_user_id', render: (v) => v || '-' },
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
      title: '操作', key: 'actions', width: 300,
      render: (_, record) => (
        <Space size="small" wrap>
          {record.status === 'disabled' && (
            <Popconfirm title="确认启用？" onConfirm={() => handleAction(record.id, 'enable')}>
              <Button size="small">启用</Button>
            </Popconfirm>
          )}
          {record.status === 'enabled' && (
            <Popconfirm title="确认禁用？" onConfirm={() => handleAction(record.id, 'disable')}>
              <Button size="small" danger>禁用</Button>
            </Popconfirm>
          )}
          {record.status === 'locked' && (
            <Popconfirm title="确认解锁？" onConfirm={() => handleAction(record.id, 'unlock')}>
              <Button size="small">解锁</Button>
            </Popconfirm>
          )}
          <Popconfirm title="确认重置密码？" onConfirm={() => handleResetPassword(record.id)}>
            <Button size="small">重置密码</Button>
          </Popconfirm>
          <Popconfirm title="确认强制下线？" onConfirm={() => handleForceLogout(record.id)}>
            <Button size="small">强制下线</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>管理账号 ({total})</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchAccounts}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            创建账号
          </Button>
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
