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
  userId: string;
  isAdmin: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  netError: boolean;
  retryAuth: () => void;
}

const Ctx = createContext<AuthCtx>(null!);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // Optimistic: if a token is in localStorage, assume authenticated immediately.
  // The background check corrects this if the token turns out to be invalid.
  const [authenticated, setAuthenticated] = useState(() => !!localStorage.getItem('os_token'));
  const [username, setUsername] = useState('');
  const [userId, setUserId] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [netError, setNetError] = useState(false);
  const [checkTrigger, setCheckTrigger] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    const hasToken = !!localStorage.getItem('os_token');

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
        // If server says "not authenticated" but we have a stored token, treat it
        // as a transient failure (shared DB conn race, proxy blip) and retry before
        // dropping the user to the login form.
        if (!s.authenticated && hasToken && attemptsLeft > 0) {
          schedule(() => void check(attemptsLeft - 1), 1000);
          return;
        }
        setAuthenticated(s.authenticated);
        setUsername(s.username ?? '');
        setUserId(s.user_id ?? '');
        setIsAdmin(s.is_admin ?? false);
        setNetError(false);
      } catch {
        if (cancelled) return;
        if (attemptsLeft > 0) {
          schedule(() => void check(attemptsLeft - 1), 1000);
        } else if (!hasToken) {
          setNetError(true);
        }
        // Token exists + can't reach server: stay optimistic, React Query handles failures.
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
    setUserId(status.user_id ?? '');
    setIsAdmin(status.is_admin ?? false);
  }, []);

  const retryAuth = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    setNetError(false);
    setCheckTrigger(t => t + 1);
  }, []);

  const logout = useCallback(async () => {
    await api.apiLogout().catch(() => {});
    localStorage.removeItem('os_token');
    queryClient.clear();
    setAuthenticated(false);
    setUsername('');
    setUserId('');
    setIsAdmin(false);
    setNetError(false);
  }, []);

  return (
    <Ctx.Provider value={{ authenticated, username, userId, isAdmin, login, logout, netError, retryAuth }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
