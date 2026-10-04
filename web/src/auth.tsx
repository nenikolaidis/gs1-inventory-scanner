import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, setUnauthorizedHandler, type User } from "./api";

interface AuthState {
  user: User | null;
  needsSetup: boolean;
  loading: boolean;
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    (async () => {
      try {
        const { needs_setup } = await api.get<{ needs_setup: boolean }>("/api/auth/setup");
        setNeedsSetup(needs_setup);
        if (!needs_setup) setUser(await api.get<User>("/api/auth/me"));
      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSetUser = useCallback((u: User | null) => {
    setUser(u);
    if (u) setNeedsSetup(false);
  }, []);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout").catch(() => {});
    setUser(null);
  }, []);

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
