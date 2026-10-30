import { Globe } from "lucide-react";
import { useState } from "react";

import {
  completeLanguages,
  languageName,
  setLanguage,
  useLanguage,
  useT,
  type LanguageCode,
  type PageLanguage,
} from "../../lib/lang";
import { Button } from "../../ui/Button";
import { Chip, ChipRow } from "../../ui/Chip";
import { Segmented } from "../../ui/Segmented";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { ChoiceList } from "../../ui/ValueRow";

/**
 * The quiet language button at the foot of the pages before setup and pairing (Welcome to
 * Sunroom, Set Up Sunroom, Pair This Screen; ADR 0043): a globe and the page's language, which
 * opens Choose a Language. A choice switches the page at once and is setup's household step's
 * language; nothing is saved before that step.
 */
export function LanguageButton() {
  const t = useT();
  const language = useLanguage();
  const display = useShell() === "display";
  const [open, setOpen] = useState(false);
  const name = languageName(language);
  const close = () => {
    setOpen(false);
  };
  return (
    <>
      <Button
        variant="quiet"
        aria-label={t("app.language.aria", { name })}
        onClick={() => {
          setOpen(true);
        }}
      >
        <Globe aria-hidden="true" className={display ? "size-7" : "size-5"} />
        {name}
      </Button>
      <Sheet
        open={open}
        title={t("app.language.title")}
        onClose={close}
        footer={
          <Button block variant="secondary" onClick={close}>
            {t("app.action.done")}
          </Button>
        }
      >
        <ChoiceList<PageLanguage>
          label={t("app.language.title")}
          choices={completeLanguages()}
          value={language}
          onChange={(code) => {
            void setLanguage(code);
          }}
        />
      </Sheet>
    </>
  );
}

/** The languages a family can pick, by their own names, one chosen: side by side up to six,
 * else chips (Settings → Household, setup's household step). */
export function LanguagePicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (code: LanguageCode) => void;
}) {
  const languages = completeLanguages();
  if (languages.length <= 6) {
    return (
      <Segmented
        label={label}
        value={value as LanguageCode}
        options={languages}
        onChange={onChange}
      />
    );
  }
  return (
    <ChipRow label={label}>
      {languages.map((language) => (
        <Chip
          key={language.value}
          on={language.value === value}
          onClick={() => {
            onChange(language.value);
          }}
        >
          {language.label}
        </Chip>
      ))}
    </ChipRow>
  );
}
