import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Board, Flash, NewFlash, UnitFirmware } from "@wiredex/api-client";
import { useTranslation } from "react-i18next";
import { api } from "../../shared/api/client";
import { refreshAfterWrite } from "../../shared/api/refresh";
import { FirmwareRefusal, firmwareKeys } from "./firmware";

/** How far ahead of now the API dates a flash: a phone's clock a little fast (requirement 1.4). */
export const FUTURE_ALLOWANCE_MS = 5 * 60_000;

export function boardsQuery(firmwareId: string) {
  return queryOptions({
    queryKey: firmwareKeys.boards(firmwareId),
    queryFn: async (): Promise<Board[]> => {
      const { data, error, response } = await api.GET("/api/firmware/{firmware_id}/boards", {
        params: { path: { firmware_id: firmwareId } },
      });
      if (!data) throw FirmwareRefusal.from(response.status, error);
      return data;
    },
  });
}

/** The units whose newest flash is one of the firmware's versions, by code (requirement 4.1). */
export function useBoards(firmwareId: string) {
  return useQuery(boardsQuery(firmwareId));
}

/** An instant in the reader's language and zone, to the minute, as every flash screen shows it. */
export function useTimeFormat(): (iso: string) => string {
  const { i18n } = useTranslation();
  const format = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return (iso) => format.format(new Date(iso));
}

export function unitFirmwareQuery(unitId: string) {
  return queryOptions({
    queryKey: firmwareKeys.unit(unitId),
    queryFn: async (): Promise<UnitFirmware> => {
      const { data, error, response } = await api.GET("/api/firmware/units/{unit_id}", {
        params: { path: { unit_id: unitId } },
      });
      if (!data) throw FirmwareRefusal.from(response.status, error);
      return data;
    },
  });
}

/** What a board runs and its flash log, newest first (requirement 2). */
export function useUnitFirmware(unitId: string) {
  return useQuery(unitFirmwareQuery(unitId));
}

export type FlashLogging = { unitId: string; body: NewFlash };

export function useLogFlash() {
  const invalidate = useFlashInvalidation();
  return useMutation({
    mutationFn: async ({ unitId, body }: FlashLogging): Promise<Flash> => {
      const { data, error, response } = await api.POST("/api/firmware/units/{unit_id}/flashes", {
        params: { path: { unit_id: unitId } },
        body,
      });
      if (data) return data;
      throw FirmwareRefusal.from(response.status, error);
    },
    // Awaited, so the unit's log holds the flash by the time the dialog closes.
    onSuccess: invalidate,
  });
}

/** Removes an entry logged by mistake, whatever its unit's status (requirement 3.1). */
export function useRemoveFlash() {
  const invalidate = useFlashInvalidation();
  return useMutation({
    mutationFn: async (flashId: string): Promise<void> => {
      const { error, response } = await api.DELETE("/api/firmware/flashes/{flash_id}", {
        params: { path: { flash_id: flashId } },
      });
      // A 404 is already gone, which is what was asked.
      if (!response.ok && response.status !== 404) {
        throw FirmwareRefusal.from(response.status, error);
      }
    },
    onSuccess: invalidate,
  });
}

/**
 * A flash moves a unit's current version, a firmware's boards and what keeps a version from
 * being deleted, all under firmware's root, so each write drops it (requirement 8.8).
 */
function useFlashInvalidation() {
  const queryClient = useQueryClient();
  return () => refreshAfterWrite(queryClient, firmwareKeys.all);
}

const LOCAL_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?$/;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** DATE as a `datetime-local` value, in the browser's own zone, to the minute. */
export function localInputValue(date: Date): string {
  const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  return `${day}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * A `datetime-local` value as ISO 8601 with the browser's offset, which the API needs to read
 * it as an instant, or null when it isn't a date and a time.
 */
export function withOffset(value: string): string | null {
  if (!LOCAL_TIME.test(value)) return null;
  // A date and a time without an offset read as local time, which is what the input holds.
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const east = -date.getTimezoneOffset();
  const sign = east >= 0 ? "+" : "-";
  const zone = `${sign}${pad(Math.floor(Math.abs(east) / 60))}:${pad(Math.abs(east) % 60)}`;
  return `${localInputValue(date)}:${pad(date.getSeconds())}${zone}`;
}
