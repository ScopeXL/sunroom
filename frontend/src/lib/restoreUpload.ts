/**
 * Sending a backup to restore (Settings → Backup → Restore from a File, ADR 0034). The file
 * itself is the body, as a photo's is, so the generated client isn't used; and it goes over
 * XMLHttpRequest, because a zip with every photo can take minutes from a phone and only XHR
 * says how far it got.
 */
import { ApiError, refusal } from "../api/client";
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
      const key = "settings.backup.restore.not_sent.error";
      reject(new ApiError(0, "aborted", t(key), false, [], null, key));
    };
    request.onerror = () => {
      const key = "settings.backup.restore.unreachable.error";
      reject(new ApiError(0, "offline", t(key), false, [], null, key));
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
      if (request.status === 413 && !(payload as { error?: unknown } | null)?.error) {
        // A proxy's own 413 page, not Sunroom's: the file never reached the server.
        const key = "settings.backup.restore.too_big.error";
        reject(new ApiError(413, "too_large", t(key), false, [], null, key));
        return;
      }
      reject(refusal(request.status, payload, "settings.backup.restore.send_failed.error"));
    };
    request.send(file);
  });
}
