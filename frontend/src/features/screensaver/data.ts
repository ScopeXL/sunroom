/**
 * Photos and the screensaver's data (PLAN §11.1 Photos, §11.3 screensaver): what the screensaver
 * shows (its manifest and settings), the household's photos a page at a time, the photo
 * sources and photo libraries (ADR 0036), and every change, each with the toast UX §2 names and
 * Undo where it applies. Removing and hiding photos, and the libraries, are a parent's (the wall
 * asks for the PIN).
 */
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { api, errorMessage, unwrap } from "../../api/client";
import type { components } from "../../api/schema";
import { t } from "../../lib/lang";
import { asParent } from "../../lib/parent";
import { showToast } from "../../lib/toast";
import { uploadPicture } from "../../lib/upload";

export type Manifest = components["schemas"]["ManifestOut"];
export type SaverPhoto = components["schemas"]["ManifestPhoto"];
export type PhotoSource = components["schemas"]["SourceOut"];
export type LibraryPhoto = components["schemas"]["PhotoOut"];
export type PhotoLibrary = components["schemas"]["LibraryOut"];
export type LibraryKind = components["schemas"]["LibraryKindOut"];
export type LibraryChoices = components["schemas"]["LibraryChoicesOut"];
export type LibraryChoice = components["schemas"]["LibraryChoiceOut"];
export type LibraryPicks = components["schemas"]["LibraryPicks"];
export type LibraryIn = components["schemas"]["LibraryIn"];
export type LibraryPatch = components["schemas"]["LibraryPatch"];

export const saverKeys = {
  manifest: () => ["screensaver", "manifest"] as const,
  sources: () => ["screensaver", "sources"] as const,
  library: () => ["photos", "library"] as const,
  libraryKinds: () => ["screensaver", "library-kinds"] as const,
  libraries: () => ["screensaver", "libraries"] as const,
  choices: (id: string) => ["screensaver", "libraries", id, "choices"] as const,
};

/** While a library is bringing photos in, its line counts them: look again every 5 s. */
const BUSY_REFETCH_MS = 5000;

export function useManifest({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: saverKeys.manifest(),
    queryFn: async () => unwrap(await api.GET("/api/screensaver/manifest")),
    staleTime: 5 * 60_000,
    enabled,
  });
}

/** The household's photos, newest first, a page at a time. */
export function useLibrary() {
  return useInfiniteQuery({
    queryKey: saverKeys.library(),
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/photos", {
          params: { query: { kind: "library", ...(pageParam ? { cursor: pageParam } : {}) } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
}

export function useSources({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: saverKeys.sources(),
    queryFn: async () => unwrap(await api.GET("/api/screensaver/sources")),
    enabled,
  });
}

const LIBRARY_KEY = "source:";

/**
 * Where a photo came from, for the viewer and the phone's sheet (ADR 0036): "From Immich" for a
 * photo library's (its name, from the libraries a parent's device may read), "From a photo
 * library" when the name isn't known here; null for an upload or the inbox's.
 */
export function fromLibrary(
  photo: { source_key: string },
  libraries: PhotoLibrary[],
): string | null {
  if (!photo.source_key.startsWith(LIBRARY_KEY)) return null;
  const id = photo.source_key.slice(LIBRARY_KEY.length);
  const library = libraries.find((each) => each.id === id);
  return library ? t("photos.from.library", { name: library.name }) : t("photos.from.unknown");
}

export function useLibraryKinds({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: saverKeys.libraryKinds(),
    queryFn: async () => unwrap(await api.GET("/api/screensaver/library-kinds")),
    staleTime: Infinity,
    enabled,
  });
}

/** The photo libraries (a parent's, so only where the device may ask). */
export function useLibraries({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: saverKeys.libraries(),
    queryFn: async () => unwrap(await api.GET("/api/screensaver/libraries")),
    enabled,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((library) => library.checking || library.pending > 0)
        ? BUSY_REFETCH_MS
        : false,
  });
}

/** The people, albums and tags a library offers (the server fetches them again when they're
 * over an hour old). */
export function useLibraryChoices(id: string | null) {
  return useQuery({
    queryKey: saverKeys.choices(id ?? ""),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/screensaver/libraries/{source_id}/choices", {
          params: { path: { source_id: id ?? "" } },
        }),
      ),
    enabled: id !== null,
  });
}

async function refresh(queryClient: QueryClient): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["photos"] }),
    queryClient.invalidateQueries({ queryKey: ["screensaver"] }),
  ]);
}

export function usePhotoChanges() {
  const queryClient = useQueryClient();

  /** Several at once, one after another (memory stays flat on a Pi). */
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      let added = 0;
      let failed: string | null = null;
      for (const file of files) {
        try {
          await uploadPicture<LibraryPhoto>("/api/photos", "POST", file, null);
          added += 1;
        } catch (error) {
          failed = errorMessage(error);
        }
      }
      return { added, failed };
    },
    onSuccess: async ({ added, failed }) => {
      await refresh(queryClient);
      if (added) showToast(t("photos.added.toast", { n: added }));
      if (failed) showToast(added ? t("photos.upload.partly.toast", { why: failed }) : failed);
    },
  });

  const restore = async (id: string) => {
    await asParent(async () =>
      unwrap(
        await api.POST("/api/photos/{photo_id}/restore", { params: { path: { photo_id: id } } }),
      ),
    );
    await refresh(queryClient);
  };

  const remove = useMutation({
    mutationFn: async (id: string) => {
      await asParent(async () => {
        unwrap(await api.DELETE("/api/photos/{photo_id}", { params: { path: { photo_id: id } } }));
      });
      return id;
    },
    onSuccess: async (id) => {
      await refresh(queryClient);
      showToast(t("photos.removed.toast"), {
        label: t("app.action.undo"),
        onAction: () => {
          void restore(id).catch(() => {
            showToast(t("app.undo.error"));
          });
        },
      });
    },
  });

  const hide = useMutation({
    mutationFn: async ({ id, hidden }: { id: string; hidden: boolean }) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/photos/{photo_id}/hide", {
            params: { path: { photo_id: id }, query: { hidden } },
          }),
        ),
      ),
    onSuccess: async (photo) => {
      await refresh(queryClient);
      showToast(photo.hidden ? t("photos.hidden.toast") : t("photos.shown.toast"), {
        label: t("app.action.undo"),
        onAction: () => {
          hide.mutate({ id: photo.id, hidden: !photo.hidden });
        },
      });
    },
  });

  /** Start screensaver on the wall, from a phone (PLAN §11.1 kiosk/command). */
  const startOnWall = useMutation({
    mutationFn: async () =>
      asParent(async () => {
        unwrap(await api.POST("/api/kiosk/command", { body: { command: "screensaver" } }));
      }),
    onSuccess: () => {
      showToast(t("photos.started.toast"));
    },
  });

  const scan = useMutation({
    mutationFn: async (id: string) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/screensaver/sources/{source_id}/scan", {
            params: { path: { source_id: id } },
          }),
        ),
      ),
    onSuccess: async (result) => {
      await refresh(queryClient);
      showToast(
        result.imported
          ? t("photos.added.toast", { n: result.imported })
          : t("photos.scan.nothing.toast"),
      );
    },
  });

  const setSource = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) =>
      asParent(async () =>
        unwrap(
          await api.PATCH("/api/screensaver/sources/{source_id}", {
            params: { path: { source_id: id } },
            body: { enabled },
          }),
        ),
      ),
    onSuccess: async (source) => {
      await refresh(queryClient);
      showToast(
        source.enabled
          ? t("photos.source.on.toast", { name: source.label })
          : t("photos.source.off.toast", { name: source.label }),
      );
    },
  });

  /** Connect a library: its refusal is shown in the panel, under the key, not as a toast. */
  const addLibrary = useMutation({
    mutationFn: async (body: LibraryIn) =>
      asParent(async () => unwrap(await api.POST("/api/screensaver/libraries", { body }))),
    onSuccess: async () => {
      await refresh(queryClient);
    },
  });

  /** Picks, Keep up to, the switch: saved as they change (the panel shows "Saved"). */
  const patchLibrary = useMutation({
    mutationFn: async ({ id, change }: { id: string; change: LibraryPatch }) =>
      asParent(async () =>
        unwrap(
          await api.PATCH("/api/screensaver/libraries/{source_id}", {
            params: { path: { source_id: id } },
            body: change,
          }),
        ),
      ),
    onSuccess: async () => {
      await refresh(queryClient);
    },
  });

  const reconnectLibrary = useMutation({
    mutationFn: async ({ id, apiKey, url }: { id: string; apiKey: string; url?: string }) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/screensaver/libraries/{source_id}/reconnect", {
            params: { path: { source_id: id } },
            body: { api_key: apiKey, ...(url ? { url } : {}) },
          }),
        ),
      ),
    onSuccess: async (library) => {
      await refresh(queryClient);
      showToast(t("photos.library.reconnected.toast", { name: library.name }));
    },
  });

  /** No Undo: its key is gone with it (the panel asked first). */
  const removeLibrary = useMutation({
    mutationFn: async (library: PhotoLibrary) => {
      await asParent(async () => {
        unwrap(
          await api.DELETE("/api/screensaver/libraries/{source_id}", {
            params: { path: { source_id: library.id } },
          }),
        );
      });
      return library;
    },
    onSuccess: async (library) => {
      await refresh(queryClient);
      showToast(t("photos.library.removed.toast", { name: library.name }));
    },
  });

  /** Check Now: the library's line does the talking after the toast. */
  const checkLibrary = useMutation({
    mutationFn: async (library: PhotoLibrary) =>
      asParent(async () =>
        unwrap(
          await api.POST("/api/screensaver/libraries/{source_id}/scan", {
            params: { path: { source_id: library.id } },
          }),
        ),
      ),
    onSuccess: async (library) => {
      await refresh(queryClient);
      showToast(t("photos.library.checking.toast", { name: library.name }));
    },
  });

  /** Refresh Choices: the people, albums and tags fetched again now. */
  const refreshChoices = useMutation({
    mutationFn: async (id: string) =>
      asParent(async () =>
        unwrap(
          await api.GET("/api/screensaver/libraries/{source_id}/choices", {
            params: { path: { source_id: id }, query: { refresh: true } },
          }),
        ),
      ),
    onSuccess: (choices, id) => {
      queryClient.setQueryData(saverKeys.choices(id), choices);
    },
  });

  return {
    upload,
    remove,
    hide,
    startOnWall,
    scan,
    setSource,
    addLibrary,
    patchLibrary,
    reconnectLibrary,
    removeLibrary,
    checkLibrary,
    refreshChoices,
  };
}
