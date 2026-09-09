import { useEffect, useState, type ReactNode } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Button, theme, Dropdown, type MenuProps } from 'antd';
import {
  DashboardOutlined,
  UserOutlined,
  SafetyOutlined,
  ApiOutlined,
  LogoutOutlined,
  KeyOutlined,
  AppstoreOutlined,
  ToolOutlined,
  AuditOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
} from '@ant-design/icons';
import { useAuth } from '../contexts/AuthContext';

const { Header, Sider, Content } = Layout;

type MenuEntry = {
  key: string;
  icon: ReactNode;
  label: string;
  operation?: string;
  children?: MenuEntry[];
};

function collectMenuLeafKeys(items: MenuEntry[]): string[] {
  return items.flatMap((item) =>
    item.children ? collectMenuLeafKeys(item.children) : [item.key],
  );
}

function findMenuParentKey(
  menuKey: string | undefined,
  items: MenuEntry[],
): string | undefined {
  if (!menuKey) {
    return undefined;
  }
  return items.find((item) =>
    item.children?.some((child) => child.key === menuKey),
  )?.key;
}

function resolveSelectedMenuKey(
  pathname: string,
  leafKeys: string[],
): string | undefined {
  // 首页路由为 /dashboard，菜单项 key 为 /
  if (pathname === '/dashboard') {
    return '/';
  }
  // 找到最长匹配的叶子菜单，支持 /catalog/tools/xxx 这类带参数的页面路径
  return leafKeys
    .filter((key) => pathname === key || pathname.startsWith(`${key}/`))
    .sort((a, b) => b.length - a.length)[0];
}

export default function AdminLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const [openKeys, setOpenKeys] = useState<string[]>([]);
  const { session, operationItems, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();

  // 菜单 → 后端操作码（前端仅控制展示，后端仍独立校验）
  const menuPermission: MenuEntry[] = [
    { key: '/', icon: <DashboardOutlined />, label: '首页' },
    { key: '/accounts', icon: <UserOutlined />, label: '管理账号', operation: 'admin_account:view' },
    { key: '/roles', icon: <SafetyOutlined />, label: '后台角色', operation: 'role:view' },
    { key: '/caller-systems', icon: <ApiOutlined />, label: '调用系统', operation: 'caller_system:view' },
    {
      key: '/catalog',
      icon: <AppstoreOutlined />,
      label: '工具目录',
      operation: 'tool:view',
      children: [
        { key: '/catalog/tools', icon: <ToolOutlined />, label: '工具', operation: 'tool:view' },
        { key: '/catalog/providers', icon: <ApiOutlined />, label: 'Provider', operation: 'provider:view' },
        { key: '/catalog/capability-packs', icon: <DatabaseOutlined />, label: '能力包', operation: 'capability:view' },
        { key: '/catalog/reviews', icon: <AuditOutlined />, label: '审核', operation: 'tool:review' },
        { key: '/catalog/index-tasks', icon: <DatabaseOutlined />, label: '索引任务', operation: 'system_task:view' },
      ],
    },
    {
      key: '/mcp',
      icon: <ApiOutlined />,
      label: 'MCP 接入',
      operation: 'mcp_server:view',
      children: [
        {
          key: '/mcp/server-config',
          icon: <ApiOutlined />,
          label: '接入配置',
          operation: 'mcp_server:view',
        },
        {
          key: '/mcp/clients',
          icon: <SafetyOutlined />,
          label: '客户端与授权',
          operation: 'mcp_client:view',
        },
        {
          key: '/mcp/exposed-tools',
          icon: <ToolOutlined />,
          label: '暴露工具',
          operation: 'mcp_client:view',
        },
        {
          key: '/mcp/call-records',
          icon: <FileSearchOutlined />,
          label: '调用记录',
          operation: 'mcp_trace:view',
        },
        {
          key: '/mcp/test-debug',
          icon: <ExperimentOutlined />,
          label: '测试调试',
          operation: 'mcp_test:run',
        },
      ],
    },
  ];

  const menuLeafKeys = collectMenuLeafKeys(menuPermission);
  const selectedKey = resolveSelectedMenuKey(location.pathname, menuLeafKeys);
  const selectedMenuParentKey = findMenuParentKey(selectedKey, menuPermission);

  // 路由变化时，自动展开当前菜单所属的父级菜单
  useEffect(() => {
    if (selectedMenuParentKey) {
      setOpenKeys((keys) =>
        keys.includes(selectedMenuParentKey) ? keys : [...keys, selectedMenuParentKey],
      );
    }
  }, [selectedMenuParentKey]);

  const handleOpenChange = (keys: string[]) => {
    // 当前页面所属的父级菜单不允许被收起，保证高亮项始终可见
    setOpenKeys(
      selectedMenuParentKey
        ? Array.from(new Set([...keys, selectedMenuParentKey]))
        : keys,
    );
  };

  const menuItems: MenuProps['items'] = menuPermission
    .filter((item) => !item.operation || operationItems.includes(item.operation))
    .map(({ key, icon, label, children }) => {
      const visibleChildren = children
        ? children.filter((child) => !child.operation || operationItems.includes(child.operation))
        : undefined;
      if (children && (!visibleChildren || visibleChildren.length === 0)) {
        return null;
      }
      return {
        key,
        icon,
        label,
        children: visibleChildren?.map(({ key: childKey, icon: childIcon, label: childLabel }) => ({
          key: childKey,
          icon: childIcon,
          label: childLabel,
        })),
      };
    })
    .filter(Boolean);

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
  };

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

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
          openKeys={collapsed ? undefined : openKeys}
          onOpenChange={handleOpenChange}
          selectedKeys={selectedKey ? [selectedKey] : []}
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
