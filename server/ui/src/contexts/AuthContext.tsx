import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api } from '../api';
import { queryClient } from '../lib/queryClient';

interface AuthCtx {
  authenticated: boolean;
  username: string;
  isAdmin: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  loading: boolean;
}

const Ctx = createContext<AuthCtx>(null!);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [username, setUsername] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const check = async (attemptsLeft: number) => {
      try {
        const s = await api.authStatus();
        if (cancelled) return;
        setAuthenticated(s.authenticated);
        setUsername(s.username ?? '');
        setIsAdmin(s.is_admin ?? false);
        setLoading(false);
      } catch {
        if (cancelled) return;
        // Network error (server restarting) — retry if we have a stored token
        if (attemptsLeft > 0 && localStorage.getItem('os_token')) {
          setTimeout(() => check(attemptsLeft - 1), 1500);
        } else {
          setLoading(false);
        }
      }
    };
    void check(4);
    return () => { cancelled = true; };
  }, []);

  const login = useCallback(async (u: string, p: string) => {
    // TypeError = fetch() itself threw (network drop, DNS failure). Error = server responded
    // with 4xx — wrong password, don't retry. Programming bugs inside req() could also throw
    // TypeError, but loginWithCredentials is a single fetch with no post-processing, so the
    // risk of masking a bug here is negligible.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const { admin_token } = await api.loginWithCredentials(u, p);
        localStorage.setItem('os_token', admin_token);
        break;
      } catch (e) {
        if (!(e instanceof TypeError) || attempt === 2) throw e;
        await new Promise(r => setTimeout(r, 600));
      }
    }
    // authStatus lives outside the retry loop — a blip after a successful token
    // issue should not surface as a credential failure.
    const status = await api.authStatus();
    setAuthenticated(true);
    setUsername(status.username || u);
    setIsAdmin(status.is_admin ?? false);
  }, []);

  const logout = useCallback(async () => {
    await api.apiLogout().catch(() => {});
    localStorage.removeItem('os_token');
    queryClient.clear();
    setAuthenticated(false);
    setUsername('');
    setIsAdmin(false);
  }, []);

  return (
    <Ctx.Provider value={{ authenticated, username, isAdmin, login, logout, loading }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
