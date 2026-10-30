/**
 * Picture uploads: the one place the app calls the API without the generated client, because the
 * body is the image itself (the server reads raw bytes, so OpenAPI describes no body). Shrunk on
 * the phone first when asked (an avatar); the server re-encodes everything as WebP without
 * metadata (ADR 0009), after reading when a photo was taken.
 */
import { ApiError, refusal } from "../api/client";
import { t } from "./lang";

const SERVER_LIMIT = 15 * 1024 * 1024;
const LIBRARY_SIDE = 2560;

/** `maxSide`: shrink to this first; null sends the photo as it is (so the server can read when
 * it was taken), unless it's over the server's 15 MB. */
export async function uploadPicture<T>(
  path: string,
  method: "POST" | "PUT",
  file: File,
  maxSide: number | null,
): Promise<T> {
  let body: Blob = file;
  if (maxSide !== null || file.size > SERVER_LIMIT) {
    try {
      body = await shrink(file, maxSide ?? LIBRARY_SIDE);
    } catch {
      // The browser couldn't decode it (HEIC on some phones): the server reads the original.
    }
  }
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      body,
      credentials: "same-origin",
      headers: { "Content-Type": body.type || "image/jpeg", "X-Sunroom": "1" },
    });
  } catch {
    const key = "app.upload.offline.error";
    throw new ApiError(0, "offline", t(key), false, [], null, key);
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw refusal(response.status, payload, "app.upload.failed.error");
  return payload as T;
}

async function shrink(file: File, maxSide: number): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("no canvas");
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("couldn't encode"));
      },
      "image/jpeg",
      0.88,
    );
  });
}
