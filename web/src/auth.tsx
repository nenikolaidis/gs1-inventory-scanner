import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, setUnauthorizedHandler, type User } from "./api";
import { isOffline } from "./offline";

// The last logged-in user, so the app can start without a connection. The
// server still checks the session cookie on every request once it's reachable.
const USER_KEY = "auth.user";

function rememberUser(user: User | null) {
  try {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(USER_KEY);
  } catch {
    // storage unavailable
  }
}

function rememberedUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

interface AuthState {
  user: User | null;
  needsSetup: boolean;
  loading: boolean;
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const setUser = useCallback((u: User | null) => {
    setUserState(u);
    rememberUser(u);
  }, []);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    (async () => {
      try {
        const { needs_setup } = await api.get<{ needs_setup: boolean }>("/api/auth/setup");
        setNeedsSetup(needs_setup);
        if (!needs_setup) setUser(await api.get<User>("/api/auth/me"));
      } catch (e) {
        setUser(isOffline(e) ? rememberedUser() : null);
      } finally {
        setLoading(false);
      }
    })();
  }, [setUser]);

  const handleSetUser = useCallback(
    (u: User | null) => {
      setUser(u);
      if (u) setNeedsSetup(false);
    },
    [setUser],
  );

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout").catch(() => {});
    setUser(null);
  }, [setUser]);

  return (
    <AuthContext.Provider value={{ user, needsSetup, loading, setUser: handleSetUser, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** The logged-in user; only use inside screens shown after login. */
export function useUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("useUser without a logged-in user");
  return user;
}
