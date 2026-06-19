import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { queryClient } from '../lib/queryClient';

// Retry fn up to 3x on network errors (TypeError = fetch threw; Error = server responded).
async function retryNetwork<T>(fn: () => Promise<T>): Promise<T> {
  for (let attempt = 0; attempt < 3; attempt++) {
    try { return await fn(); } catch (e) {
      if (!(e instanceof TypeError) || attempt === 2) throw e;
      await new Promise(r => setTimeout(r, 600));
    }
  }
  throw new Error('unreachable');
}

interface AuthCtx {
  authenticated: boolean;
  username: string;
  isAdmin: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  loading: boolean;
  netError: boolean;
  retryAuth: () => void;
}

const Ctx = createContext<AuthCtx>(null!);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [username, setUsername] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [netError, setNetError] = useState(false);
  const [checkTrigger, setCheckTrigger] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNetError(false);

    const schedule = (fn: () => void, delay: number) => {
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        if (!cancelled) fn();
      }, delay);
    };

    const check = async (attemptsLeft: number) => {
      try {
        const s = await api.authStatus();
        if (cancelled) return;
        setAuthenticated(s.authenticated);
        setUsername(s.username ?? '');
        setIsAdmin(s.is_admin ?? false);
        setNetError(false);
        setLoading(false);
      } catch {
        if (cancelled) return;
        if (attemptsLeft > 0 && localStorage.getItem('os_token')) {
          // Still have rapid retries left — try again in 1s
          schedule(() => void check(attemptsLeft - 1), 1000);
        } else if (localStorage.getItem('os_token')) {
          // Rapid retries exhausted but token exists — show reconnect screen,
          // keep auto-retrying every 5s in the background.
          setNetError(true);
          setLoading(false);
          schedule(() => void check(7), 5000);
        } else {
          setLoading(false);
        }
      }
    };
    void check(7);
    return () => {
      cancelled = true;
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    };
  }, [checkTrigger]);

  const login = useCallback(async (u: string, p: string) => {
    const { admin_token } = await retryNetwork(() => api.loginWithCredentials(u, p));
    localStorage.setItem('os_token', admin_token);
    // authStatus is a separate request — retry independently so a blip between
    // the two calls doesn't surface as a credential failure.
    const status = await retryNetwork(() => api.authStatus());
    setAuthenticated(true);
    setUsername(status.username || u);
    setIsAdmin(status.is_admin ?? false);
  }, []);

  const retryAuth = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    setNetError(false);
    setLoading(true);
    setCheckTrigger(t => t + 1);
  }, []);

  const logout = useCallback(async () => {
    await api.apiLogout().catch(() => {});
    localStorage.removeItem('os_token');
    queryClient.clear();
    setAuthenticated(false);
    setUsername('');
    setIsAdmin(false);
    setNetError(false);
  }, []);

  return (
    <Ctx.Provider value={{ authenticated, username, isAdmin, login, logout, loading, netError, retryAuth }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
