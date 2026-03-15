"use client";

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

type AppStatus = "idle" | "loading" | "success" | "error";

interface AppStatusState {
  status: AppStatus;
  setStatus: (status: AppStatus) => void;
}

const AppStatusContext = createContext<AppStatusState | null>(null);

export function AppStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatusRaw] = useState<AppStatus>("idle");

  const setStatus = useCallback((s: AppStatus) => setStatusRaw(s), []);

  return (
    <AppStatusContext.Provider value={{ status, setStatus }}>
      {children}
    </AppStatusContext.Provider>
  );
}

export function useAppStatus() {
  const ctx = useContext(AppStatusContext);
  if (!ctx) throw new Error("useAppStatus must be used within AppStatusProvider");
  return ctx;
}
