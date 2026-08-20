import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Form, Input, Button, message, Typography } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import { changePassword } from '../api/auth';
import { useAuth } from '../contexts/AuthContext';

const { Title } = Typography;

export default function ChangePasswordPage() {
  const [loading, setLoading] = useState(false);
  const { refreshSession } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (values: { old_password: string; new_password: string; confirm: string }) => {
    if (values.new_password !== values.confirm) {
      message.error('两次输入的新密码不一致');
      return;
    }
    setLoading(true);
    try {
      await changePassword(values.old_password, values.new_password);
      message.success('密码修改成功');
      // 改密后后端轮转会话，重新拉取会话与 CSRF
      await refreshSession();
      navigate('/');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '修改失败';
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 480, margin: '48px auto' }}>
      <Card>
        <Title level={4} style={{ textAlign: 'center', marginBottom: 24 }}>
          修改密码
        </Title>
        <Form onFinish={handleSubmit} layout="vertical">
          <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
            <Input.Password prefix={<LockOutlined />} size="large" />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: '请输入新密码' }]}>
            <Input.Password prefix={<LockOutlined />} size="large" />
          </Form.Item>
          <Form.Item name="confirm" label="确认新密码" rules={[{ required: true, message: '请再次输入新密码' }]}>
            <Input.Password prefix={<LockOutlined />} size="large" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block size="large">
              确认修改
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
