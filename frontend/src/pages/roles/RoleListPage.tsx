import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, message, Space, Tag, Typography, Select, Popconfirm,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listRoles, createRole, updateRole, updateRoleStatus,
  getRoleOperations, assignOperations, removeOperations, listAllOperations,
  type RoleItem, type OperationItem,
} from '../../api/roles';
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
      title: '操作', key: 'actions', width: 300,
      render: (_, record) => (
        <Space size="small">
          {hasOperation('role:edit') && (
            <Button size="small" onClick={() => openOpsModal(record.id)}>操作项</Button>
          )}
          {hasOperation('role:manage') && !record.is_super_admin && record.status === 'active' && (
            <Popconfirm title="确认停用？" onConfirm={() => handleStatus(record.id, 'disabled')}>
              <Button size="small">停用</Button>
            </Popconfirm>
          )}
          {hasOperation('role:manage') && record.status === 'disabled' && (
            <Popconfirm title="确认启用？" onConfirm={() => handleStatus(record.id, 'active')}>
              <Button size="small">启用</Button>
            </Popconfirm>
          )}
          {hasOperation('role:manage') && record.status !== 'archived' && !record.is_super_admin && (
            <Popconfirm title="确认归档？" onConfirm={() => handleStatus(record.id, 'archived')}>
              <Button size="small">归档</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const assignedCodes = new Set(roleOps.map((o) => o.operation_code));
  const availableOps = allOps.filter((o) => !assignedCodes.has(o.operation_code));

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
        title="管理操作项"
        open={opsModalOpen}
        onCancel={() => setOpsModalOpen(false)}
        footer={null}
        width={600}
      >
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong>已分配的操作项：</Typography.Text>
          {roleOps.length === 0 && <div style={{ color: '#999', marginTop: 8 }}>暂无</div>}
          <div style={{ marginTop: 8 }}>
            {roleOps.map((op) => (
              <Tag
                key={op.operation_code}
                closable
                onClose={() => handleRemoveOp(op.operation_code)}
                style={{ marginBottom: 8 }}
              >
                {op.display_name}
              </Tag>
            ))}
          </div>
        </div>
        <div>
          <Typography.Text strong>添加操作项：</Typography.Text>
          <Select
            mode="multiple"
            style={{ width: '100%', marginTop: 8 }}
            placeholder="搜索并选择操作项"
            options={availableOps.map((op) => ({
              label: `${op.display_name} (${op.operation_code})`,
              value: op.operation_code,
            }))}
            onChange={handleAssignOps}
            value={[]}
          />
        </div>
      </Modal>
    </>
  );
}
