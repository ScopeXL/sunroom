import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";

import { ApiError, api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { copyText } from "../../lib/copy";
import { asParent } from "../../lib/parent";
import { fetchSession } from "../../lib/session";
import { showToast } from "../../lib/toast";
import { Button, ButtonLink } from "../../ui/Button";
import { DiscordMark } from "../../ui/DiscordMark";
import { useFieldLabel } from "../../ui/Field";
import { ListRowAnchor } from "../../ui/ListRow";
import { QrCode } from "../../ui/QrCode";
import { Segmented } from "../../ui/Segmented";
import { Sheet } from "../../ui/Sheet";
import { useShell } from "../../ui/shell";
import { TextField } from "../../ui/TextField";
import { Group, Row, Text } from "./parts";
import {
  ADDRESSES,
  DISCORD_URL,
  PATREON_URL,
  feedbackUrl,
  installWords,
  type FeedbackKind,
} from "./support";

const DISCORD_NOTE = "Join the Sunroom Discord for help, ideas and what's new.";

/** "patreon.com/sunroom" for "https://www.patreon.com/sunroom": what a row shows of a link. */
function shortLink(url: string): string {
  return url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
}

/**
 * Settings → Support Sunroom (UX §4, ADR 0034): what Sunroom is (free, open source, not for
 * profit) and how to support it: the Sunroom Discord first (ADR 0042), then the owner's links
 * and addresses in `support.ts` (an empty one isn't drawn), then Send Feedback. A paired screen opens no other website, so it shows a
 * QR code where a device has a link, and no Copy (there is nowhere to paste on a screen).
 */
export function SupportPage() {
  const display = useShell() === "display";
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const kiosk = session?.device_kind === "kiosk";
  const [feedback, setFeedback] = useState(false);
  const { data: diagnostics } = useQuery({
    queryKey: qk.diagnostics(),
    queryFn: () => asParent(async () => unwrap(await api.GET("/api/admin/diagnostics"))),
  });
  // This Sunroom sends feedback itself, unless the server has that off (ADR 0042).
  const direct = diagnostics?.feedback ?? true;
  const rows = [
    kiosk ? (
      <Row key="discord" label="Discord" hint={DISCORD_NOTE}>
        <DiscordMark className="size-8 shrink-0 text-ink-soft" />
        <Text soft>{shortLink(DISCORD_URL)}</Text>
        <QrCode
          value={DISCORD_URL}
          label="A code that opens the Sunroom Discord"
          className="size-40"
        />
      </Row>
    ) : (
      <ListRowAnchor
        key="discord"
        label="Open Discord"
        leading={<DiscordMark className={`shrink-0 ${display ? "size-8" : "size-6"}`} />}
        title="Discord"
        subtitle={DISCORD_NOTE}
        href={DISCORD_URL}
        target="_blank"
        rel="noreferrer noopener"
      />
    ),
    PATREON_URL ? (
      kiosk ? (
        <Row key="patreon" label="Patreon">
          <Text soft>{shortLink(PATREON_URL)}</Text>
          <QrCode value={PATREON_URL} label="A code that opens Patreon" className="size-40" />
        </Row>
      ) : (
        <ListRowAnchor
          key="patreon"
          label="Open Patreon"
          title="Patreon"
          subtitle={shortLink(PATREON_URL)}
          href={PATREON_URL}
          target="_blank"
          rel="noreferrer noopener"
        />
      )
    ) : null,
    ...ADDRESSES.filter((entry) => entry.address).map((entry) => (
      <div
        key={entry.name}
        className={`flex flex-wrap items-center gap-x-6 gap-y-3 ${display ? "py-5" : "py-4"}`}
      >
        <div className="flex min-w-0 flex-1 basis-60 flex-col gap-1">
          <span className={display ? "text-d-body font-semibold" : "text-body font-semibold"}>
            {entry.name}
          </span>
          <span
            className={`font-mono break-all text-ink-soft select-all ${
              display ? "text-d-secondary" : "text-secondary"
            }`}
          >
            {entry.address}
          </span>
          {kiosk ? null : (
            <div className="mt-2">
              <Button
                variant="quiet"
                onClick={() => {
                  void copyText(entry.address).then((copied) => {
                    showToast(
                      copied
                        ? `Copied the ${entry.name} address`
                        : "Couldn't copy it here. Hold the address to select it.",
                    );
                  });
                }}
              >
                Copy
              </Button>
            </div>
          )}
        </div>
        <QrCode
          value={entry.address}
          label={`A code of the ${entry.name} address`}
          className="size-40 shrink-0"
        />
      </div>
    )),
  ].filter(Boolean);
  return (
    <>
      <Group
        title="Support Sunroom"
        mark=" 💛"
        note="Sunroom is free and open source, and not for profit: no ads, no accounts, no subscription. If it has earned a place on your wall, a donation helps it keep growing."
      >
        {rows.length ? rows : null}
      </Group>
      <Group
        title="Feedback"
        note={
          direct
            ? "Found a problem, or have an idea? It goes straight to the people who make Sunroom. No account needed, and nothing from your calendar is sent."
            : "Found a problem, or have an idea? Feedback goes to Sunroom's page on GitHub, where everyone can see it. It needs a GitHub account; nothing from your calendar is sent."
        }
      >
        <div className={display ? "py-5" : "py-4"}>
          <Button
            variant="secondary"
            onClick={() => {
              setFeedback(true);
            }}
          >
            Send Feedback
          </Button>
        </div>
      </Group>
      <FeedbackSheet
        open={feedback}
        kiosk={kiosk}
        direct={direct}
        version={diagnostics?.version ?? __APP_VERSION__}
        install={installWords(diagnostics?.install_kind)}
        onClose={() => {
          setFeedback(false);
        }}
      />
    </>
  );
}

/**
 * Send Feedback (ADR 0034, 0042): the kind, a title, the words and how to reach you, which this
 * Sunroom posts to the people who make it, with its version and install and nothing else: no
 * account, from any device and from the screen itself (the words on its keyboard). A server with
 * feedback off opens GitHub's new-issue page instead, filled in, where the person signs in and
 * taps Submit (the page can't post to GitHub itself: its CSP talks to Sunroom only, and the image
 * holds no token); on a paired screen as a QR code of the link with the title only, so the code
 * stays readable.
 */
function FeedbackSheet({
  open,
  kiosk,
  direct,
  version,
  install,
  onClose,
}: {
  open: boolean;
  kiosk: boolean;
  direct: boolean;
  version: string;
  install: string | null;
  onClose: () => void;
}) {
  const display = useShell() === "display";
  const labelClass = useFieldLabel();
  const wordsId = useId();
  const [kind, setKind] = useState<FeedbackKind>("problem");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [contact, setContact] = useState("");
  // The server said it has feedback off after all: GitHub's way for this sheet.
  const [off, setOff] = useState(false);
  const github = !direct || off;
  const clear = () => {
    setTitle("");
    setBody("");
    setContact("");
  };
  const send = useMutation({
    mutationFn: async () => {
      unwrap(await api.POST("/api/feedback", { body: { kind, title, body, contact } }));
    },
    onSuccess: () => {
      showToast("Feedback sent. Thank you!");
      onClose();
      clear();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "feedback_off") setOff(true);
    },
  });
  const close = () => {
    onClose();
    clear();
    send.reset();
  };
  const url = feedbackUrl({ kind, title, body: kiosk ? "" : body, version, install });
  const ready = title.trim().length > 0;
  const soft = display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft";
  const words = (
    <div className="flex flex-col gap-2">
      <label htmlFor={wordsId} className={labelClass}>
        What happened, or what would help
      </label>
      <textarea
        id={wordsId}
        value={body}
        maxLength={1500}
        rows={5}
        {...(display ? { inputMode: "none" as const, "data-osk": "text" } : {})}
        onChange={(event) => {
          setBody(event.target.value);
        }}
        className={`min-w-0 resize-y rounded-button border-2 border-line bg-surface text-ink ${
          display ? "min-h-40 px-5 py-4 text-d-body" : "min-h-32 px-4 py-3 text-body"
        }`}
      />
    </div>
  );
  let footer;
  if (!github) {
    footer = (
      <div className="flex flex-col gap-3">
        <Button
          block
          pending={send.isPending}
          disabled={!ready}
          onClick={() => {
            send.mutate();
          }}
        >
          Send Feedback
        </Button>
        {send.isError ? (
          <p role="alert" className={`${soft} font-semibold text-alert`}>
            {errorMessage(send.error)}
          </p>
        ) : null}
        <Button block variant="secondary" onClick={close}>
          Cancel
        </Button>
      </div>
    );
  } else if (kiosk) {
    footer = (
      <Button block variant="secondary" onClick={close}>
        Done
      </Button>
    );
  } else {
    footer = (
      <div className="flex flex-col gap-3">
        <ButtonLink
          block
          href={url}
          target="_blank"
          rel="noreferrer noopener"
          disabled={!ready}
          onClick={() => {
            if (ready) close();
          }}
        >
          Open GitHub
        </ButtonLink>
        <Button block variant="secondary" onClick={close}>
          Cancel
        </Button>
      </div>
    );
  }
  return (
    <Sheet open={open} title="Send Feedback" onClose={close} footer={footer}>
      <div className="flex flex-col gap-5">
        <Segmented
          label="What is it?"
          value={kind}
          onChange={setKind}
          options={[
            { value: "problem", label: "Something's wrong" },
            { value: "idea", label: "An idea" },
          ]}
        />
        <TextField
          label="In a few words"
          value={title}
          maxLength={80}
          autoComplete="off"
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
        {github && kiosk ? null : words}
        {github ? null : (
          <TextField
            label="How to reach you (optional)"
            hint="An email or a Discord name, if you'd like an answer."
            value={contact}
            maxLength={120}
            autoComplete="off"
            onChange={(event) => {
              setContact(event.target.value);
            }}
          />
        )}
        <p className={soft}>
          {`Sunroom ${version}${install ? ` on ${install}` : ""} is added for you. Nothing else is.`}
        </p>
        {github && kiosk && ready ? (
          <div className="flex flex-col items-center gap-4 text-center">
            <QrCode value={url} label="A code that opens GitHub's new issue" className="size-72" />
            <p className={display ? "text-d-body" : "text-body"}>
              Scan this with your phone to finish on GitHub.
            </p>
          </div>
        ) : null}
      </div>
    </Sheet>
  );
}
