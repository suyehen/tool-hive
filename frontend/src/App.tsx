import { Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import AdminLayout from './layouts/AdminLayout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import AccountListPage from './pages/accounts/AccountListPage';
import RoleListPage from './pages/roles/RoleListPage';
import CallerSystemListPage from './pages/caller-systems/CallerSystemListPage';
import ProvidersPage from './pages/catalog/ProvidersPage';
import CapabilityPacksPage from './pages/catalog/CapabilityPacksPage';
import ToolsPage from './pages/catalog/ToolsPage';
import ReviewsPage from './pages/catalog/ReviewsPage';
import IndexTasksPage from './pages/catalog/IndexTasksPage';

export default function App() {
  return (
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
  );
}
