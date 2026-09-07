import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  message,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { getServerConfig, updateServerConfig } from '../../api/mcp';

const { Title, Paragraph } = Typography;

export default function ServerConfigPage() {
  const [config, setConfig] = useState<Awaited<ReturnType<typeof getServerConfig>> | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    try {
      const data = await getServerConfig();
      setConfig(data);
      form.setFieldsValue({
        server_name: data.server_name,
        description: data.description || '',
        enabled: data.enabled,
        endpoint_path: data.endpoint_path,
        allowed_hosts: (data.allowed_hosts || []).join('\n'),
      });
    } catch {
      message.error('加载 MCP 接入配置失败');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    if (!config) return;
    const values = await form.validateFields();
    setSaving(true);
    try {
      const updated = await updateServerConfig({
        server_name: values.server_name,
        description: values.description || null,
        enabled: values.enabled,
        endpoint_path: values.endpoint_path,
        allowed_hosts: (values.allowed_hosts || '')
          .split('\n')
          .map((line: string) => line.trim())
          .filter(Boolean),
        protocol_versions: config.protocol_versions,
        row_version: config.row_version,
      });
      setConfig(updated);
      message.success('接入配置已保存');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <Title level={4}>MCP 接入配置</Title>
      {config && (
        <Card
          style={{ marginBottom: 16 }}
          title="运行摘要"
          size="small"
        >
          <Space size="large">
            <Tag color={config.enabled ? 'green' : 'red'}>
              {config.enabled ? '已启用' : '已停用'}
            </Tag>
            <span>端点：{config.endpoint_path}</span>
            <span>Server：{config.server_name}</span>
          </Space>
        </Card>
      )}
      <Card size="small">
        <Form form={form} layout="vertical">
          <Form.Item
            name="server_name"
            label="Server 名称"
            rules={[{ required: true, message: '必填' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Space size="large">
            <Form.Item name="enabled" label="全局启用" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item
              name="endpoint_path"
              label="端点路径"
              rules={[{ required: true, message: '必填' }]}
            >
              <Input style={{ width: 220 }} />
            </Form.Item>
          </Space>
          <Form.Item
            name="allowed_hosts"
            label="Host 白名单（每行一个）"
            rules={[{ required: true, message: '必填' }]}
          >
            <Input.TextArea rows={4} placeholder={'127.0.0.1\nlocalhost'} />
          </Form.Item>
        </Form>
        <Space>
          <Button type="primary" loading={saving} onClick={save}>
            保存
          </Button>
          <Button icon={<ReloadOutlined />} onClick={load}>
            刷新
          </Button>
        </Space>
      </Card>
      {config && (
        <Paragraph type="secondary" style={{ marginTop: 16 }}>
          <Descriptions
            column={1}
            size="small"
            bordered
            items={[
              { key: 'row', label: '版本号', children: config.row_version },
              { key: 'updated', label: '更新时间', children: config.updated_at || '-' },
            ]}
          />
        </Paragraph>
      )}
    </div>
  );
}
