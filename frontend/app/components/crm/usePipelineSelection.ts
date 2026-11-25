"use client";
import { useEffect, useRef, useSyncExternalStore } from "react";
import type { Funnel } from "./types";

export const PIPELINE_STORAGE_KEY = "gmapscrap.crm.pipelineId";
const changed = "gmapscrap:crm-pipeline-changed";
let memoryId = 0;
let failedWrite: { previous: string | null | undefined } | null = null;

function read() {
  if (typeof window === "undefined") return 0;
  try {
    const raw = window.localStorage.getItem(PIPELINE_STORAGE_KEY);
    // Quota/private-mode failures must not immediately undo the user's choice
    // merely because getItem still returns the previous stored value.
    if (failedWrite && raw === failedWrite.previous) return memoryId;
    failedWrite = null;
    const value = Number(raw);
    memoryId = Number.isSafeInteger(value) && value > 0 ? value : 0;
  } catch { /* Storage may be disabled; keep selection for this page session. */ }
  return memoryId;
}

function write(id: number) {
  memoryId = id;
  let previous: string | null | undefined;
  try { previous = window.localStorage.getItem(PIPELINE_STORAGE_KEY); } catch { /* Storage blocked. */ }
  try {
    if (id) window.localStorage.setItem(PIPELINE_STORAGE_KEY, String(id));
    else window.localStorage.removeItem(PIPELINE_STORAGE_KEY);
    failedWrite = null;
  } catch { failedWrite = {previous}; }
  window.dispatchEvent(new Event(changed));
}

function subscribe(notify: () => void) {
  const storage = (event: StorageEvent) => {
    if (event.key === PIPELINE_STORAGE_KEY || event.key === null) { failedWrite = null; notify(); }
  };
  window.addEventListener(changed, notify);
  window.addEventListener("storage", storage);
  return () => { window.removeEventListener(changed, notify); window.removeEventListener("storage", storage); };
}

export function usePipelineSelection(funnels: Funnel[] | null) {
  const saved = useSyncExternalStore(subscribe, read, () => 0);
  const validatedMetadata = useRef<Funnel[] | null>(null);
  // Null means metadata is loading. Never display a guessed first pipeline.
  const id = funnels?.some(item => item.id === saved) ? saved : 0;
  const needsMetadata = funnels !== null && validatedMetadata.current === funnels && !id && (funnels.length > 0 || saved > 0);
  useEffect(() => {
    if (funnels === null) return;
    validatedMetadata.current = funnels;
    const latest = read();
    const validated = funnels.some(item => item.id === latest) ? latest : funnels[0]?.id || 0;
    if (validated !== latest) write(validated);
    // Only freshly fetched metadata may replace a missing saved pipeline.
    // A stale sibling view must refresh instead of overwriting that choice.
  }, [funnels]);
  const select = (next: number) => {
    if (funnels?.some(item => item.id === next)) write(next);
  };
  return [id, select, needsMetadata] as const;
}
