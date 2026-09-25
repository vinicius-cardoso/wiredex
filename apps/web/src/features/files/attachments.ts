import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  AttachmentKind,
  AttachmentResponse,
  ChangeAttachmentRequest,
} from "@wiredex/api-client";
import { api } from "../../shared/api/client";

/**
 * A subject is what an attachment belongs to, the `part:<uuid>` string the API parses from
 * and echoes back. The web builds it for a part and never takes it apart.
 */
export function subjectOfPart(partId: string): string {
  return `part:${partId}`;
}

/** Every attachment cache hangs off one subject, so a change to a part's files is one key. */
export const attachmentKeys = {
  all: ["attachments"] as const,
  ofSubject: (subject: string) => ["attachments", subject] as const,
};

export function attachmentsQuery(subject: string) {
  return queryOptions({
    queryKey: attachmentKeys.ofSubject(subject),
    queryFn: async (): Promise<AttachmentResponse[]> => {
      const { data } = await api.GET("/api/files/attachments", {
        params: { query: { subject } },
      });
      if (!data) throw new Error("Could not load the attachments");
      return data;
    },
  });
}

/** A part's attachments, newest first (requirement 6.1). */
export function useAttachments(subject: string) {
  return useQuery(attachmentsQuery(subject));
}

/**
 * Why an upload was refused, in the API's own words, so the section can say "too large",
 * "not a PDF or picture", "quota reached" or "already attached" without translating a status
 * into a guess (requirement 6.3). The status is kept for a caller that wants to branch on it.
 */
export class UploadRefusal extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message || `the upload was refused with ${status}`);
  }
}

export type UploadRequest = {
  subject: string;
  kind: AttachmentKind;
  file: File;
  title?: string;
};

/**
 * Uploads one file as multipart, with the CSRF header every write carries (the client's
 * middleware adds it). The bytes are sent as `FormData`, so the browser sets the multipart
 * boundary; a refusal becomes an {@link UploadRefusal} carrying the API's message.
 */
export function useUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      subject,
      kind,
      file,
      title,
    }: UploadRequest): Promise<AttachmentResponse> => {
      const form = new FormData();
      form.set("subject", subject);
      form.set("kind", kind);
      form.set("file", file);
      if (title !== undefined && title !== "") form.set("title", title);
      const { data, error, response } = await api.POST("/api/files/attachments", {
        body: form as unknown as never,
        bodySerializer: (body: unknown) => body as BodyInit,
      });
      if (data) return data;
      throw new UploadRefusal(response.status, detailOf(error));
    },
    onSuccess: (attachment) => invalidate(queryClient, attachment.subject),
  });
}

/** One of the four `files.upload.refused.*` keys, so `t` takes it as the typed key it is. */
export type RefusalKey =
  | "files.upload.refused.tooLarge"
  | "files.upload.refused.unsupported"
  | "files.upload.refused.quota"
  | "files.upload.refused.duplicate"
  | "files.upload.refused.other";

/**
 * The `files.upload.refused.*` key for a refusal, from its status (requirement 6.3). A 413
 * is either "too large" or "quota reached"; the API says which in its message, so a mention
 * of the quota or of space left picks the quota wording, and a bare 413 the size one.
 */
export function refusalKey(refusal: UploadRefusal): RefusalKey {
  switch (refusal.status) {
    case 415:
      return "files.upload.refused.unsupported";
    case 409:
      return "files.upload.refused.duplicate";
    case 413:
      return /quota|space|left/i.test(refusal.message)
        ? "files.upload.refused.quota"
        : "files.upload.refused.tooLarge";
    default:
      return "files.upload.refused.other";
  }
}

export type AttachmentChange = {
  attachmentId: string;
  subject: string;
  body: ChangeAttachmentRequest;
};

/** Rename or re-kind an attachment in place (requirement 4.1); the file is left alone. */
export function useChangeAttachment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ attachmentId, body }: AttachmentChange): Promise<AttachmentResponse> => {
      const { data, error, response } = await api.PATCH("/api/files/attachments/{attachment_id}", {
        params: { path: { attachment_id: attachmentId } },
        body,
      });
      if (data) return data;
      throw new UploadRefusal(response.status, detailOf(error));
    },
    onSuccess: (_data, { subject }) => invalidate(queryClient, subject),
  });
}

export type Detachment = { attachmentId: string; subject: string };

/** Remove an attachment (requirement 6.5). A 404 is fine: it is gone either way. */
export function useDetach() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ attachmentId }: Detachment): Promise<void> => {
      const { error, response } = await api.DELETE("/api/files/attachments/{attachment_id}", {
        params: { path: { attachment_id: attachmentId } },
      });
      if (!response.ok && response.status !== 404) {
        throw new UploadRefusal(response.status, detailOf(error));
      }
    },
    onSuccess: (_data, { subject }) => invalidate(queryClient, subject),
  });
}

async function invalidate(
  queryClient: ReturnType<typeof useQueryClient>,
  subject: string,
): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: attachmentKeys.ofSubject(subject) });
}

/** What the API said it refused, whether a plain message or a list of field errors. */
function detailOf(error: unknown): string {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => String((entry as { msg?: unknown }).msg ?? ""))
      .filter(Boolean)
      .join("; ");
  }
  return "";
}
