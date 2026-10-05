// Server settings the interface depends on (fetched once, after login).

import { useEffect, useState } from "react";

import { api } from "./api";
import { useAuth } from "./auth";

export interface AppConfig {
  version: string;
  expiry_warning_days: number;
  label_printer: boolean;
  label_dpi: number;
  label_size: string;
}

let cached: Promise<AppConfig> | null = null;

export function useConfig(): AppConfig | null {
  const { user } = useAuth();
  const [config, setConfig] = useState<AppConfig | null>(null);
  useEffect(() => {
    if (!user) return; // the endpoint needs a login; fetch once someone has logged in
    cached ??= api.get<AppConfig>("/api/config");
    cached.then(setConfig, () => {
      cached = null;
    });
  }, [user]);
  return user ? config : null;
}
