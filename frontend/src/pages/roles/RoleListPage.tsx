import { useEffect, useState, type Key } from 'react';
import {
  Table, Button, Modal, Form, Input, InputNumber, message, Space, Tag, Typography, Dropdown, Transfer, Select,
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
const statusLabel: Record<string, string> = {
  active: '启用',
  disabled: '停用',
  archived: '已归档',
};
const categoryLabels: Record<string, string> = {
  account: '管理账号',
  role: '后台角色',
  caller_system: '调用系统',
  tool: '工具',
  provider: 'Provider',
  system_task: '系统任务',
};
const categoryOrder = ['account', 'role', 'caller_system', 'tool', 'provider', 'system_task'];

export default function RoleListPage() {
  const { hasOperation } = useAuth();
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editRowVersion, setEditRowVersion] = useState<number | null>(null);
  const [editForm] = Form.useForm();
  const [opsModalOpen, setOpsModalOpen] = useState(false);
  const [opsRoleId, setOpsRoleId] = useState<string | null>(null);
  const [allOps, setAllOps] = useState<OperationItem[]>([]);
  const [roleOps, setRoleOps] = useState<OperationItem[]>([]);
  const [opsCategory, setOpsCategory] = useState<string | undefined>(undefined);
  const [opsSelected, setOpsSelected] = useState<string[]>([]);
  const [accountsOpen, setAccountsOpen] = useState(false);
  const [accountsRoleId, setAccountsRoleId] = useState<string | null>(null);
  const [roleAccounts, setRoleAccounts] = useState<RoleAccountItem[]>([]);
  const [allAccounts, setAllAccounts] = useState<AccountItem[]>([]);
  const [accountsSelected, setAccountsSelected] = useState<string[]>([]);
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);

  const fetchRoles = async (override?: { keyword?: string; status?: string }) => {
    // 未传 override 时使用当前筛选状态；传了则完全以 override 为准（重置场景）
    const kw = override === undefined ? keyword : (override.keyword ?? '');
    const st = override === undefined ? statusFilter : override.status;
    setLoading(true);
    try {
      const { items, total: t } = await listRoles(0, 50, {
        keyword: kw.trim() || undefined,
        status: st,
      });
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

  const handleCreate = async (values: {
    code: string;
    name: string;
    sort_order: number;
    description?: string;
  }) => {
    try {
      await createRole(values.code, values.name, {
        sort_order: values.sort_order,
        description: values.description,
      });
      message.success('角色创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      fetchRoles();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '创建失败';
      message.error(msg);
    }
  };

  const openEdit = (record: RoleItem) => {
    setEditId(record.id);
    setEditRowVersion(record.row_version);
    editForm.setFieldsValue({
      code: record.code,
      name: record.name,
      description: record.description ?? undefined,
      sort_order: record.sort_order,
    });
    setEditOpen(true);
  };

  const handleEdit = async (values: {
    name: string;
    description?: string;
    sort_order: number;
  }) => {
    if (!editId || editRowVersion === null) return;
    try {
      await updateRole(editId, {
        name: values.name,
        description: values.description || undefined,
        sort_order: values.sort_order,
        row_version: editRowVersion,
      });
      message.success('角色已更新');
      setEditOpen(false);
      editForm.resetFields();
      fetchRoles();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '更新失败';
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
      content: status === 'archived'
        ? `确认归档角色「${record.name}」？该操作无法撤销，归档后角色将永久停用、不可恢复。`
        : `确认${action}角色「${record.name}」？`,
      onOk: () => handleStatus(record.id, status),
    });
  };

  const openOpsModal = async (roleId: string) => {
    setOpsRoleId(roleId);
    setOpsCategory(undefined);
    setOpsSelected([]);
    try {
      setRoleOps(await getRoleOperations(roleId));
    } catch {
      setRoleOps([]);
    }
    setOpsModalOpen(true);
  };

  const handleOpsTransfer = async (
    _nextTargetKeys: Key[],
    direction: 'left' | 'right',
    moveKeys: Key[],
  ) => {
    if (!opsRoleId || moveKeys.length === 0) return;
    const keys = moveKeys.map(String);
    const previous = roleOps;
    // 乐观更新：先移动穿梭框中的条目，接口失败再回滚
    if (direction === 'right') {
      const moved = allOps.filter((op) => keys.includes(op.operation_code));
      setRoleOps([...roleOps, ...moved]);
    } else {
      setRoleOps(roleOps.filter((op) => !keys.includes(op.operation_code)));
    }
    try {
      if (direction === 'right') {
        await assignOperations(opsRoleId, keys);
      } else {
        await removeOperations(opsRoleId, keys);
      }
      message.success('操作权限已更新');
      setRoleOps(await getRoleOperations(opsRoleId));
    } catch (err: unknown) {
      setRoleOps(previous);
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '更新失败';
      message.error(msg);
    }
    setOpsSelected([]);
  };

  const openAccountsModal = async (roleId: string) => {
    setAccountsRoleId(roleId);
    setAccountsSelected([]);
    try {
      setRoleAccounts(await listRoleAccounts(roleId));
      const { items } = await listAccounts(0, 200);
      setAllAccounts(items);
    } catch {
      setRoleAccounts([]);
      setAllAccounts([]);
    }
    setAccountsOpen(true);
  };

  const handleAccountsTransfer = async (
    _nextTargetKeys: Key[],
    direction: 'left' | 'right',
    moveKeys: Key[],
  ) => {
    if (!accountsRoleId || moveKeys.length === 0) return;
    const keys = moveKeys.map(String);
    const previous = roleAccounts;
    // 乐观更新：先移动穿梭框中的条目，接口失败再回滚
    if (direction === 'right') {
      const moved = allAccounts
        .filter((item) => keys.includes(item.id))
        .map((item) => ({
          id: item.id,
          account: item.account,
          real_name: item.real_name,
          status: item.status,
        }));
      setRoleAccounts([...roleAccounts, ...moved]);
    } else {
      setRoleAccounts(roleAccounts.filter((item) => !moveKeys.includes(item.id)));
    }
    try {
      if (direction === 'right') {
        for (const accountId of keys) {
          await assignRoleToAccount(accountId, accountsRoleId);
        }
      } else {
        for (const accountId of keys) {
          await removeRoleFromAccount(accountId, accountsRoleId);
        }
      }
      message.success('账号已更新');
      setRoleAccounts(await listRoleAccounts(accountsRoleId));
    } catch (err: unknown) {
      setRoleAccounts(previous);
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '更新失败';
      message.error(msg);
    }
    setAccountsSelected([]);
  };

  const columns: ColumnsType<RoleItem> = [
    { title: '编码', dataIndex: 'code', key: 'code' },
    { title: '角色名', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description', render: (v) => v || '-' },
    {
      title: '超管', dataIndex: 'is_super_admin', key: 'is_super_admin', width: 80,
      render: (v) => v ? <Tag color="red">是</Tag> : <Tag>否</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s) => <Tag color={statusColor[s]}>{statusLabel[s] || s}</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 80,
      render: (_, record) => {
        const items: MenuProps['items'] = [];
        if (hasOperation('role:edit') && !record.is_super_admin && record.status !== 'archived') {
          items.push({
            key: 'edit',
            label: '编辑',
            onClick: () => openEdit(record),
          });
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

  const currentRole = roles.find((r) => r.id === opsRoleId);
  const isSuperAdminRole = currentRole?.is_super_admin ?? false;

  // 当前分类筛选下可见的操作权限（按分类 + 组内排序）
  const visibleOps = allOps
    .filter((op) => !opsCategory || op.category === opsCategory)
    .sort((a, b) => (
      a.category === b.category
        ? a.sort_order - b.sort_order
        : categoryOrder.indexOf(a.category) - categoryOrder.indexOf(b.category)
    ));
  const assignedOpCodes = new Set(roleOps.map((op) => op.operation_code));
  // 未离职的全部账号（穿梭框数据源）
  const visibleAccounts = allAccounts.filter((item) => item.status !== 'offboarded');
  const assignedAccountIds = new Set(roleAccounts.map((item) => item.id));

  // 面板级选择工具：select=全选、deselect=清空、invert=反选（只作用于传入的 paneKeys）
  const applySelection = (
    setter: (updater: (prev: string[]) => string[]) => void,
    paneKeys: string[],
    mode: 'select' | 'deselect' | 'invert',
  ) => {
    const paneSet = new Set(paneKeys);
    setter((prev) => {
      if (mode === 'deselect') {
        return prev.filter((key) => !paneSet.has(key));
      }
      if (mode === 'select') {
        return [...prev.filter((key) => !paneSet.has(key)), ...paneKeys];
      }
      const prevSet = new Set(prev);
      return [
        ...prev.filter((key) => paneSet.has(key)),
        ...paneKeys.filter((key) => !prevSet.has(key)),
      ];
    });
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>后台角色 ({total})</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => fetchRoles()}>刷新</Button>
          {hasOperation('role:create') && (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              创建角色
            </Button>
          )}
        </Space>
      </div>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="编码/角色名"
          style={{ width: 220 }}
          allowClear
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onPressEnter={() => fetchRoles()}
        />
        <Select
          placeholder="状态"
          style={{ width: 140 }}
          allowClear
          value={statusFilter}
          onChange={setStatusFilter}
          options={Object.keys(statusLabel).map((s) => ({ label: statusLabel[s], value: s }))}
        />
        <Button type="primary" onClick={() => fetchRoles()}>查询</Button>
        <Button onClick={() => {
          setKeyword('');
          setStatusFilter(undefined);
          fetchRoles({ keyword: '', status: undefined });
        }}>
          重置
        </Button>
      </Space>

      <Table columns={columns} dataSource={roles} rowKey="id" loading={loading} />

      <Modal
        title="创建角色"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); }}
        onOk={() => createForm.submit()}
      >
        <Form form={createForm} onFinish={handleCreate} layout="vertical">
          <Form.Item name="code" label="编码" rules={[{ required: true }]}>
            <Input placeholder="如 ops、auditor" />
          </Form.Item>
          <Form.Item name="name" label="角色名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="sort_order" label="排序（越小越靠前）" initialValue={0}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑角色"
        open={editOpen}
        onCancel={() => { setEditOpen(false); editForm.resetFields(); }}
        onOk={() => editForm.submit()}
      >
        <Form form={editForm} onFinish={handleEdit} layout="vertical">
          <Form.Item name="code" label="编码">
            <Input disabled />
          </Form.Item>
          <Form.Item name="name" label="角色名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea />
          </Form.Item>
          <Form.Item name="sort_order" label="排序（越小越靠前）" rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="管理操作权限"
        open={opsModalOpen}
        onCancel={() => setOpsModalOpen(false)}
        footer={null}
        width={760}
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            allowClear
            placeholder="按分类筛选"
            style={{ width: 200 }}
            value={opsCategory}
            onChange={(value) => {
              setOpsCategory(value);
              setOpsSelected([]);
            }}
            options={Array.from(new Set(allOps.map((op) => op.category)))
              .map((c) => ({ label: categoryLabels[c] || c, value: c }))}
          />
        </Space>
        <Transfer
          dataSource={visibleOps.map((op) => ({
            key: op.operation_code,
            title: op.display_name,
            description: op.operation_code,
            category: op.category,
          }))}
          targetKeys={roleOps.map((op) => op.operation_code)}
          onChange={handleOpsTransfer}
          selectedKeys={opsSelected}
          onSelectChange={(source, target) =>
            setOpsSelected([...source, ...target].map(String))}
          disabled={isSuperAdminRole || !hasOperation('role:edit')}
          titles={['未分配', '已分配']}
          render={(item) => (
            opsCategory
              ? item.title
              : `${categoryLabels[item.category] || item.category} / ${item.title}`
          )}
          showSearch
          filterOption={(input, item) =>
            `${item.title} ${item.description}`.toLowerCase().includes(input.toLowerCase())}
          pagination={{ pageSize: 10 }}
          listStyle={{ width: 330, height: 360 }}
          footer={(_, info) => {
            const isLeft = (info?.direction ?? 'left') === 'left';
            const paneKeys = (isLeft
              ? visibleOps.filter((op) => !assignedOpCodes.has(op.operation_code))
              : roleOps
            ).map((op) => op.operation_code);
            if (isSuperAdminRole || !hasOperation('role:edit')) return null;
            return (
              <Space size="small">
                <Button size="small" type="link" onClick={() => applySelection(setOpsSelected, paneKeys, 'select')}>
                  全选
                </Button>
                <Button size="small" type="link" onClick={() => applySelection(setOpsSelected, paneKeys, 'invert')}>
                  反选
                </Button>
                <Button size="small" type="link" onClick={() => applySelection(setOpsSelected, paneKeys, 'deselect')}>
                  清空
                </Button>
              </Space>
            );
          }}
        />
      </Modal>

      <Modal
        title="分配账号"
        open={accountsOpen}
        onCancel={() => setAccountsOpen(false)}
        footer={null}
        width={760}
      >
        <Transfer
          dataSource={visibleAccounts.map((item) => ({
            key: item.id,
            title: `${item.account}（${item.real_name}）`,
          }))}
          targetKeys={roleAccounts.map((item) => item.id)}
          onChange={handleAccountsTransfer}
          selectedKeys={accountsSelected}
          onSelectChange={(source, target) =>
            setAccountsSelected([...source, ...target].map(String))}
          disabled={!hasOperation('role:assign')}
          titles={['未分配', '已分配']}
          render={(item) => item.title}
          showSearch
          filterOption={(input, item) => item.title.toLowerCase().includes(input.toLowerCase())}
          pagination={{ pageSize: 10 }}
          listStyle={{ width: 330, height: 360 }}
          footer={(_, info) => {
            const isLeft = (info?.direction ?? 'left') === 'left';
            const paneKeys = (isLeft
              ? visibleAccounts.filter((item) => !assignedAccountIds.has(item.id))
              : roleAccounts
            ).map((item) => item.id);
            if (!hasOperation('role:assign')) return null;
            return (
              <Space size="small">
                <Button size="small" type="link" onClick={() => applySelection(setAccountsSelected, paneKeys, 'select')}>
                  全选
                </Button>
                <Button size="small" type="link" onClick={() => applySelection(setAccountsSelected, paneKeys, 'invert')}>
                  反选
                </Button>
                <Button size="small" type="link" onClick={() => applySelection(setAccountsSelected, paneKeys, 'deselect')}>
                  清空
                </Button>
              </Space>
            );
          }}
        />
      </Modal>
    </>
  );
}
