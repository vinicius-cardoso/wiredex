import { useQuery } from "@tanstack/react-query";
import type { AttachmentResponse } from "@wiredex/api-client";
import { attachmentKeys, attachmentsQuery } from "../../files/attachments";
import { type Bundle, BundleError, readBundle } from "./bundle";

/** A version as an attachment's subject, the way the files API names it. */
export function buildsSubject(versionId: string): string {
  return `firmware_version:${versionId}`;
}

/**
 * A version's newest build, as far as it is known: still being fetched, none stored, stored
 * but not one this dialog can write, or read and ready.
 */
export type StoredBuild =
  | { state: "loading" | "none" }
  | { state: "unreadable"; attachment: AttachmentResponse; problem: BundleError | null }
  | { state: "ready"; attachment: AttachmentResponse; bundle: Bundle };

/**
 * The build the flash dialog offers for a version (spec 20, requirement 3.1): its newest, since
 * a version's attachments come newest first and are all builds. The zip is fetched and read
 * once: the same attachment is always the same bytes. With no version chosen there is none.
 */
export function useStoredBuild(versionId: string | null): StoredBuild {
  const builds = useQuery({
    ...attachmentsQuery(buildsSubject(versionId ?? "")),
    enabled: versionId !== null,
  });
  const newest = builds.data?.[0];
  const bundle = useQuery({
    queryKey: [...attachmentKeys.all, "build", newest?.id],
    queryFn: async () => {
      const response = await fetch(newest?.content_url ?? "", { credentials: "same-origin" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return readBundle(new Uint8Array(await response.arrayBuffer()));
    },
    enabled: newest !== undefined,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });

  if (versionId === null) return { state: "none" };
  if (builds.isPending) return { state: "loading" };
  // A list that can't be read leaves the computer's files, as a version with no build does.
  if (!newest) return { state: "none" };
  if (bundle.isPending) return { state: "loading" };
  if (bundle.data) return { state: "ready", attachment: newest, bundle: bundle.data };
  return {
    state: "unreadable",
    attachment: newest,
    problem: bundle.error instanceof BundleError ? bundle.error : null,
  };
}
