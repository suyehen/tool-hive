import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Form, Input, Button, Card, message, Space, Typography } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { loginPassword, verifyMfa, loginRecovery, type LoginStep1Result, type MfaSetupRequiredResponse } from '../api/auth';
import { useAuth } from '../contexts/AuthContext';

const { Title } = Typography;

export default function LoginPage() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<'password' | 'mfa' | 'recovery'>('password');
  const [mfaSetupUri, setMfaSetupUri] = useState<string | null>(null);
  const [mfaSecret, setMfaSecret] = useState<string | null>(null);
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/';

  const handlePassword = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const result: LoginStep1Result = await loginPassword(values.username, values.password);

      if ('session_id' in result) {
        // 无 MFA，直接登录成功
        login(result.csrf_token, {
          account_id: '',
          username: result.username,
          is_super_admin: result.is_super_admin,
          source_ip: '',
          created_at: '',
        });
        message.success('登录成功');
        navigate(from, { replace: true });
      } else if ('require_mfa' in result) {
        setStep('mfa');
      } else if ('require_mfa_setup' in result) {
        // 需要绑定 MFA → 跳转 MFA 设置页
        const setup = result as MfaSetupRequiredResponse;
        navigate('/mfa-setup', { state: { secret: setup.secret, totpUri: setup.totp_uri } });
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (msg === 'captcha_required') {
        message.warning('需要验证码，请稍后重试');
      } else {
        message.error(msg || '登录失败');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleMfa = async (values: { code: string }) => {
    setLoading(true);
    try {
      const result = await verifyMfa(values.code);
      login(result.csrf_token, {
        account_id: '',
        username: result.username,
        is_super_admin: result.is_super_admin,
        source_ip: '',
        created_at: '',
      });
      message.success('登录成功');
      navigate(from, { replace: true });
    } catch {
      message.error('MFA 验证失败');
    } finally {
      setLoading(false);
    }
  };

  const handleRecovery = async (values: { username: string; password: string; recoveryCode: string }) => {
    setLoading(true);
    try {
      const result = await loginRecovery(values.username, values.password, values.recoveryCode);
      login(result.csrf_token, {
        account_id: '',
        username: result.username,
        is_super_admin: result.is_super_admin,
        source_ip: '',
        created_at: '',
      });
      message.success('登录成功');
      navigate(from, { replace: true });
    } catch {
      message.error('恢复码无效');
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

        {step === 'password' && (
          <>
            <Title level={5} style={{ textAlign: 'center', marginBottom: 24 }}>
              账号登录
            </Title>
            <Form form={form} onFinish={handlePassword} layout="vertical">
              <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                <Input prefix={<UserOutlined />} placeholder="用户名" size="large" />
              </Form.Item>
              <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" loading={loading} block size="large">
                  登录
                </Button>
              </Form.Item>
              <Space style={{ width: '100%', justifyContent: 'center' }}>
                <Button type="link" onClick={() => setStep('recovery')}>
                  使用恢复码登录
                </Button>
              </Space>
            </Form>
          </>
        )}

        {step === 'mfa' && (
          <>
            <Title level={5} style={{ textAlign: 'center', marginBottom: 24 }}>
              MFA 验证
            </Title>
            <Form onFinish={handleMfa} layout="vertical">
              <Form.Item name="code" rules={[{ required: true, message: '请输入6位验证码' }]}>
                <Input placeholder="6位验证码" size="large" maxLength={6} autoFocus />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" loading={loading} block size="large">
                  验证
                </Button>
              </Form.Item>
              <Space style={{ width: '100%', justifyContent: 'center' }}>
                <Button type="link" onClick={() => setStep('password')}>
                  返回密码登录
                </Button>
                <Button type="link" onClick={() => setStep('recovery')}>
                  使用恢复码
                </Button>
              </Space>
            </Form>
          </>
        )}

        {step === 'recovery' && (
          <>
            <Title level={5} style={{ textAlign: 'center', marginBottom: 24 }}>
              恢复码登录
            </Title>
            <Form onFinish={handleRecovery} layout="vertical">
              <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                <Input prefix={<UserOutlined />} placeholder="用户名" size="large" />
              </Form.Item>
              <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                <Input.Password prefix={<LockOutlined />} placeholder="密码" size="large" />
              </Form.Item>
              <Form.Item name="recoveryCode" rules={[{ required: true, message: '请输入恢复码' }]}>
                <Input placeholder="恢复码" size="large" />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" loading={loading} block size="large">
                  使用恢复码登录
                </Button>
              </Form.Item>
              <Space style={{ width: '100%', justifyContent: 'center' }}>
                <Button type="link" onClick={() => setStep('password')}>
                  返回密码登录
                </Button>
              </Space>
            </Form>
          </>
        )}
      </Card>
    </div>
  );
}
