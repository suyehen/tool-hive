import { useEffect, useState } from 'react';
import { Button, Table, Tag, Typography, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { listExposedTools } from '../../api/mcp';

const { Title } = Typography;

const riskLabel: Record<string, string> = { low: '低', medium: '中', high: '高' };

export default function ExposedToolsPage() {
  const [items, setItems] = useState<Awaited<ReturnType<typeof listExposedTools>>>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setItems(await listExposedTools());
    } catch {
      message.error('加载 MCP 暴露工具失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div>
      <Title level={4}>暴露工具（只读）</Title>
      <Typography.Paragraph type="secondary">
        当前从 MCP 客户端 tools/list 可见的工具（已启用 + mcp_enabled + 已发布默认版本）。
        工具定义与开关请在共享工具目录维护。
      </Typography.Paragraph>
      <Button
        style={{ marginBottom: 16 }}
        icon={<ReloadOutlined />}
        onClick={load}
      >
        刷新
      </Button>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={false}
        columns={[
          { title: '完整标识', dataIndex: 'full_code', width: 240 },
          { title: '名称', dataIndex: 'name', width: 160 },
          {
            title: '风险',
            dataIndex: 'risk_level',
            width: 80,
            render: (v: string) => riskLabel[v] || v,
          },
          {
            title: '默认版本',
            dataIndex: 'version',
            width: 100,
          },
          {
            title: 'MCP 入口',
            dataIndex: 'mcp_enabled',
            width: 100,
            render: (v: boolean) =>
              v ? <Tag color="green">开启</Tag> : <Tag color="red">关闭</Tag>,
          },
          { title: '工具状态', dataIndex: 'status', width: 100 },
        ]}
      />
    </div>
  );
}
