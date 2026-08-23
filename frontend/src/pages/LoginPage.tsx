import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Form, Input, Button, Card, message, Typography } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import {
  loginPassword,
  getCaptchaChallenge,
  getSession,
  getMe,
  getOperationItems,
  type CaptchaChallenge,
} from '../api/auth';
import { useAuth } from '../contexts/AuthContext';

const { Title } = Typography;

// 登录相关输入不允许出现中文/全角字符（含中文标点），避免误输入
const CJK_INPUT_REGEX = /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF\u3000-\u303F]/;
const stripCJKChars = (value: string) => value.replace(new RegExp(CJK_INPUT_REGEX.source, 'g'), '');
const blockCJKInput = (event: FormEvent<HTMLInputElement>) => {
  const data = (event.nativeEvent as InputEvent).data;
  if (data && CJK_INPUT_REGEX.test(data)) {
    event.preventDefault();
  }
};

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

  const handleSubmit = async (values: { account: string; password: string; captchaCode: string }) => {
    if (!captcha) {
      message.warning('请先加载验证码');
      return;
    }
    setLoading(true);
    try {
      const result = await loginPassword(
        values.account,
        values.password,
        captcha.captcha_id,
        values.captchaCode,
      );
      // 登录成功后拉取真实会话、账号资料与实时操作项
      const [session, me, operationItems] = await Promise.all([
        getSession(),
        getMe(),
        getOperationItems(),
      ]);
      login(result.csrf_token, session, me, operationItems);
      message.success('登录成功');
      navigate(me.must_change_password ? '/change-password' : from, { replace: true });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      // 验证码为一次性消费，无论密码/验证码/其他错误，旧验证码均已失效，统一刷新
      loadCaptcha();
      message.error(msg || '登录失败');
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
          <Form.Item
            name="account"
            rules={[{ required: true, message: '请输入账号' }]}
            normalize={(value) => stripCJKChars(value ?? '')}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="账号"
              size="large"
              autoComplete="username"
              onBeforeInput={blockCJKInput}
            />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
            normalize={(value) => stripCJKChars(value ?? '')}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              size="large"
              autoComplete="current-password"
              onBeforeInput={blockCJKInput}
            />
          </Form.Item>
          <Form.Item
            name="captchaCode"
            rules={[{ required: true, message: '请输入验证码' }]}
            normalize={(value) => stripCJKChars(value ?? '')}
          >
            <div style={{ display: 'flex', gap: 8, width: '100%' }}>
              <Input
                placeholder="验证码"
                size="large"
                maxLength={8}
                autoComplete="off"
                onBeforeInput={blockCJKInput}
              />
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
