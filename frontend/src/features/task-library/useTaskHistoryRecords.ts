import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, isTerminalStatus, retryPollDelay } from "../../api/client";
import type { LibrarySearchResult, Task } from "../../api/types";
import { mergeNewestTasks } from "./model";

async function requestAllTaskPages(signal?: AbortSignal): Promise<Task[]> {
  const tasks: Task[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ limit: "100" });
    if (cursor) query.set("cursor", cursor);
    const page = await api.requestPage<Task[]>(
      `/api/tasks?${query.toString()}`,
      signal,
    );
    tasks.push(...page.data);
    if (page.nextCursor === null) break;
    if (seenCursors.has(page.nextCursor)) throw new Error("task cursor repeated");
    seenCursors.add(page.nextCursor);
    cursor = page.nextCursor;
  } while (cursor);
  return tasks;
}

export function useTaskHistoryRecords({
  searchActive,
  discoveryQuery,
}: {
  searchActive: boolean;
  discoveryQuery: string;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [searchResults, setSearchResults] = useState<LibrarySearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const deletedTaskIdsRef = useRef<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    if (searchActive) {
      try {
        const results = await api.request<LibrarySearchResult[]>(
          `/api/library/search?${discoveryQuery}`,
        );
        setSearchResults(results);
        setTasks(results.map((result) => result.task));
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "无法搜索总结记录。");
      } finally {
        setLoading(false);
      }
      return;
    }
    try {
      const result = await requestAllTaskPages();
      setTasks(
        result.filter((task) => !deletedTaskIdsRef.current.has(task.id)),
      );
      setSearchResults([]);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "无法读取总结记录。");
    } finally {
      setLoading(false);
    }
  }, [discoveryQuery, searchActive]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasActiveTasks = useMemo(
    () => tasks.some((task) => !isTerminalStatus(task.status)),
    [tasks],
  );

  useEffect(() => {
    if (!hasActiveTasks || searchActive) return;
    let disposed = false;
    let failureCount = 0;
    let timer: number | null = null;
    let controller: AbortController | null = null;

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => void refresh(), delay);
    };
    const refresh = async () => {
      controller = new AbortController();
      try {
        const result = await requestAllTaskPages(controller.signal);
        if (disposed) return;
        failureCount = 0;
        setTasks((current) =>
          mergeNewestTasks(
            current,
            result.filter((task) => !deletedTaskIdsRef.current.has(task.id)),
          ),
        );
        schedule(document.hidden ? 10_000 : 1_500);
      } catch (caught) {
        if (disposed || (caught instanceof DOMException && caught.name === "AbortError")) {
          return;
        }
        failureCount += 1;
        schedule(retryPollDelay(failureCount));
      }
    };

    schedule(document.hidden ? 5_000 : 900);
    return () => {
      disposed = true;
      controller?.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [hasActiveTasks, searchActive]);

  const markTasksDeleted = useCallback((taskIds: string[]) => {
    for (const taskId of taskIds) deletedTaskIdsRef.current.add(taskId);
  }, []);

  return {
    tasks,
    setTasks,
    searchResults,
    setSearchResults,
    loading,
    error,
    setError,
    load,
    markTasksDeleted,
  };
}
