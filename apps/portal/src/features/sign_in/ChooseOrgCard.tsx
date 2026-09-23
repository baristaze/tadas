import type { MembershipChoiceView } from "../../api";
import { placeNote } from "../../app/orgChipModel";
import { Card, Muted } from "../../design/kit";

/** The person's places, the personal one first: one button each. */
export function ChooseOrgCard({
  memberships,
  onPick,
}: {
  memberships: MembershipChoiceView[];
  onPick: (membership: MembershipChoiceView) => void;
}) {
  return (
    <Card title="Choose an organization">
      <div className="tadas-menu" role="menu">
        {memberships.map((membership) => (
          <button
            key={membership.org.id}
            type="button"
            role="menuitem"
            className="tadas-menu-item"
            onClick={() => onPick(membership)}
          >
            <span>{membership.org.name}</span>
            <Muted>{placeNote(membership)}</Muted>
          </button>
        ))}
      </div>
    </Card>
  );
}
