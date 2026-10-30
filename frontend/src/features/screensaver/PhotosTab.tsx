import { useQuery } from "@tanstack/react-query";
import { EyeOff, Images, Play } from "lucide-react";
import { useState } from "react";

import { qk } from "../../api/keys";
import { useT } from "../../lib/lang";
import { fetchSession } from "../../lib/session";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Screen } from "../../ui/Screen";
import { Sheet } from "../../ui/Sheet";
import { AddPhotosButton } from "./AddPhotosButton";
import {
  fromLibrary,
  useLibraries,
  useLibrary,
  useManifest,
  usePhotoChanges,
  type LibraryPhoto,
} from "./data";

/**
 * Photos on a phone (UX §5 "More"): where photos are added, from the camera or the library,
 * several at once, and removed (with Undo); a photo library's is hidden instead, since the
 * library is where it's changed (ADR 0036). A parent can start the screensaver on the wall
 * screen from here.
 */
export function PhotosTab() {
  const t = useT();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const { data: manifest } = useManifest();
  const library = useLibrary();
  const changes = usePhotoChanges();
  const photos = library.data?.pages.flatMap((page) => page.photos) ?? [];
  const [open, setOpen] = useState<LibraryPhoto | null>(null);
  const { data: libraries = [] } = useLibraries({ enabled: session?.is_parent ?? false });
  const from = open ? fromLibrary(open, libraries) : null;
  return (
    <Screen title={t("photos.room.title")} back="/more" actions={<AddPhotosButton block />}>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <p className="text-body text-ink-soft">
          {library.isSuccess ? t("photos.tab.on_saver", { n: manifest?.photos.length ?? 0 }) : ""}
        </p>
        {session?.is_parent ? (
          <Button
            variant="secondary"
            pending={changes.startOnWall.isPending}
            onClick={() => {
              changes.startOnWall.mutate();
            }}
          >
            <Play aria-hidden="true" className="size-5" />
            {t("photos.start.action")}
          </Button>
        ) : null}
      </div>
      {library.isSuccess && photos.length === 0 ? (
        <EmptyState icon={Images} line={t("photos.empty")} note={t("photos.empty_note")} />
      ) : (
        <ul aria-label={t("photos.room.title")} className="grid grid-cols-3 gap-2">
          {photos.map((photo) => (
            <li key={photo.id}>
              <button
                type="button"
                aria-label={photo.hidden ? t("photos.photo.hidden.aria") : t("photos.photo.aria")}
                onClick={() => {
                  setOpen(photo);
                }}
                className="press relative block aspect-square w-full overflow-hidden rounded-sm bg-line"
              >
                <img
                  src={photo.thumb_url}
                  alt=""
                  loading="lazy"
                  className={`size-full object-cover ${photo.hidden ? "opacity-40" : ""}`}
                />
                {photo.hidden ? (
                  <EyeOff
                    aria-hidden="true"
                    className="absolute top-1 right-1 size-6 rounded-full bg-surface p-1"
                  />
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
      {library.hasNextPage ? (
        <div className="mt-5">
          <Button
            variant="secondary"
            block
            pending={library.isFetchingNextPage}
            onClick={() => {
              void library.fetchNextPage();
            }}
          >
            {t("photos.more.action")}
          </Button>
        </div>
      ) : null}
      <Sheet
        open={open !== null}
        title={t("photos.photo.title")}
        onClose={() => {
          setOpen(null);
        }}
        footer={
          open && session?.is_parent ? (
            <div className="flex flex-wrap gap-3">
              <Button
                variant="secondary"
                onClick={() => {
                  changes.hide.mutate({ id: open.id, hidden: !open.hidden });
                  setOpen(null);
                }}
              >
                {open.hidden
                  ? t("photos.show_on_saver.action")
                  : t("photos.hide_from_saver.action")}
              </Button>
              {from ? null : (
                <Button
                  variant="quiet-danger"
                  onClick={() => {
                    changes.remove.mutate(open.id);
                    setOpen(null);
                  }}
                >
                  {t("app.action.remove")}
                </Button>
              )}
            </div>
          ) : null
        }
      >
        {open ? <img src={open.url} alt="" className="w-full rounded-chip object-contain" /> : null}
        {from ? <p className="mt-3 text-secondary font-semibold text-ink-soft">{from}</p> : null}
      </Sheet>
    </Screen>
  );
}
