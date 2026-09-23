// The current org in the chrome. With more than one place it opens the list
// and switches; with one it is a label.
import { tokens } from "../design/tokens";
import { useOrgChipVm } from "./useOrgChipVm";

export function OrgChip() {
  const vm = useOrgChipVm();
  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={vm.toggle}
        disabled={!vm.canSwitch || vm.switching}
        aria-haspopup={vm.canSwitch ? "menu" : undefined}
        aria-expanded={vm.canSwitch ? vm.open : undefined}
        title={vm.canSwitch ? "Switch organization" : undefined}
        className="tadas-org-chip"
        style={{ cursor: vm.canSwitch ? "pointer" : "default" }}
      >
        <span className="tadas-org-avatar" aria-hidden>
          {vm.orgName.trim().charAt(0).toUpperCase()}
        </span>
        {vm.orgName}
        {vm.canSwitch ? (
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" style={{ color: tokens.color.muted }}>
            <path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : null}
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
            minWidth: 220,
          }}
        >
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
          {vm.others.map((membership) => (
            <button
              key={membership.org.id}
              type="button"
              role="menuitem"
              onClick={() => void vm.pick(membership)}
              className="tadas-menu-item"
            >
              <span>{membership.org.name}</span>
              <span style={{ color: tokens.color.muted, fontSize: tokens.font.size.sm }}>{membership.role}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
