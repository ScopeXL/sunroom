import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Eye, EyeOff, Images, Play, Settings, X } from "lucide-react";
import { useState } from "react";

import { qk } from "../../api/keys";
import { askForPin } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { RoomHeader } from "../../shell/roomHeader";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Pop } from "../../ui/Pop";
import { QrCode } from "../../ui/QrCode";
import { AddPhotosButton } from "./AddPhotosButton";
import {
  fromLibrary,
  useLibraries,
  useLibrary,
  useManifest,
  usePhotoChanges,
  type LibraryPhoto,
} from "./data";
import { startSaver } from "./start";

/** "124 photos". */
export function photosCount(count: number): string {
  return count === 1 ? "1 photo" : `${String(count)} photos`;
}

/**
 * The Photos room in the wall's shell (UX §4): how many there are, Start screensaver, its
 * Settings (behind the PIN), and the photos newest first. The wall screen shows a code for
 * adding photos from a phone; a computer adds them itself with Add photos (ADR 0028). A photo
 * opens full screen with Previous, Next and Hide from screensaver: this room can hide photos
 * but never removes them (phones do, with Undo). A photo library's says where it's from.
 */
export function PhotosRoom() {
  const navigate = useNavigate();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const kiosk = session?.device_kind === "kiosk";
  const { data: manifest } = useManifest();
  const library = useLibrary();
  const photos = library.data?.pages.flatMap((page) => page.photos) ?? [];
  const [open, setOpen] = useState<number | null>(null);
  const shown = manifest?.photos.length ?? 0;
  const address = `${window.location.origin}/photos`;
  // A paired screen adds no photos itself (it has no files): a device does, from this code.
  const fromADevice = (
    <div className="flex items-center gap-6 rounded-panel border border-line bg-surface p-5 text-left">
      <QrCode value={address} label="A code that opens Photos on a device" className="size-32" />
      <p className="text-d-body">Add photos from a device: open Sunroom there, then Photos.</p>
    </div>
  );
  return (
    <section aria-label="Photos" className="flex min-h-0 flex-1 flex-col">
      <RoomHeader
        title="Photos"
        controls={
          <div className="ml-auto flex flex-wrap gap-3">
            <Button
              variant="secondary"
              onClick={() => {
                void (async () => {
                  if (!session?.is_parent && !(await askForPin())) return;
                  await navigate({ to: "/settings/$page", params: { page: "screensaver" } });
                })();
              }}
            >
              <Settings aria-hidden="true" className="size-7" />
              Settings
            </Button>
            <Button
              variant="secondary"
              onClick={() => {
                startSaver();
              }}
            >
              <Play aria-hidden="true" className="size-7" />
              Start Screensaver
            </Button>
            {kiosk ? null : <AddPhotosButton />}
          </div>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-6" tabIndex={0}>
        {library.isSuccess && photos.length === 0 ? (
          <EmptyState
            icon={Images}
            line="No photos yet"
            note="Photos added from any device show here and on the screensaver."
            // A paired screen has no file picker: its QR code stands where the button would.
            action={kiosk ? fromADevice : <AddPhotosButton />}
          />
        ) : (
          <>
            {kiosk ? <div className="mb-6">{fromADevice}</div> : null}
            {/* How many the screensaver shows, over the grid: the header has no second line. */}
            {library.isSuccess ? (
              <p className="mb-3 text-d-secondary font-semibold text-ink-soft">
                <Pop value={photosCount(shown)} className="inline-block" />
              </p>
            ) : null}
            <ul
              aria-label="Photos"
              className="grid grid-cols-[repeat(auto-fill,minmax(12.5rem,1fr))] gap-3"
            >
              {photos.map((photo, index) => (
                <li key={photo.id}>
                  <button
                    type="button"
                    aria-label={photo.hidden ? "A photo, hidden from the screensaver" : "A photo"}
                    onClick={() => {
                      setOpen(index);
                    }}
                    className="press relative block aspect-square w-full overflow-hidden rounded-chip-d bg-line"
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
                        className="absolute top-2 right-2 size-7 rounded-full bg-surface p-1"
                      />
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
        {library.hasNextPage ? (
          <div className="mt-6">
            <Button
              variant="secondary"
              pending={library.isFetchingNextPage}
              onClick={() => {
                void library.fetchNextPage();
              }}
            >
              Show More
            </Button>
          </div>
        ) : null}
      </div>
      {open !== null && photos[open] ? (
        <Viewer
          photos={photos}
          index={open}
          parent={session?.is_parent ?? false}
          onIndex={setOpen}
          onClose={() => {
            setOpen(null);
          }}
        />
      ) : null}
    </section>
  );
}

/** One photo full screen, with Previous, Next, Hide from screensaver and Close; a photo library's
 * says where it's from ("From Immich"). */
function Viewer({
  photos,
  index,
  parent,
  onIndex,
  onClose,
}: {
  photos: LibraryPhoto[];
  index: number;
  /** The libraries' names are a parent's to read (the PIN's grant on the wall). */
  parent: boolean;
  onIndex: (index: number) => void;
  onClose: () => void;
}) {
  const { hide } = usePhotoChanges();
  const { data: libraries = [] } = useLibraries({ enabled: parent });
  const photo = photos[index];
  if (!photo) return null;
  const from = fromLibrary(photo, libraries);
  const step = (by: number) => {
    onIndex((index + by + photos.length) % photos.length);
  };
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Photo"
      className="fixed inset-0 z-[45] flex flex-col bg-wall"
    >
      <img src={photo.url} alt="" className="min-h-0 flex-1 object-contain" />
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface px-6 py-4">
        <div className="flex gap-3">
          <Button
            variant="secondary"
            disabled={photos.length < 2}
            onClick={() => {
              step(-1);
            }}
          >
            <ChevronLeft aria-hidden="true" className="size-7" />
            Previous
          </Button>
          <Button
            variant="secondary"
            disabled={photos.length < 2}
            onClick={() => {
              step(1);
            }}
          >
            Next
            <ChevronRight aria-hidden="true" className="size-7" />
          </Button>
        </div>
        {from ? <p className="text-d-secondary font-semibold text-ink-soft">{from}</p> : null}
        <div className="flex gap-3">
          <Button
            variant="secondary"
            pending={hide.isPending}
            onClick={() => {
              hide.mutate({ id: photo.id, hidden: !photo.hidden });
            }}
          >
            {photo.hidden ? (
              <Eye aria-hidden="true" className="size-7" />
            ) : (
              <EyeOff aria-hidden="true" className="size-7" />
            )}
            {photo.hidden ? "Show on the Screensaver" : "Hide from Screensaver"}
          </Button>
          <Button variant="secondary" onClick={onClose}>
            <X aria-hidden="true" className="size-7" />
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}
