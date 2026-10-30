import { Star } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { errorMessage } from "../../api/client";
import { useMembers } from "../../lib/household";
import { useT } from "../../lib/lang";
import { HeaderBack } from "../../shell/HeaderLinks";
import { RoomHeader } from "../../shell/roomHeader";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { useFieldLabel } from "../../ui/Field";
import { PanelActions } from "../../ui/PanelActions";
import { celebrate } from "../../ui/Celebration";
import { Chip, ChipRow } from "../../ui/Chip";
import { EmptyState } from "../../ui/EmptyState";
import { Screen } from "../../ui/Screen";
import { useShell } from "../../ui/shell";
import { SidePanel } from "../../ui/SidePanel";
import { TextField } from "../../ui/TextField";
import { WhoPicker } from "../../ui/WhoPicker";
import { Pop } from "../../ui/Pop";
import { personOf, Strip, useViewer } from "./ChoreBoard";
import { useChoreChanges, useRewards, type Redemption, type Reward, type Stars } from "./data";
import { starsLine } from "./words";

const COSTS = [5, 10, 20, 30, 50, 100];

/**
 * Stars & rewards (UX §4, §6 "Redeem a reward"): each kid's balance, the rewards stars buy with
 * Ask for it (who's asking, kids only), and what's been asked with Approve (the PIN on the wall
 * screen) and Not now. A reward costing more than a kid has says so under a disabled button.
 */
export function RewardsPage() {
  const t = useT();
  const display = useShell() === "display";
  const body = <RewardsBody />;
  if (!display) {
    return (
      <Screen title={t("tasks.rewards.title")} back="/chores">
        {body}
      </Screen>
    );
  }
  return (
    <section aria-label={t("tasks.rewards.title")} className="flex min-h-0 flex-1 flex-col">
      <RoomHeader
        title={t("tasks.rewards.title")}
        visibleTitle
        back={
          <HeaderBack to="/$room" params={{ room: "chores" }}>
            {t("tasks.room.title")}
          </HeaderBack>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">{body}</div>
    </section>
  );
}

function RewardsBody() {
  const t = useT();
  const display = useShell() === "display";
  const { data } = useRewards();
  const { data: members = [] } = useMembers();
  const viewer = useViewer();
  const [asking, setAsking] = useState<Reward | null>(null);
  const [editing, setEditing] = useState<Reward | "new" | null>(null);
  if (!data) return null;
  const gap = display ? "gap-8" : "gap-6";
  return (
    <div className={`flex flex-col ${gap}`}>
      {data.asked.length && viewer.answers ? <AskedStrip asked={data.asked} /> : null}
      {data.stars.length ? (
        <ul className={`flex flex-col ${display ? "gap-3" : "gap-2"}`}>
          {data.stars.map((stars) => {
            const kid = personOf(members, stars.member_id);
            if (!kid) return null;
            return (
              <li key={stars.member_id} data-person={kid.color} className="flex items-center gap-3">
                <Avatar member={kid} size={display ? "lg" : "md"} />
                <span className="flex flex-col">
                  <span className={display ? "text-d-body font-bold" : "text-body font-bold"}>
                    {kid.name}
                  </span>
                  <Pop
                    value={starsLine(stars)}
                    className={`self-start ${display ? "text-d-secondary" : "text-secondary"}`}
                  />
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      {data.rewards.length === 0 ? (
        <EmptyState
          icon={Star}
          line={t("tasks.rewards.none.empty")}
          note={t("tasks.rewards.none.hint")}
          action={
            <Button
              onClick={() => {
                setEditing("new");
              }}
            >
              {t("tasks.reward.add.action")}
            </Button>
          }
        />
      ) : (
        <>
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-4">
            {data.rewards.map((reward) => (
              <RewardTile
                key={reward.id}
                reward={reward}
                stars={data.stars}
                onAsk={() => {
                  setAsking(reward);
                }}
              />
            ))}
          </ul>
          {viewer.answers ? (
            <div>
              <Button
                variant="secondary"
                onClick={() => {
                  setEditing("new");
                }}
              >
                {t("tasks.reward.add.action")}
              </Button>
            </div>
          ) : null}
        </>
      )}
      <AskPanel
        reward={asking}
        stars={data.stars}
        onClose={() => {
          setAsking(null);
        }}
      />
      <RewardPanel
        reward={editing === "new" ? null : editing}
        open={editing !== null}
        onClose={() => {
          setEditing(null);
        }}
      />
    </div>
  );
}

function RewardTile({
  reward,
  stars,
  onAsk,
}: {
  reward: Reward;
  stars: Stars[];
  onAsk: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const viewer = useViewer();
  const { data: members = [] } = useMembers();
  const { redeem } = useChoreChanges();
  // A kid's own phone asks for that kid straight away.
  const me = !viewer.answers && viewer.memberId ? personOf(members, viewer.memberId) : undefined;
  const mine = me ? stars.find((s) => s.member_id === me.id) : undefined;
  const short = me && mine ? mine.balance - mine.held < reward.cost_points : false;
  return (
    <li
      className={`flex flex-col gap-3 rounded-panel border border-line bg-surface ${display ? "p-6" : "p-4"}`}
    >
      <h3 className={`font-bold break-words ${display ? "text-d-title" : "text-row"}`}>
        {reward.title}
      </h3>
      <span
        className={`inline-flex items-center gap-1 font-bold ${display ? "text-d-body" : "text-body"}`}
      >
        <Star
          aria-hidden="true"
          className={display ? "size-6 fill-sun stroke-sun-ink" : "size-4 fill-sun stroke-sun-ink"}
        />
        {reward.cost_points}
        <span className="sr-only"> {t("tasks.stars.unit.aria")}</span>
      </span>
      <Button
        variant="secondary"
        disabled={short}
        pending={redeem.isPending && redeem.variables.reward.id === reward.id}
        onClick={() => {
          if (me) redeem.mutate({ reward, member: me.id, name: me.name });
          else onAsk();
        }}
      >
        {t("tasks.reward.ask.action")}
      </Button>
      {short && me && mine ? (
        <span
          className={display ? "text-d-secondary text-ink-soft" : "text-secondary text-ink-soft"}
        >
          {t("tasks.reward.short", {
            name: me.name,
            has: mine.balance - mine.held,
            cost: reward.cost_points,
          })}
        </span>
      ) : null}
    </li>
  );
}

/** Ask for it on a shared screen: which kid is asking (UX §6). */
function AskPanel({
  reward,
  stars,
  onClose,
}: {
  reward: Reward | null;
  stars: Stars[];
  onClose: () => void;
}) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const { redeem } = useChoreChanges();
  const [kid, setKid] = useState<string | null>(null);
  const chosen = personOf(members, kid);
  const balance = stars.find((s) => s.member_id === kid);
  const has = balance ? balance.balance - balance.held : 0;
  const short = reward ? has < reward.cost_points : true;
  const close = () => {
    setKid(null);
    onClose();
  };
  return (
    <SidePanel
      open={reward !== null}
      title={reward ? t("tasks.reward.ask.title", { name: reward.title }) : ""}
      onClose={close}
    >
      {reward ? (
        <div className={`flex flex-col ${display ? "gap-6" : "gap-5"}`}>
          <p className={display ? "text-d-body font-semibold" : "text-body font-semibold"}>
            {t("tasks.reward.who.label")}
          </p>
          <WhoPicker
            label={t("tasks.reward.who.label")}
            members={members}
            kidsOnly
            everyone={false}
            value={kid ? [kid] : []}
            onChange={(ids) => {
              setKid(ids[0] ?? null);
            }}
          />
          {chosen ? (
            <p className={display ? "text-d-body" : "text-body"}>
              {short
                ? t("tasks.reward.short", { name: chosen.name, has, cost: reward.cost_points })
                : t("tasks.reward.has", { name: chosen.name, has })}
            </p>
          ) : null}
          {redeem.isError ? (
            <p role="alert" className="font-semibold text-alert">
              {errorMessage(redeem.error)}
            </p>
          ) : null}
          <Button
            block
            disabled={!chosen || short}
            pending={redeem.isPending}
            onClick={() => {
              if (!chosen) return;
              redeem.mutate({ reward, member: chosen.id, name: chosen.name }, { onSuccess: close });
            }}
          >
            {t("tasks.reward.ask.action")}
          </Button>
        </div>
      ) : null}
    </SidePanel>
  );
}

/** What kids asked for, with Approve and Not now (UX §6). A yes gets the big burst. */
export function AskedStrip({ asked }: { asked: Redemption[] }) {
  const t = useT();
  const display = useShell() === "display";
  const { data: members = [] } = useMembers();
  const { decide } = useChoreChanges();
  const strip = useRef<HTMLDivElement>(null);
  return (
    <div ref={strip}>
      <Strip title={t("tasks.asked.title")}>
        {asked.map((redemption) => {
          const kid = personOf(members, redemption.member_id);
          const name = kid?.name ?? t("tasks.asked.someone");
          return (
            <Row key={redemption.id}>
              <span className={display ? "text-d-body font-semibold" : "text-body font-semibold"}>
                {`${name} · ${redemption.reward_title} · ★${String(redemption.cost_points)}`}
              </span>
              <span className="flex gap-2">
                <Button
                  pending={
                    decide.isPending &&
                    decide.variables.redemption.id === redemption.id &&
                    decide.variables.yes
                  }
                  onClick={() => {
                    decide.mutate(
                      { redemption, yes: true, name },
                      {
                        onSuccess: () => {
                          celebrate(strip.current, kid?.color ?? "everyone", "full");
                        },
                      },
                    );
                  }}
                >
                  {t("tasks.asked.approve.action")}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => {
                    decide.mutate({ redemption, yes: false, name });
                  }}
                >
                  {t("tasks.asked.not_now.action")}
                </Button>
              </span>
            </Row>
          );
        })}
        {decide.isError ? (
          <p role="alert" className="py-2 font-semibold text-alert">
            {errorMessage(decide.error)}
          </p>
        ) : null}
      </Strip>
    </div>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center justify-between gap-3 py-2">{children}</div>;
}

/** Add or change a reward (a parent; the PIN on the wall screen). */
export function RewardPanel({
  reward,
  open,
  onClose,
}: {
  reward: Reward | null;
  open: boolean;
  onClose: () => void;
}) {
  const t = useT();
  return (
    <SidePanel
      open={open}
      title={reward ? t("tasks.edit.title", { name: reward.title }) : t("tasks.reward.add.title")}
      onClose={onClose}
    >
      {open ? <RewardForm key={reward?.id ?? "new"} reward={reward} onClose={onClose} /> : null}
    </SidePanel>
  );
}

function RewardForm({ reward, onClose }: { reward: Reward | null; onClose: () => void }) {
  const t = useT();
  const display = useShell() === "display";
  const { saveReward, removeReward } = useChoreChanges();
  const [title, setTitle] = useState(reward?.title ?? "");
  const [cost, setCost] = useState(reward?.cost_points ?? 20);
  const label = useFieldLabel();
  return (
    <form
      className={`flex flex-col ${display ? "gap-6" : "gap-5"}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (!title.trim()) return;
        saveReward.mutate({ reward, title: title.trim(), cost }, { onSuccess: onClose });
      }}
    >
      <TextField
        label={t("tasks.reward.what.label")}
        placeholder={t("tasks.reward.what.placeholder")}
        autoComplete="off"
        value={title}
        onChange={(event) => {
          setTitle(event.target.value);
        }}
      />
      <div className="flex flex-col gap-2">
        <p className={label}>{t("tasks.reward.cost.label")}</p>
        <ChipRow label={t("tasks.reward.cost.label")}>
          {COSTS.map((value) => (
            <Chip
              key={value}
              on={cost === value}
              label={t("tasks.reward.cost.aria", { n: value })}
              onClick={() => {
                setCost(value);
              }}
            >
              {`★${String(value)}`}
            </Chip>
          ))}
          {!COSTS.includes(cost) ? (
            <Chip on onClick={() => undefined}>
              {`★${String(cost)}`}
            </Chip>
          ) : null}
        </ChipRow>
      </div>
      {saveReward.isError || removeReward.isError ? (
        <p role="alert" className="font-semibold text-alert">
          {errorMessage(saveReward.error ?? removeReward.error)}
        </p>
      ) : null}
      {reward ? (
        <Button
          variant="quiet-danger"
          pending={removeReward.isPending}
          onClick={() => {
            removeReward.mutate({ reward }, { onSuccess: onClose });
          }}
        >
          {t("tasks.remove.action", { name: reward.title })}
        </Button>
      ) : null}
      <PanelActions>
        <Button type="submit" block disabled={!title.trim()} pending={saveReward.isPending}>
          {reward ? t("app.action.save_changes") : t("tasks.reward.add.action")}
        </Button>
      </PanelActions>
    </form>
  );
}
