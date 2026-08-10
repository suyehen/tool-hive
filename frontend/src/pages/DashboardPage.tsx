import { Card, Col, Row, Statistic, Typography } from 'antd';
import { SafetyOutlined, UserOutlined, ApiOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';

const { Title } = Typography;

export default function DashboardPage() {
  const { session } = useAuth();

  return (
    <>
      <Title level={4} style={{ marginBottom: 24 }}>
        欢迎，{session?.username}
      </Title>
      <Row gutter={24}>
        <Col span={8}>
          <Card>
            <Statistic title="登录来源 IP" value={session?.source_ip || '-'} prefix={<UserOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="角色" value={session?.is_super_admin ? '超级管理员' : '普通管理员'} prefix={<SafetyOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="当前会话" value="已认证" prefix={<ApiOutlined />} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
      </Row>
    </>
  );
}
