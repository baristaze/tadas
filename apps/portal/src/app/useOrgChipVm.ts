import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { MembershipChoiceView } from "../api";
import { useMe, useMyMemberships, useSwitchOrg } from "../queries/tenancy";
import { useNoticesStore } from "../store/notices";
import { adoptSession } from "./adoptSession";
import { chipChoices } from "./orgChipModel";
import { switchOrg } from "./switchOrg";

export function useOrgChipVm() {
  const navigate = useNavigate();
  const me = useMe();
  const memberships = useMyMemberships();
  const exchange = useSwitchOrg();
  const notify = useNoticesStore((s) => s.notify);
  const [open, setOpen] = useState(false);
  const choices = chipChoices(memberships.isPending ? undefined : memberships.data, me.data?.org.id);

  const pick = async (membership: MembershipChoiceView) => {
    setOpen(false);
    const outcome = await switchOrg({
      exchange: () => exchange.mutateAsync(membership.org.id),
      adopt: adoptSession,
      report: notify,
    });
    // The new tenant starts on its task list; a page of the old one may not exist here.
    if (outcome === "switched") navigate("/", { replace: true });
  };

  return {
    orgName: me.data?.org.name ?? "Tadas",
    personal: me.data?.org.kind === "personal",
    role: me.data?.role,
    canOpen: me.data !== undefined,
    canSwitch: choices.canSwitch,
    others: choices.others,
    open,
    switching: exchange.isPending,
    toggle: () => setOpen((value) => me.data !== undefined && !value),
    close: () => setOpen(false),
    pick,
    newOrg: () => {
      setOpen(false);
      navigate("/orgs/new");
    },
  };
}
