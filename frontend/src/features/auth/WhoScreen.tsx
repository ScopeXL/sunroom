import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCanGoBack, useNavigate, useRouter } from "@tanstack/react-router";
import { UserPlus, UserRound } from "lucide-react";
import { useState } from "react";

import { api, errorMessage, unwrap } from "../../api/client";
import { qk } from "../../api/keys";
import { fetchSession, type Session } from "../../lib/session";
import { Button } from "../../ui/Button";
import { AddPersonRow, type RoleChoice } from "../settings/AddPersonRow";
import { MemberButton } from "./MemberButton";

/** Where Who's using this device was opened from, so it can go back there. */
export type WhoFrom = "more" | "settings";

/**
 * "Who's using this device?" (UX §5): attribution for what this device adds and checks off.
 * Whoever uses this device shows as "Using this device". A guest picks nobody. Opened from More or
 * Settings, it goes back there after a choice (or Back); right after signing in, on to Today
 * (or Skip for now).
 */
export function WhoScreen({ from }: { from?: WhoFrom | undefined }) {
  const navigate = useNavigate();
  const router = useRouter();
  const canGoBack = useCanGoBack();
  const queryClient = useQueryClient();
  const { data: session } = useQuery({ queryKey: qk.session(), queryFn: fetchSession });
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const leave = async () => {
    if (from && canGoBack) {
      router.history.back();
      return;
    }
    await navigate({ to: from === "settings" ? "/settings" : from === "more" ? "/more" : "/" });
  };

  const finish = async (updated: Session) => {
    queryClient.setQueryData(qk.session(), updated);
    await queryClient.invalidateQueries({ queryKey: qk.members() });
    await leave();
  };

  const choose = useMutation({
    mutationFn: async (memberId: string | null) =>
      unwrap(await api.PUT("/api/auth/member", { body: { member_id: memberId } })),
    onSuccess: finish,
    onError: (failure) => {
      setError(errorMessage(failure));
    },
  });

  const addMe = useMutation({
    mutationFn: async ({ name, role }: { name: string; role: RoleChoice }) => {
      const member = unwrap(await api.POST("/api/members", { body: { name, role } }));
      return unwrap(await api.PUT("/api/auth/member", { body: { member_id: member.id } }));
    },
    onSuccess: finish,
    onError: (failure) => {
      setError(errorMessage(failure));
    },
  });

  const members = session?.members ?? [];
  const current = session?.member ?? null;
  const canAdd = session?.is_parent ?? false;
  const showForm = canAdd && (adding || members.length === 0);

  return (
    <main className="mx-auto w-full max-w-md px-4 pt-[calc(env(safe-area-inset-top)+32px)] pb-12">
      <h1 className="text-title font-bold">Who’s Using This Device?</h1>
      <p className="mt-2 mb-6 text-body text-ink-soft">
        Pick your name so everyone can see who added or checked off what.
      </p>
      <ul className="flex flex-col gap-3">
        {members.map((member) => (
          <li key={member.id}>
            <MemberButton
              member={member}
              chosen={member.id === current?.id}
              disabled={choose.isPending}
              onChoose={() => {
                if (member.id === current?.id) void leave();
                else choose.mutate(member.id);
              }}
            />
          </li>
        ))}
      </ul>
      {showForm ? (
        <div className="mt-6 flex flex-col gap-3">
          <AddPersonRow
            label="Your name"
            action="Add Me"
            primary
            autoComplete="given-name"
            pending={addMe.isPending}
            error={null}
            onAdd={(name, role) => addMe.mutateAsync({ name, role })}
          />
          {members.length > 0 ? (
            <Button
              variant="quiet"
              block
              onClick={() => {
                setAdding(false);
              }}
            >
              Cancel
            </Button>
          ) : null}
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          {canAdd ? (
            <Button
              variant="secondary"
              block
              onClick={() => {
                setAdding(true);
              }}
            >
              <UserPlus aria-hidden="true" />
              Someone Else
            </Button>
          ) : null}
          <Button
            variant="secondary"
            block
            onClick={() => {
              choose.mutate(null);
            }}
          >
            <UserRound aria-hidden="true" />A Guest
          </Button>
        </div>
      )}
      <p role="alert" className="mt-3 min-h-7 text-secondary font-semibold text-alert">
        {error}
      </p>
      {from || current ? (
        <Button
          variant="quiet"
          block
          onClick={() => {
            void leave();
          }}
        >
          Back
        </Button>
      ) : (
        <Button
          variant="quiet"
          block
          onClick={() => {
            void navigate({ to: "/" });
          }}
        >
          Skip for Now
        </Button>
      )}
    </main>
  );
}
