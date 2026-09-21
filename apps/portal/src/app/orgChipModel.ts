// Pure: what the org chip offers. The current org comes from `me`; the
// person's places come from the memberships list. With one place there is
// nothing to switch to, and the chip is a label.
import type { MembershipChoiceView } from "../api";

export interface ChipChoices {
  canSwitch: boolean;
  /** The other orgs, by name; the current one is not offered. */
  others: MembershipChoiceView[];
}

export function chipChoices(memberships: MembershipChoiceView[] | undefined, currentOrgId: string | undefined): ChipChoices {
  if (!memberships || !currentOrgId) return { canSwitch: false, others: [] };
  const others = memberships
    .filter((membership) => membership.org.id !== currentOrgId)
    .sort((a, b) => a.org.name.localeCompare(b.org.name));
  return { canSwitch: others.length > 0, others };
}
