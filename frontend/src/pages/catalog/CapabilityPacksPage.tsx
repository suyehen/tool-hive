import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Form, Input, message, Space, Tag, Typography, Popconfirm, Select, Tabs,
} from 'antd';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listCapabilityPacks, createCapabilityPack, updateCapabilityPack,
  setCapabilityPackStatus, listPackTools, replacePackTools,
  listPackSystems, replacePackSystems,
  listTools,
  type CapabilityPackItem, type ToolItem, type CallerSystemLite,
} from '../../api/catalog';
import { listCallerSystems } from '../../api/caller-systems';
import { useAuth } from '../../contexts/AuthContext';

const { Title } = Typography;

const statusLabel: Record<string, string> = {
  enabled: '已启用', disabled: '已停用', archived: '已归档',
};
const statusColor: Record<string, string> = {
  enabled: 'green', disabled: 'orange', archived: 'default',
};

export default function CapabilityPacksPage() {
  const { hasOperation } = useAuth();
  const [items, setItems] = useState<CapabilityPackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editItem, setEditItem] = useState<CapabilityPackItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [packTools, setPackTools] = useState<ToolItem[]>([]);
  const [packSystems, setPackSystems] = useState<CallerSystemLite[]>([]);
  const [toolOptions, setToolOptions] = useState<ToolItem[]>([]);
  const [systemOptions, setSystemOptions] = useState<CallerSystemLite[]>([]);
  const [toolSelectOpen, setToolSelectOpen] = useState(false);
  const [systemSelectOpen, setSystemSelectOpen] = useState(false);
  const [selectedToolIds, setSelectedToolIds] = useState<string[]>([]);
  const [selectedSystemIds, setSelectedSystemIds] = useState<string[]>([]);
  const [form] = Form.useForm();

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { items: list, total: t } = await listCapabilityPacks(0, 100);
      setItems(list);
      setTotal(t);
    } catch {
      message.error('加载能力包失败');
    } finally {
      setLoading(false);
    }
  };

  const loadOptions = async () => {
    try {
      const [{ items: tools }, systemsResp] = await Promise.all([
        listTools(0, 200),
        listCallerSystems(0, 200),
      ]);
      setToolOptions(tools);
      setSystemOptions(systemsResp.items);
    } catch {
      message.error('加载可选数据失败');
    }
  };

  useEffect(() => { fetchItems(); loadOptions(); }, []);

  const openDetail = async (pack: CapabilityPackItem) => {
    setDetailId(pack.id);
    setDetailOpen(true);
    try {
      setPackTools(await listPackTools(pack.id));
      setPackSystems(await listPackSystems(pack.id));
    } catch {
      setPackTools([]);
      setPackSystems([]);
    }
  };

  const handleCreate = async () => {
    const values = await form.validateFields();
    try {
      await createCapabilityPack(values);
      message.success('能力包已创建');
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
      await updateCapabilityPack(editItem.id, {
        name: values.name,
        description: values.description,
        row_version: editItem.row_version,
      });
      message.success('能力包已更新');
      setEditOpen(false);
      fetchItems();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '更新失败');
    }
  };

  const handleStatus = async (pack: CapabilityPackItem, action: 'enable' | 'disable' | 'archive') => {
    try {
      await setCapabilityPackStatus(pack.id, action);
      message.success('操作成功');
      fetchItems();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '操作失败');
    }
  };

  const savePackTools = async () => {
    if (!detailId) return;
    try {
      setPackTools(await replacePackTools(detailId, selectedToolIds));
      message.success('工具关联已保存');
      setToolSelectOpen(false);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '保存失败');
    }
  };

  const savePackSystems = async () => {
    if (!detailId) return;
    try {
      setPackSystems(await replacePackSystems(detailId, selectedSystemIds));
      message.success('调用系统授权已保存');
      setSystemSelectOpen(false);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '保存失败');
    }
  };

  const columns: ColumnsType<CapabilityPackItem> = [
    { title: '编码', dataIndex: 'pack_code', width: 160 },
    { title: '名称', dataIndex: 'name', width: 200 },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={statusColor[v]}>{statusLabel[v] || v}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 320,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => openDetail(record)}>详情</Button>
          {hasOperation('capability:edit') && (
            <Button
              size="small"
              onClick={() => {
                setEditItem(record);
                form.setFieldsValue({
                  name: record.name,
                  description: record.description || undefined,
                });
                setEditOpen(true);
              }}
            >
              编辑
            </Button>
          )}
          {hasOperation('capability:manage') && record.status === 'enabled' && (
            <Popconfirm title="确认停用？" onConfirm={() => handleStatus(record, 'disable')}>
              <Button size="small">停用</Button>
            </Popconfirm>
          )}
          {hasOperation('capability:manage') && record.status === 'disabled' && (
            <Button size="small" onClick={() => handleStatus(record, 'enable')}>启用</Button>
          )}
          {hasOperation('capability:manage') && record.status !== 'archived' && (
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
      <Title level={4}>能力包管理</Title>
      <Space style={{ marginBottom: 16 }}>
        {hasOperation('capability:create') && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              setCreateOpen(true);
            }}
          >
            新建能力包
          </Button>
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
      <Modal title="新建能力包" open={createOpen} onOk={handleCreate} onCancel={() => setCreateOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item name="pack_code" label="编码" rules={[{ required: true, message: '请输入编码' }]}>
            <Input placeholder="如 basic-math" />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal title="编辑能力包" open={editOpen} onOk={handleUpdate} onCancel={() => setEditOpen(false)} destroyOnClose>
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item label="编码">
            <Input value={editItem?.pack_code} disabled />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="能力包详情"
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={760}
      >
        <Tabs
          items={[
            {
              key: 'tools',
              label: `工具（${packTools.length}）`,
              children: (
                <>
                  {hasOperation('capability:edit') && (
                    <Button
                      size="small"
                      style={{ marginBottom: 12 }}
                      onClick={() => {
                        setSelectedToolIds(packTools.map((t) => t.id));
                        setToolSelectOpen(true);
                      }}
                    >
                      编辑工具关联
                    </Button>
                  )}
                  <Table
                    rowKey="id"
                    size="small"
                    pagination={false}
                    dataSource={packTools}
                    columns={[
                      { title: '完整标识', dataIndex: 'full_code' },
                      { title: '名称', dataIndex: 'name' },
                      { title: '状态', dataIndex: 'status' },
                    ]}
                  />
                </>
              ),
            },
            {
              key: 'systems',
              label: `调用系统授权（${packSystems.length}）`,
              children: (
                <>
                  {hasOperation('capability:edit') && (
                    <Button
                      size="small"
                      style={{ marginBottom: 12 }}
                      onClick={() => {
                        setSelectedSystemIds(packSystems.map((s) => s.system_id));
                        setSystemSelectOpen(true);
                      }}
                    >
                      编辑调用系统授权
                    </Button>
                  )}
                  <Table
                    rowKey="system_id"
                    size="small"
                    pagination={false}
                    dataSource={packSystems}
                    columns={[
                      { title: 'system_id', dataIndex: 'system_id' },
                      { title: '名称', dataIndex: 'name' },
                      { title: '环境', dataIndex: 'environment' },
                    ]}
                  />
                </>
              ),
            },
          ]}
        />
      </Modal>
      <Modal
        title="编辑工具关联"
        open={toolSelectOpen}
        onOk={savePackTools}
        onCancel={() => setToolSelectOpen(false)}
      >
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          placeholder="选择工具"
          value={selectedToolIds}
          onChange={setSelectedToolIds}
          options={toolOptions.map((t) => ({ value: t.id, label: `${t.full_code}（${t.name}）` }))}
          optionFilterProp="label"
        />
      </Modal>
      <Modal
        title="编辑调用系统授权"
        open={systemSelectOpen}
        onOk={savePackSystems}
        onCancel={() => setSystemSelectOpen(false)}
      >
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          placeholder="选择调用系统"
          value={selectedSystemIds}
          onChange={setSelectedSystemIds}
          options={systemOptions.map((s) => ({
            value: s.system_id,
            label: `${s.system_id}（${s.name} / ${s.environment}）`,
          }))}
          optionFilterProp="label"
        />
      </Modal>
    </div>
  );
}
