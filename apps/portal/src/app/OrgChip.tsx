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
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: tokens.space.xs,
          font: "inherit",
          fontWeight: 600,
          color: tokens.color.text,
          background: tokens.color.surface,
          border: `1px solid ${tokens.color.border}`,
          borderRadius: 999,
          padding: `${tokens.space.xs} ${tokens.space.md}`,
          cursor: vm.canSwitch ? "pointer" : "default",
        }}
      >
        {vm.orgName}
        {vm.canSwitch ? <span aria-hidden style={{ color: tokens.color.muted }}>▾</span> : null}
      </button>
      {vm.open ? (
        <div
          role="menu"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            zIndex: 10,
            minWidth: 220,
            background: tokens.color.surface,
            border: `1px solid ${tokens.color.border}`,
            borderRadius: tokens.radius.md,
            boxShadow: "0 4px 16px rgba(0, 0, 0, 0.08)",
            padding: tokens.space.xs,
          }}
        >
          <div style={{ padding: tokens.space.sm, fontSize: tokens.font.size.sm, color: tokens.color.muted }}>
            Switch to
          </div>
          {vm.others.map((membership) => (
            <button
              key={membership.org.id}
              type="button"
              role="menuitem"
              onClick={() => void vm.pick(membership)}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: tokens.space.md,
                width: "100%",
                font: "inherit",
                textAlign: "left",
                background: "none",
                border: "none",
                borderRadius: tokens.radius.sm,
                padding: tokens.space.sm,
                cursor: "pointer",
                color: tokens.color.text,
              }}
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
