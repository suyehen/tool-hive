import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Card, Typography, Input, Button, message, Space, Alert } from 'antd';
import { QRCodeSVG } from 'qrcode.react';
import { bindMfa } from '../api/auth';
import { useAuth } from '../contexts/AuthContext';

const { Title, Text, Paragraph } = Typography;

export default function MfaSetupPage() {
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const { refreshSession } = useAuth();

  const state = location.state as { secret?: string; totpUri?: string } | null;
  const secret = state?.secret;
  const totpUri = state?.totpUri;

  if (!secret || !totpUri) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center', background: '#f5f5f5' }}>
        <Card style={{ width: 450 }}>
          <Title level={4} style={{ textAlign: 'center' }}>无效的 MFA 设置链接</Title>
          <Paragraph style={{ textAlign: 'center' }}>请从登录流程重新开始。</Paragraph>
          <Button block onClick={() => navigate('/login')}>返回登录</Button>
        </Card>
      </div>
    );
  }

  const handleBind = async () => {
    if (!code || code.length !== 6) {
      message.warning('请输入6位验证码');
      return;
    }
    setLoading(true);
    try {
      const result = await bindMfa(secret, code);
      setRecoveryCodes(result.recovery_codes);
      message.success('MFA 绑定成功');
      await refreshSession();
    } catch {
      message.error('验证码不正确，请重试');
    } finally {
      setLoading(false);
    }
  };

  if (recoveryCodes) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center', background: '#f5f5f5' }}>
        <Card style={{ width: 500 }}>
          <Alert
            type="warning"
            message="请立即保存以下恢复码！"
            description="这些恢复码只会展示一次，请复制并保存在安全的地方。丢失后需联系超级管理员重置。"
            style={{ marginBottom: 16 }}
          />
          <div
            style={{
              background: '#f6f8fa',
              padding: 16,
              borderRadius: 8,
              fontFamily: 'monospace',
              fontSize: 14,
              lineHeight: 2,
              marginBottom: 16,
            }}
          >
            {recoveryCodes.map((rc, i) => (
              <div key={i}>{i + 1}. {rc}</div>
            ))}
          </div>
          <Button
            type="primary"
            block
            size="large"
            onClick={() => {
              navigate('/', { replace: true });
            }}
          >
            我已保存，进入管理后台
          </Button>
        </Card>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center', background: '#f5f5f5' }}>
      <Card style={{ width: 450, textAlign: 'center' }}>
        <Title level={4}>绑定 MFA</Title>
        <Paragraph type="secondary">
          使用验证器应用（如 Google Authenticator、Authy）扫描下方二维码
        </Paragraph>
        <div style={{ padding: 16, background: '#fff', display: 'inline-block', borderRadius: 8, marginBottom: 16 }}>
          <QRCodeSVG value={totpUri} size={200} />
        </div>
        <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 24 }}>
          或手动输入密钥：<Text code>{secret}</Text>
        </Paragraph>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="输入6位验证码"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            maxLength={6}
            size="large"
          />
          <Button type="primary" loading={loading} onClick={handleBind} size="large">
            绑定
          </Button>
        </Space.Compact>
      </Card>
    </div>
  );
}
