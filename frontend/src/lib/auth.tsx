"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, onUnauthenticated, refreshAccessToken, setAccessToken } from "@/lib/api-client";
import type { Me, TokenResponse } from "@/lib/types";

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface RegisterInput {
  email: string;
  password: string;
  full_name: string;
}

interface AuthContextValue {
  status: AuthStatus;
  me: Me | null;
  login: (email: string, password: string) => Promise<Me>;
  register: (input: RegisterInput) => Promise<Me>;
  logout: () => Promise<void>;
  reload: () => Promise<Me | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [me, setMe] = useState<Me | null>(null);

  const reload = useCallback(async () => {
    try {
      const data = await api<Me>("/auth/me");
      setMe(data);
      setStatus("authenticated");
      return data;
    } catch {
      setMe(null);
      setStatus("anonymous");
      return null;
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const token = await refreshAccessToken();
      if (cancelled) return;
      if (token) await reload();
      else setStatus("anonymous");
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  useEffect(
    () =>
      onUnauthenticated(() => {
        setAccessToken(null);
        setMe(null);
        setStatus("anonymous");
      }),
    [],
  );

  const startSession = useCallback(
    async (response: TokenResponse) => {
      setAccessToken(response.access_token);
      const data = await reload();
      if (!data) throw new Error("Could not load your account");
      return data;
    },
    [reload],
  );

  const login = useCallback(
    async (email: string, password: string) =>
      startSession(
        await api<TokenResponse>("/auth/login", {
          method: "POST",
          body: { email, password },
          auth: false,
        }),
      ),
    [startSession],
  );

  const register = useCallback(
    async (input: RegisterInput) =>
      startSession(
        await api<TokenResponse>("/auth/register", { method: "POST", body: input, auth: false }),
      ),
    [startSession],
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST", auth: false });
    } finally {
      setAccessToken(null);
      setMe(null);
      setStatus("anonymous");
      queryClient.clear();
    }
  }, [queryClient]);

  const value = useMemo(
    () => ({ status, me, login, register, logout, reload }),
    [status, me, login, register, logout, reload],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
