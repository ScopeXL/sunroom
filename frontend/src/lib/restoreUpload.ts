/**
 * Sending a backup to restore (Settings → Backup → Restore from a File, ADR 0034). The file
 * itself is the body, as a photo's is, so the generated client isn't used; and it goes over
 * XMLHttpRequest, because a zip with every photo can take minutes from a phone and only XHR
 * says how far it got.
 */
import { ApiError } from "../api/client";
import type { components } from "../api/schema";
import { t } from "./lang";

export type RestoreSummary = components["schemas"]["RestoreSummaryOut"];

/** Rejects with an ApiError in the server's words; code "aborted" when `request.abort()` ran. */
export function uploadBackup(
  file: File,
  onProgress: (fraction: number) => void,
  request: XMLHttpRequest = new XMLHttpRequest(),
): Promise<RestoreSummary> {
  return new Promise((resolve, reject) => {
    request.open("POST", "/api/admin/restore");
    request.setRequestHeader("X-Sunroom", "1");
    request.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    request.onabort = () => {
      reject(new ApiError(0, "aborted", "Not sent."));
    };
    request.onerror = () => {
      reject(new ApiError(0, "offline", "Not sent — the server can't be reached. Try again."));
    };
    request.onload = () => {
      let payload: unknown;
      try {
        payload = JSON.parse(request.responseText) as unknown;
      } catch {
        payload = null; // a proxy's page, not Sunroom's answer
      }
      if (request.status >= 200 && request.status < 300 && payload !== null) {
        resolve(payload as RestoreSummary);
        return;
      }
      const error = (
        payload as { error?: { code?: string; message?: string; pin?: boolean } } | null
      )?.error;
      if (request.status === 413 && !error) {
        // A proxy's own 413 page, not Sunroom's: the file never reached the server.
        reject(new ApiError(413, "too_large", t("settings.backup.restore.too_big.error")));
        return;
      }
      reject(
        new ApiError(
          request.status,
          error?.code ?? "error",
          error?.message ?? "That file couldn't be sent. Try again.",
          error?.pin === true,
        ),
      );
    };
    request.send(file);
  });
}
