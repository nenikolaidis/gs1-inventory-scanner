// Server settings the interface depends on (fetched once per page load).

import { useEffect, useState } from "react";

import { api } from "./api";

export interface AppConfig {
  version: string;
  expiry_warning_days: number;
  label_printer: boolean;
  label_dpi: number;
  label_size: string;
}

let cached: Promise<AppConfig> | null = null;

export function useConfig(): AppConfig | null {
  const [config, setConfig] = useState<AppConfig | null>(null);
  useEffect(() => {
    cached ??= api.get<AppConfig>("/api/config");
    cached.then(setConfig, () => {
      cached = null;
    });
  }, []);
  return config;
}
