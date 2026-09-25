import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { Pinout, PinoutReplacement } from "@wiredex/api-client";
import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { acceptPinoutSaves, aPin, refusePinoutSaves, server } from "../../../test/server";
import { PinoutRefusal, useReplacePinout } from "./pinout";

const PART = "0199cccc-0000-7000-8000-000000000001";
const TABLE: PinoutReplacement = {
  pins: [{ number: "2", label: "VOUT", type: "power", functions: [], voltage: "3V3" }],
};

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useReplacePinout(PART), { wrapper });
}

/** Saves `TABLE`, answering what was stored, or nothing when the API refused it. */
async function save(result: { current: ReturnType<typeof useReplacePinout> }) {
  let stored: Pinout | undefined;
  await act(async () => {
    stored = await result.current.mutateAsync(TABLE).catch(() => undefined);
  });
  return stored;
}

describe("useReplacePinout", () => {
  it("sends the whole table and keeps what came back stored", async () => {
    const sent = acceptPinoutSaves([aPin({ number: "2", label: "VOUT", type: "power" })]);
    const { result } = setup();

    const stored = await save(result);

    expect(sent).toEqual([TABLE]);
    expect(stored?.pins.map((pin) => pin.label)).toEqual(["VOUT"]);
  });

  it("carries the row and the cell a refused table names", async () => {
    refusePinoutSaves("row 12: pin 5 is already row 3", { row: 12, field: "number" });
    const { result } = setup();

    await save(result);

    const refusal = result.current.error;
    expect(refusal).toBeInstanceOf(PinoutRefusal);
    expect(refusal).toMatchObject({ status: 422, row: 12, field: "number" });
    expect(refusal?.message).toContain("pin 5 is already row 3");
  });

  it("carries no row when the table is refused as a whole", async () => {
    refusePinoutSaves("a pinout has at most 1024 pins");
    const { result } = setup();

    await save(result);

    expect(result.current.error).toMatchObject({ row: null, field: null });
  });

  it("drops a cell name it doesn't know, keeping the message", async () => {
    refusePinoutSaves("row 2: that cell is odd", { row: 2, field: "colour" });
    const { result } = setup();

    await save(result);

    expect(result.current.error).toMatchObject({ row: 2, field: null });
    expect(result.current.error?.message).toContain("that cell is odd");
  });

  it("reads a plain refusal, as a part in another workspace gets", async () => {
    server.use(
      http.put("*/api/catalog/parts/:partId/pinout", () =>
        HttpResponse.json({ detail: "that part doesn't exist" }, { status: 404 }),
      ),
    );
    const { result } = setup();

    await save(result);

    expect(result.current.error).toMatchObject({ status: 404, row: null, field: null });
    expect(result.current.error?.message).toBe("that part doesn't exist");
  });
});
