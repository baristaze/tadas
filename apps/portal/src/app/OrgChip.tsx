// The current org in the chrome, with the plan it is on. It opens a menu: the
// other places to switch to, when there are any, and a new team org.
import { Pill } from "../design/kit";
import { tokens } from "../design/tokens";
import { placeNote } from "./orgChipModel";
import { useOrgChipVm } from "./useOrgChipVm";

export function OrgChip() {
  const vm = useOrgChipVm();
  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={vm.toggle}
        disabled={!vm.canOpen || vm.switching}
        aria-haspopup="menu"
        aria-expanded={vm.open}
        title={vm.canSwitch ? "Switch or create an organization" : "Create an organization"}
        className="tadas-org-chip"
        style={{ cursor: vm.canOpen ? "pointer" : "default" }}
      >
        <span className="tadas-org-avatar" aria-hidden>
          {vm.orgName.trim().charAt(0).toUpperCase()}
        </span>
        {vm.orgName}
        {vm.personal ? (
          <span style={{ color: tokens.color.muted, fontWeight: 400, fontSize: tokens.font.size.sm }}>personal</span>
        ) : null}
        {vm.plan ? (
          <Pill tone={vm.plan === "Free" ? "plain" : "accent"} title={`This org is on ${vm.plan}`}>
            {vm.plan}
          </Pill>
        ) : null}
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" style={{ color: tokens.color.muted }}>
          <path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {vm.open ? (
        <div
          role="menu"
          className="tadas-menu"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            zIndex: 30,
            minWidth: 240,
          }}
        >
          {vm.canSwitch ? (
            <div
              style={{
                padding: `${tokens.space.xs} 10px`,
                fontSize: tokens.font.size.xs,
                fontWeight: 550,
                color: tokens.color.muted,
              }}
            >
              Switch to
            </div>
          ) : null}
          {vm.others.map((membership) => (
            <button
              key={membership.org.id}
              type="button"
              role="menuitem"
              onClick={() => void vm.pick(membership)}
              className="tadas-menu-item"
            >
              <span>{membership.org.name}</span>
              <span style={{ color: tokens.color.muted, fontSize: tokens.font.size.sm }}>{placeNote(membership)}</span>
            </button>
          ))}
          <div
            style={{
              borderTop: vm.canSwitch ? `1px solid ${tokens.color.border}` : "none",
              marginTop: vm.canSwitch ? tokens.space.xs : 0,
              paddingTop: vm.canSwitch ? tokens.space.xs : 0,
            }}
          >
            <button type="button" role="menuitem" onClick={vm.newOrg} className="tadas-menu-item">
              <span>New organization…</span>
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
