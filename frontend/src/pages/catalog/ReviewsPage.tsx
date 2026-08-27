import { useEffect, useState } from 'react';
import {
  Table, Button, Modal, Input, message, Space, Typography,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listPendingReviews, approveReview, rejectReview,
  type PendingReviewItem,
} from '../../api/catalog';

const { Title, Paragraph } = Typography;

export default function ReviewsPage() {
  const [items, setItems] = useState<PendingReviewItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState<'approve' | 'reject' | null>(null);
  const [target, setTarget] = useState<PendingReviewItem | null>(null);
  const [comment, setComment] = useState('');

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { items: list, total: t } = await listPendingReviews(0, 100);
      setItems(list);
      setTotal(t);
    } catch {
      message.error('加载待审核列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchItems(); }, []);

  const handleReview = async () => {
    if (!target || !action) return;
    try {
      if (action === 'approve') {
        await approveReview(target.version_id, comment);
        message.success('已通过审核');
      } else {
        await rejectReview(target.version_id, comment);
        message.success('已驳回');
      }
      setAction(null);
      setTarget(null);
      setComment('');
      fetchItems();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err.response?.data?.detail || '操作失败');
    }
  };

  const columns: ColumnsType<PendingReviewItem> = [
    { title: '工具', dataIndex: 'full_code', width: 200 },
    { title: '名称', dataIndex: 'tool_name', width: 160 },
    { title: '版本', dataIndex: 'version', width: 100 },
    { title: '版本说明', dataIndex: 'release_note', ellipsis: true },
    { title: '送审人', dataIndex: 'submitter_account_id', width: 120, render: (v: string | null) => v || '-' },
    { title: '送审时间', dataIndex: 'created_at', width: 180 },
    {
      title: '操作', key: 'actions', width: 180,
      render: (_, record) => (
        <Space>
          <Button
            type="primary"
            size="small"
            onClick={() => {
              setTarget(record);
              setAction('approve');
              setComment('');
            }}
          >
            通过
          </Button>
          <Button
            danger
            size="small"
            onClick={() => {
              setTarget(record);
              setAction('reject');
              setComment('');
            }}
          >
            驳回
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4}>工具审核</Title>
      <Button icon={<ReloadOutlined />} style={{ marginBottom: 16 }} onClick={fetchItems}>刷新</Button>
      <Table
        rowKey="version_id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{ total, pageSize: 100, showTotal: (t) => `共 ${t} 条` }}
      />
      <Modal
        title={action === 'approve' ? '审核通过' : '审核驳回'}
        open={action !== null}
        onOk={handleReview}
        onCancel={() => setAction(null)}
        destroyOnClose
      >
        <Paragraph>
          工具 {target?.full_code}，版本 {target?.version}
        </Paragraph>
        <Input.TextArea
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={action === 'reject' ? '驳回原因' : '审核意见（可选）'}
        />
      </Modal>
    </div>
  );
}
