import { ImagePlus } from "lucide-react";

import { useT } from "../../lib/lang";
import { useShell } from "../../ui/shell";
import { usePhotoChanges } from "./data";

/**
 * Add photos (UX §4 Photos room, §5 More → Photos): several at once, from a phone's camera or
 * library, or a computer's files. A label around a hidden file input, so the browser's own
 * picker opens, drawn as the shell's primary button (64 px in the wall's shell). The server
 * takes photos from any signed-in device and decodes HEIC itself.
 */
export function AddPhotosButton({ block = false }: { block?: boolean }) {
  const t = useT();
  const display = useShell() === "display";
  const { upload } = usePhotoChanges();
  return (
    <label
      className={`press flex cursor-pointer items-center justify-center gap-2 bg-ink font-semibold text-on-ink has-focus-visible:outline-[3px] has-focus-visible:outline-offset-2 has-focus-visible:outline-ink ${
        display
          ? "min-h-16 rounded-button-d px-7 text-d-body"
          : "min-h-12 rounded-button px-5 text-body"
      } ${block ? "w-full" : ""}`}
    >
      <ImagePlus aria-hidden="true" className={display ? "size-7" : "size-5"} />
      {upload.isPending ? t("photos.adding.action") : t("photos.add.action")}
      <input
        type="file"
        accept="image/*"
        multiple
        className="sr-only"
        disabled={upload.isPending}
        onChange={(event) => {
          const files = [...(event.target.files ?? [])];
          event.target.value = "";
          if (files.length) upload.mutate(files);
        }}
      />
    </label>
  );
}
