import { useState, type ReactNode } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Button, theme, Dropdown, type MenuProps } from 'antd';
import {
  DashboardOutlined,
  UserOutlined,
  SafetyOutlined,
  ApiOutlined,
  LogoutOutlined,
  KeyOutlined,
} from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';

const { Header, Sider, Content } = Layout;

export default function AdminLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const { session, operationItems, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();

  // 菜单 → 后端操作码（前端仅控制展示，后端仍独立校验）
  const menuPermission: Array<{ key: string; icon: ReactNode; label: string; operation?: string }> = [
    { key: '/', icon: <DashboardOutlined />, label: '首页' },
    { key: '/accounts', icon: <UserOutlined />, label: '管理账号', operation: 'admin_account:view' },
    { key: '/roles', icon: <SafetyOutlined />, label: '后台角色', operation: 'role:view' },
    { key: '/caller-systems', icon: <ApiOutlined />, label: '调用系统', operation: 'caller_system:view' },
  ];

  const menuItems: MenuProps['items'] = menuPermission
    .filter((item) => !item.operation || operationItems.includes(item.operation))
    .map(({ key, icon, label }) => ({ key, icon, label }));

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
  };

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const selectedKey = '/' + location.pathname.split('/')[1];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        style={{ background: token.colorBgContainer }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: collapsed ? 16 : 20,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          {collapsed ? 'TH' : 'ToolHive'}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={handleMenuClick}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: token.colorBgContainer,
            padding: '0 24px',
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Dropdown
            menu={{
              items: [
                {
                  key: 'change-password',
                  icon: <KeyOutlined />,
                  label: '修改密码',
                  onClick: () => navigate('/change-password'),
                },
                { type: 'divider' },
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: '退出登录',
                  onClick: handleLogout,
                },
              ],
            }}
          >
            <Button type="text" icon={<UserOutlined />}>
              {session?.account || '管理员'}
            </Button>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
