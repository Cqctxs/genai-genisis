"use client";

import { useAppStatus } from "@/lib/app-status-context";

const FOOTER_HEIGHT = "2rem";

export const FOOTER_HEIGHT_CLASS = "h-8";

export function GlobalFooterPill() {
  const { status } = useAppStatus();

  const isLoading = status === "loading";

  const colorClass =
    status === "idle"
      ? "bg-light/20"
      : status === "success"
        ? "bg-accent-green"
        : status === "error"
          ? "bg-accent-red"
          : "";

  return (
    <div className="shrink-0 flex items-center justify-center py-4 border-t border-light/10 w-full relative z-40">
      <div
        className={`w-32 sm:w-40 h-1.5 rounded-full transition-colors duration-500 ${
          isLoading ? "animate-scroll-bg" : colorClass
        }`}
        style={
          isLoading
            ? {
                backgroundImage:
                  "linear-gradient(90deg, var(--color-accent-blue), var(--color-accent-purple), var(--color-accent-blue))",
                backgroundSize: "200% auto",
              }
            : undefined
        }
        role="status"
        aria-label={`Application status: ${status}`}
      />
    </div>
  );
}
