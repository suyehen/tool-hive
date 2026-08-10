import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';
import { getSession, fetchCsrfToken, logout as apiLogout, type SessionInfo } from '../api/auth';

interface AuthState {
  session: SessionInfo | null;
  loading: boolean;
  csrfToken: string | null;
}

interface AuthContextValue extends AuthState {
  login: (csrfToken: string, session?: SessionInfo) => void;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    session: null,
    loading: true,
    csrfToken: localStorage.getItem('csrf_token'),
  });

  const refreshSession = useCallback(async () => {
    try {
      const session = await getSession();
      const token = await fetchCsrfToken();
      localStorage.setItem('csrf_token', token);
      setState({ session, loading: false, csrfToken: token });
    } catch {
      localStorage.removeItem('csrf_token');
      setState({ session: null, loading: false, csrfToken: null });
    }
  }, []);

  useEffect(() => {
    refreshSession();
  }, [refreshSession]);

  const login = useCallback((token: string, session?: SessionInfo) => {
    localStorage.setItem('csrf_token', token);
    setState((prev) => ({ ...prev, csrfToken: token, session: session || prev.session }));
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // ignore
    }
    localStorage.removeItem('csrf_token');
    setState({ session: null, loading: false, csrfToken: null });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, logout, refreshSession }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
