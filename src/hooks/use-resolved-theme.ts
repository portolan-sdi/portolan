"use client";

import { useSyncExternalStore } from "react";

type ResolvedTheme = "light" | "dark";

// theme-toggle.tsx writes the active theme to `data-theme` on <html>. There is
// no theme context, so we read that attribute directly through an external
// store. Each subscriber gets its own MutationObserver (created in subscribe,
// disconnected on cleanup) rather than a shared module-level observer.
function subscribe(callback: () => void): () => void {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
}

function getSnapshot(): ResolvedTheme {
  return document.documentElement.getAttribute("data-theme") === "dark"
    ? "dark"
    : "light";
}

function getServerSnapshot(): ResolvedTheme {
  return "light";
}

export function useResolvedTheme(): ResolvedTheme {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
