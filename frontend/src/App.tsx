import { lazy, Suspense } from 'react';
import { Spin } from 'antd';
import { Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import AdminLayout from './layouts/AdminLayout';

const LoginPage = lazy(() => import('./pages/LoginPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const ChangePasswordPage = lazy(() => import('./pages/ChangePasswordPage'));
const AccountListPage = lazy(() => import('./pages/accounts/AccountListPage'));
const RoleListPage = lazy(() => import('./pages/roles/RoleListPage'));
const CallerSystemListPage = lazy(() => import('./pages/caller-systems/CallerSystemListPage'));
const ProvidersPage = lazy(() => import('./pages/catalog/ProvidersPage'));
const CapabilityPacksPage = lazy(() => import('./pages/catalog/CapabilityPacksPage'));
const ToolsPage = lazy(() => import('./pages/catalog/ToolsPage'));
const ReviewsPage = lazy(() => import('./pages/catalog/ReviewsPage'));
const IndexTasksPage = lazy(() => import('./pages/catalog/IndexTasksPage'));

function PageFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
      <Spin size="large" />
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AdminLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="change-password" element={<ChangePasswordPage />} />
          <Route path="accounts" element={<AccountListPage />} />
          <Route path="roles" element={<RoleListPage />} />
          <Route path="caller-systems" element={<CallerSystemListPage />} />
          <Route path="catalog/providers" element={<ProvidersPage />} />
          <Route path="catalog/capability-packs" element={<CapabilityPacksPage />} />
          <Route path="catalog/tools" element={<ToolsPage />} />
          <Route path="catalog/reviews" element={<ReviewsPage />} />
          <Route path="catalog/index-tasks" element={<IndexTasksPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
