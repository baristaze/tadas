// The account menu at the right of the bar: who is signed in and where,
// Settings, the theme, and Sign out. It opens on a click, never on hover.
import { Caret, Menu, MenuItem, MenuItemRadio, MenuSeparator, MenuText } from "../design/kit";
import { useAccountMenuVm } from "./useAccountMenuVm";

export function AccountMenu() {
  const vm = useAccountMenuVm();
  return (
    <Menu
      label="Account"
      triggerLabel={vm.email ? `Account: ${vm.email}` : "Account"}
      align="end"
      minWidth={240}
      disabled={!vm.ready}
      trigger={
        <>
          <span className="tadas-account-email">{vm.email}</span>
          <span className="tadas-account-email" data-short>
            {vm.shortEmail}
          </span>
          <Caret />
        </>
      }
    >
      <MenuText strong>{vm.email}</MenuText>
      <MenuText>{vm.orgName}</MenuText>
      <MenuSeparator />
      <MenuItem onSelect={vm.openSettings}>Settings</MenuItem>
      <MenuSeparator />
      <div role="group" aria-label="Theme">
        <MenuText>Theme</MenuText>
        {vm.themes.map((choice) => (
          <MenuItemRadio key={choice.value} checked={vm.theme === choice.value} onSelect={() => vm.setTheme(choice.value)}>
            {choice.label}
          </MenuItemRadio>
        ))}
      </div>
      <MenuSeparator />
      <MenuItem onSelect={vm.signOut} disabled={vm.signingOut}>
        Sign out
      </MenuItem>
    </Menu>
  );
}
