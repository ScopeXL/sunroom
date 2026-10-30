/**
 * The step library (UX §4 "Routine runner"): a picture for each routine step, chosen when the
 * routine is made, so a child who can't read yet can follow along. Keys are stored; the labels
 * (keys in lang/en.json, translated where they're shown) are what a parent sees when choosing.
 */
import {
  Apple,
  Backpack,
  Bath,
  BedDouble,
  BookOpen,
  Dog,
  Footprints,
  GlassWater,
  Glasses,
  Hand,
  Moon,
  Music,
  PencilLine,
  Pill,
  Shirt,
  ShowerHead,
  Smile,
  Sparkles,
  Sun,
  Toothbrush,
  Trash2,
  UtensilsCrossed,
  type LucideIcon,
} from "lucide-react";

import type { Key } from "../../lib/lang";

export const STEP_ICONS: Record<string, { label: Key; Icon: LucideIcon }> = {
  toothbrush: { label: "tasks.step_icon.toothbrush", Icon: Toothbrush },
  bed: { label: "tasks.step_icon.bed", Icon: BedDouble },
  book: { label: "tasks.step_icon.book", Icon: BookOpen },
  shirt: { label: "tasks.step_icon.shirt", Icon: Shirt },
  backpack: { label: "tasks.step_icon.backpack", Icon: Backpack },
  sun: { label: "tasks.step_icon.sun", Icon: Sun },
  moon: { label: "tasks.step_icon.moon", Icon: Moon },
  bath: { label: "tasks.step_icon.bath", Icon: Bath },
  shower: { label: "tasks.step_icon.shower", Icon: ShowerHead },
  plate: { label: "tasks.step_icon.plate", Icon: UtensilsCrossed },
  dog: { label: "tasks.step_icon.dog", Icon: Dog },
  water: { label: "tasks.step_icon.water", Icon: GlassWater },
  snack: { label: "tasks.step_icon.snack", Icon: Apple },
  shoes: { label: "tasks.step_icon.shoes", Icon: Footprints },
  hands: { label: "tasks.step_icon.hands", Icon: Hand },
  glasses: { label: "tasks.step_icon.glasses", Icon: Glasses },
  medicine: { label: "tasks.step_icon.medicine", Icon: Pill },
  tidy: { label: "tasks.step_icon.tidy", Icon: Sparkles },
  trash: { label: "tasks.step_icon.trash", Icon: Trash2 },
  homework: { label: "tasks.step_icon.homework", Icon: PencilLine },
  music: { label: "tasks.step_icon.music", Icon: Music },
  smile: { label: "tasks.step_icon.smile", Icon: Smile },
};

export function stepIcon(key: string | null | undefined): LucideIcon {
  return (key ? STEP_ICONS[key]?.Icon : undefined) ?? Smile;
}
