import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import { sessionsQuery } from "./sessions";

/** Why a change was refused: the API's four codes, too many wrong tries, or anything else. */
export type PasswordFailure =
  | "wrong_password"
  | "weak_password"
  | "same_password"
  | "password_like_account"
  | "throttled"
  | "unavailable";

const CODES: readonly PasswordFailure[] = [
  "wrong_password",
  "weak_password",
  "same_password",
  "password_like_account",
];

export class PasswordError extends Error {
  constructor(readonly failure: PasswordFailure) {
    super(`the password wasn't changed: ${failure}`);
  }
}

export type PasswordChange = { currentPassword: string; newPassword: string };

/**
 * Changes your own password. The API ends every other session when it does, so the devices
 * list is fetched again; this session stays.
 */
export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ currentPassword, newPassword }: PasswordChange): Promise<number> => {
      const { data, error, response } = await api.POST("/api/auth/password", {
        body: { current_password: currentPassword, new_password: newPassword },
      });
      if (data) return data.revoked_sessions;
      if (response.status === 429) throw new PasswordError("throttled");
      const code = (error as { detail?: { code?: unknown } } | undefined)?.detail?.code;
      const known = CODES.find((each) => each === code);
      throw new PasswordError(known ?? "unavailable");
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sessionsQuery.queryKey }),
  });
}

/** The failure of a change, whatever was thrown. */
export function passwordFailure(error: unknown): PasswordFailure {
  return error instanceof PasswordError ? error.failure : "unavailable";
}
