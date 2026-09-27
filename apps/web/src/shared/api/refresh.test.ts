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
});
