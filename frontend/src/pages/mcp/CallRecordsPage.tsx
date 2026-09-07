import { useEffect, useState } from 'react';
import {
  Button,
  Descriptions,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import {
  getCallRecordDetail,
  listCallRecords,
  listMcpClients,
  type TraceEvent,
} from '../../api/mcp';

const { Title } = Typography;

export default function CallRecordsPage() {
  const [items, setItems] = useState<TraceEvent[]>([]);
  const [clients, setClients] = useState<Array<Record<string, unknown>>>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>();
  const [clientId, setClientId] = useState<string>();
  const [detail, setDetail] = useState<{ trace_id: string; events: TraceEvent[] } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await listCallRecords(0, 100, { status, client_id: clientId });
      setItems(data.items);
      setTotal(data.total);
    } catch {
      message.error('加载调用记录失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    void listMcpClients(0, 200)
      .then((data) => setClients(data.items as unknown as Array<Record<string, unknown>>))
      .catch(() => setClients([]));
  }, []);

  const openDetail = async (traceId: string) => {
    setDetailLoading(true);
    try {
      setDetail(await getCallRecordDetail(traceId));
    } catch {
      message.error('加载事件链失败');
    } finally {
      setDetailLoading(false);
    }
  };

  return (
    <div>
      <Title level={4}>MCP 调用记录</Title>
      <Space style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 120 }}
          value={status}
          onChange={setStatus}
          options={[
            { value: 'success', label: '成功' },
            { value: 'failure', label: '失败' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="客户端"
          style={{ width: 220 }}
          value={clientId}
          onChange={setClientId}
          options={clients.map((client) => ({
            value: String(client.id),
            label: `${String(client.name)}（${String(client.client_code)}）`,
          }))}
        />
        <Button type="primary" onClick={load}>
          查询
        </Button>
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={{
          current: 1,
          pageSize: 100,
          total,
          showTotal: (t) => `共 ${t} 条`,
        }}
        columns={[
          { title: 'Trace ID', dataIndex: 'trace_id', width: 200 },
          { title: '动作', dataIndex: 'action', width: 170 },
          {
            title: '结果',
            dataIndex: 'status',
            width: 90,
            render: (v: string) => (
              <Tag color={v === 'success' ? 'green' : 'red'}>{v}</Tag>
            ),
          },
          { title: '客户端', dataIndex: 'mcp_client_id', width: 190 },
          { title: '时间', dataIndex: 'occurred_at', width: 200 },
          {
            title: '操作',
            key: 'action',
            render: (_, record) => (
              <Button
                size="small"
                onClick={() => openDetail(String(record.trace_id))}
              >
                详情
              </Button>
            ),
          },
        ]}
      />
      <Modal
        title={`Trace 详情 ${detail?.trace_id ?? ''}`}
        open={detail !== null}
        footer={null}
        width={900}
        onCancel={() => setDetail(null)}
      >
        {detail && (
          <Table
            size="small"
            loading={detailLoading}
            rowKey="id"
            dataSource={detail.events}
            pagination={false}
            expandable={{
              expandedRowRender: (record) => (
                <Descriptions
                  column={1}
                  size="small"
                  bordered
                  items={[
                    {
                      key: 'summary',
                      label: '摘要',
                      children: JSON.stringify(record.summary || {}, null, 2),
                    },
                    {
                      key: 'error',
                      label: '错误码',
                      children: String(record.error_code || '-'),
                    },
                  ]}
                />
              ),
            }}
            columns={[
              { title: '动作', dataIndex: 'action' },
              { title: '结果', dataIndex: 'status', width: 90 },
              { title: '来源 IP', dataIndex: 'source_ip', width: 130 },
              { title: '时间', dataIndex: 'occurred_at', width: 200 },
            ]}
          />
        )}
      </Modal>
    </div>
  );
}
