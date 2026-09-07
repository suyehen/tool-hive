import { useEffect, useState } from 'react';
import {
  Button,
  Form,
  Input,
  message,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { listExposedTools, runMcpTestDebug } from '../../api/mcp';

const { Title, Paragraph } = Typography;

export default function TestDebugPage() {
  const [tools, setTools] = useState<Awaited<ReturnType<typeof listExposedTools>>>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string>();
  const [form] = Form.useForm();

  useEffect(() => {
    void listExposedTools()
      .then(setTools)
      .catch(() => setTools([]));
  }, []);

  const run = async () => {
    const values = await form.validateFields();
    setRunning(true);
    setResult(undefined);
    try {
      const parsed = values.arguments ? JSON.parse(values.arguments) : {};
      const outcome = await runMcpTestDebug(values.tool_code, parsed);
      setResult(JSON.stringify(outcome, null, 2));
      if (!outcome.ok) {
        message.warning('调试会话未完全成功');
      }
    } catch {
      message.error('运行调试失败：请检查参数 JSON');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <Title level={4}>MCP 测试调试</Title>
      <Paragraph type="secondary">
        以专用内置测试客户端对实际 MCP 端点发起 initialize → tools/list → tools/call，
        展示协议层摘要、结果与 trace_id。高风险/需确认工具将按当前策略拒绝执行。
      </Paragraph>
      <Form form={form} layout="vertical" style={{ maxWidth: 720 }}>
        <Form.Item
          name="tool_code"
          label="工具"
          rules={[{ required: true, message: '请选择工具' }]}
        >
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="选择 MCP 可发现工具"
            options={tools.map((tool) => ({
              value: tool.full_code,
              label: `${tool.full_code}（${tool.name}）`,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="arguments"
          label="参数（JSON）"
          initialValue="{}"
          rules={[{ required: true, message: '请输入参数 JSON' }]}
        >
          <Input.TextArea rows={6} placeholder='{"a":1,"b":2}' />
        </Form.Item>
        <Space>
          <Button type="primary" loading={running} onClick={run}>
            运行调试
          </Button>
          {result && <Tag>{running ? '运行中' : '运行完成'}</Tag>}
        </Space>
      </Form>
      {result && (
        <pre
          style={{
            marginTop: 16,
            background: '#f5f5f5',
            padding: 12,
            borderRadius: 6,
            maxHeight: 360,
            overflow: 'auto',
          }}
        >
          {result}
        </pre>
      )}
    </div>
  );
}
