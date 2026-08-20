import { Card, Col, Row, Statistic, Typography } from 'antd';
import { SafetyOutlined, UserOutlined, ApiOutlined } from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';

const { Title } = Typography;

export default function DashboardPage() {
  const { session, me, operationItems } = useAuth();

  const statusText =
    me?.status === 'enabled' ? '正常' : me?.status === 'disabled' ? '已禁用' : me?.status || '-';

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
            <Statistic title="账号状态" value={statusText} prefix={<SafetyOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="已授权操作项" value={operationItems.length} prefix={<ApiOutlined />} />
          </Card>
        </Col>
      </Row>
    </>
  );
}
