import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';
import {
  getSession,
  getMe,
  getOperationItems,
  fetchCsrfToken,
  logout as apiLogout,
  type SessionInfo,
  type MeInfo,
} from '../api/auth';

interface AuthState {
  session: SessionInfo | null;
  me: MeInfo | null;
  operationItems: string[];
  loading: boolean;
  csrfToken: string | null;
}

interface AuthContextValue extends AuthState {
  login: (csrfToken: string, session: SessionInfo, me: MeInfo, operationItems: string[]) => void;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  hasOperation: (code: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    session: null,
    me: null,
    operationItems: [],
    loading: true,
    csrfToken: localStorage.getItem('csrf_token'),
  });

  const refreshSession = useCallback(async () => {
    try {
      const [session, me, operationItems, token] = await Promise.all([
        getSession(),
        getMe(),
        getOperationItems(),
        fetchCsrfToken(),
      ]);
      localStorage.setItem('csrf_token', token);
      setState({ session, me, operationItems, loading: false, csrfToken: token });
    } catch {
      localStorage.removeItem('csrf_token');
      setState({ session: null, me: null, operationItems: [], loading: false, csrfToken: null });
    }
  }, []);

  useEffect(() => {
    refreshSession();
  }, [refreshSession]);

  const login = useCallback(
    (token: string, session: SessionInfo, me: MeInfo, operationItems: string[]) => {
    localStorage.setItem('csrf_token', token);
    setState((prev) => ({
      ...prev,
      csrfToken: token,
      session,
      me,
      operationItems,
      loading: false,
    }));
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // ignore
    }
    localStorage.removeItem('csrf_token');
    setState({ session: null, me: null, operationItems: [], loading: false, csrfToken: null });
  }, []);

  const hasOperation = useCallback(
    (code: string) => state.operationItems.includes(code),
    [state.operationItems],
  );

  return (
    <AuthContext.Provider value={{ ...state, login, logout, refreshSession, hasOperation }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
