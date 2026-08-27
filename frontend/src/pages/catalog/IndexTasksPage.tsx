import { useEffect, useState } from 'react';
import {
  Table, Button, message, Space, Tag, Typography, Popconfirm,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listIndexTasks, retryIndexTask, type IndexTaskItem,
} from '../../api/catalog';
import { useAuth } from '../../contexts/AuthContext';

const { Title } = Typography;

const statusLabel: Record<string, string> = {
  PENDING: '待处理', PROCESSING: '处理中', RETRY: '重试中',
  SUCCEEDED: '成功', DEAD: '失败',
};
const statusColor: Record<string, string> = {
  PENDING: 'default', PROCESSING: 'blue', RETRY: 'orange',
  SUCCEEDED: 'green', DEAD: 'red',
};

export default function IndexTasksPage() {
  const { hasOperation } = useAuth();
  const [items, setItems] = useState<IndexTaskItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { items: list, total: t } = await listIndexTasks(0, 100);
      setItems(list);
      setTotal(t);
    } catch {
      message.error('加载索引任务失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchItems(); }, []);

  const handleRetry = async (deliveryId: string) => {
    try {
      await retryIndexTask(deliveryId);
      message.success('已重新投递');
      fetchItems();
    } catch {
      message.error('重试失败');
    }
  };

  const columns: ColumnsType<IndexTaskItem> = [
    { title: '事件类型', dataIndex: 'event_type', width: 220 },
    { title: '对象', dataIndex: 'object_id', width: 200 },
    {
      title: '状态', dataIndex: 'status', width: 100,
      render: (v: string) => <Tag color={statusColor[v]}>{statusLabel[v] || v}</Tag>,
    },
    { title: '尝试次数', dataIndex: 'attempts', width: 90 },
    { title: '错误信息', dataIndex: 'last_error', ellipsis: true },
    { title: '创建时间', dataIndex: 'create_time', width: 180 },
    {
      title: '操作', key: 'actions', width: 100,
      render: (_, record) =>
        hasOperation('system_task:retry') && (record.status === 'DEAD' || record.status === 'RETRY') ? (
          <Popconfirm title="确认重新投递？" onConfirm={() => handleRetry(record.delivery_id)}>
            <Button size="small">重试</Button>
          </Popconfirm>
        ) : null,
    },
  ];

  return (
    <div>
      <Title level={4}>Catalog 索引任务</Title>
      <Button icon={<ReloadOutlined />} style={{ marginBottom: 16 }} onClick={fetchItems}>刷新</Button>
      <Table
        rowKey="delivery_id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{ total, pageSize: 100, showTotal: (t) => `共 ${t} 条` }}
      />
    </div>
  );
}
