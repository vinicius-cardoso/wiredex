import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { refreshAfterWrite } from "./refresh";

describe("refreshAfterWrite", () => {
  it("refetches a query whose first load started before the write", async () => {
    const queryClient = new QueryClient();
    let stored = ["Drawer A"];
    let releaseFirstLoad = () => {};
    let calls = 0;
    const observer = new QueryObserver(queryClient, {
      queryKey: ["locations"],
      queryFn: async () => {
        calls += 1;
        const snapshot = [...stored];
        // The first load answers only after the write, with what it read before it.
        if (calls === 1) await new Promise<void>((resolve) => (releaseFirstLoad = resolve));
        return snapshot;
      },
    });
    const unsubscribe = observer.subscribe(() => {});

    stored = [...stored, "Drawer B"];
    const refreshed = refreshAfterWrite(queryClient, ["locations"]);
    releaseFirstLoad();
    await refreshed;

    expect(queryClient.getQueryData(["locations"])).toEqual(["Drawer A", "Drawer B"]);
    unsubscribe();
  });

  it("refetches the history and the dashboard's counts with every write, whatever it wrote", async () => {
    const queryClient = new QueryClient();
    const reads = { activity: 0, counts: 0, firmware: 0 };
    const watch = (queryKey: string[], name: keyof typeof reads) =>
      new QueryObserver(queryClient, {
        queryKey,
        queryFn: async () => {
          reads[name] += 1;
          return reads[name];
        },
      }).subscribe(() => {});
    const unsubscribes = [
      watch(["history", "recent"], "activity"),
      watch(["dashboard", "counts"], "counts"),
      watch(["firmware", "list"], "firmware"),
    ];
    await expect.poll(() => reads).toEqual({ activity: 1, counts: 1, firmware: 1 });

    await refreshAfterWrite(queryClient, ["catalog"]);
    // Read again without being named; what the write didn't touch is left alone.
    expect(reads).toEqual({ activity: 2, counts: 2, firmware: 1 });

    // A write that names the history itself still reads it once more, not twice.
    await refreshAfterWrite(queryClient, ["history"]);
    expect(reads).toEqual({ activity: 3, counts: 3, firmware: 1 });
    for (const unsubscribe of unsubscribes) unsubscribe();
  });
});
