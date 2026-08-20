import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Form, Input, Button, Card, message, Typography } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import {
  loginPassword,
  getCaptchaChallenge,
  type CaptchaChallenge,
} from '../api/auth';
import { useAuth } from '../contexts/AuthContext';

const { Title } = Typography;

export default function LoginPage() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [captcha, setCaptcha] = useState<CaptchaChallenge | null>(null);
  const [captchaLoading, setCaptchaLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/';

  const loadCaptcha = useCallback(async () => {
    setCaptchaLoading(true);
    try {
      const challenge = await getCaptchaChallenge();
      setCaptcha(challenge);
      form.setFieldValue('captchaCode', undefined);
    } catch {
      message.error('验证码加载失败，请稍后重试');
    } finally {
      setCaptchaLoading(false);
    }
  }, [form]);

  useEffect(() => {
    loadCaptcha();
  }, [loadCaptcha]);

  const handleSubmit = async (values: { username: string; password: string; captchaCode: string }) => {
    if (!captcha) {
      message.warning('请先加载验证码');
      return;
    }
    setLoading(true);
    try {
      const result = await loginPassword(
        values.username,
        values.password,
        captcha.captcha_id,
        values.captchaCode,
      );
      login(result.csrf_token, {
        account_id: '',
        username: result.username,
        is_super_admin: result.is_super_admin,
        source_ip: '',
        created_at: '',
      });
      message.success('登录成功');
      navigate(from, { replace: true });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (msg && msg.includes('验证码')) {
        loadCaptcha();
        message.error(msg);
      } else {
        message.error(msg || '登录失败');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: '#f5f5f5',
      }}
    >
      <Card style={{ width: 400 }}>
        <Title level={3} style={{ textAlign: 'center', marginBottom: 32 }}>
          ToolHive 管理后台
        </Title>

        <Title level={5} style={{ textAlign: 'center', marginBottom: 24 }}>
          账号登录
        </Title>
        <Form form={form} onFinish={handleSubmit} layout="vertical">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" size="large" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
          </Form.Item>
          <Form.Item name="captchaCode" rules={[{ required: true, message: '请输入验证码' }]}>
            <div style={{ display: 'flex', gap: 8, width: '100%' }}>
              <Input placeholder="验证码" size="large" maxLength={8} />
              {captcha && (
                <img
                  src={captcha.image}
                  alt="验证码"
                  title="点击刷新验证码"
                  onClick={loadCaptcha}
                  style={{
                    height: 40,
                    width: 110,
                    objectFit: 'cover',
                    cursor: 'pointer',
                    border: '1px solid #d9d9d9',
                    borderRadius: 6,
                  }}
                />
              )}
              {!captcha && (
                <Button size="large" onClick={loadCaptcha} loading={captchaLoading}>
                  获取验证码
                </Button>
              )}
            </div>
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block size="large">
              登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
