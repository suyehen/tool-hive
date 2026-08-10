import { Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import AdminLayout from './layouts/AdminLayout';
import LoginPage from './pages/LoginPage';
import MfaSetupPage from './pages/MfaSetupPage';
import DashboardPage from './pages/DashboardPage';
import AccountListPage from './pages/accounts/AccountListPage';
import RoleListPage from './pages/roles/RoleListPage';
import CallerSystemListPage from './pages/caller-systems/CallerSystemListPage';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/mfa-setup" element={<MfaSetupPage />} />
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
        <Route path="accounts" element={<AccountListPage />} />
        <Route path="roles" element={<RoleListPage />} />
        <Route path="caller-systems" element={<CallerSystemListPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
