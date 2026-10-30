import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";

import { useT } from "../../lib/lang";
import { Button } from "../../ui/Button";
import { zoomIn, zoomOut } from "./hours";

/**
 * The Hours grid's zoom, on the grid itself (UX §4, ADR 0030): Fit the day · Zoom out · Zoom in
 * (the whole day first since ADR 0032, as the owner reads it) at the grid's bottom corner, like
 * a map's, outside the scroller so it stays put while the hours scroll under it. Each tap is
 * half again, as far as the grid allows; Fit shows the whole day again. A row, not a stack: fitted, it covers the last column's last two hours and no
 * more. It belongs to the thing it zooms, and the header has no room for three more buttons.
 */
export function ZoomControl({
  zoom,
  max,
  onZoom,
}: {
  /** 1 fits the whole day (features/calendar/hours). */
  zoom: number;
  /** As far in as the grid goes at its height and this text size. */
  max: number;
  onZoom: (zoom: number) => void;
}) {
  const t = useT();
  const fitted = zoom <= 1;
  return (
    // Three buttons, not a choice: one control to the tap-target check, like a segmented.
    <div
      role="group"
      aria-label={t("calendar.zoom.aria")}
      data-segmented=""
      className="absolute right-6 bottom-4 z-30 flex gap-2 rounded-panel border-2 border-line bg-surface p-2"
    >
      <Button
        variant="secondary"
        icon
        aria-label={t("calendar.zoom.fit.aria")}
        disabled={fitted}
        onClick={() => {
          onZoom(1);
        }}
      >
        <Maximize2 aria-hidden="true" className="size-8" />
      </Button>
      <Button
        variant="secondary"
        icon
        aria-label={t("calendar.zoom.out.aria")}
        disabled={fitted}
        onClick={() => {
          onZoom(zoomOut(zoom));
        }}
      >
        <ZoomOut aria-hidden="true" className="size-8" />
      </Button>
      <Button
        variant="secondary"
        icon
        aria-label={t("calendar.zoom.in.aria")}
        disabled={zoom >= max}
        onClick={() => {
          onZoom(zoomIn(zoom, max));
        }}
      >
        <ZoomIn aria-hidden="true" className="size-8" />
      </Button>
    </div>
  );
}
