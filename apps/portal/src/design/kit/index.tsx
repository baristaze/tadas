// A minimal component kit over the tokens and kit.css. Components render;
// nothing here decides. The one state a component keeps is its own: whether
// a menu is open, and where the keyboard is in it.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { tokens } from "../tokens";

/** The product's mark: a check in the accent square, and the name. */
export function BrandMark({ size = 28, withName = true }: { size?: number; withName?: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: tokens.space.sm }}>
      <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
        <rect width="28" height="28" rx="8" fill={tokens.color.accent} />
        <path
          d="M8.5 14.5l3.8 3.8 7.2-8.1"
          fill="none"
          stroke={tokens.color.accentText}
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {withName ? <span style={{ fontWeight: 650, fontSize: tokens.font.size.lg, letterSpacing: "-0.01em" }}>Tadas</span> : null}
    </span>
  );
}

/** A page: one centered column under the chrome's bar. `narrow` is the
 * sign-in and sign-up width, a single column of fields under the mark; the
 * side padding shrinks with a narrow window. A page has a title, or a heading
 * of its own in its place. */
export function Page({
  title,
  heading,
  back,
  nav,
  notice,
  narrow = false,
  children,
}: {
  title?: string;
  /** Drawn where the title goes, for a page whose heading is more than words. */
  heading?: ReactNode;
  /** The way back, above the title. */
  back?: ReactNode;
  nav?: ReactNode;
  /** What the page says above its title before anything else: a banner the
   * whole app shows, such as a payment that failed. */
  notice?: ReactNode;
  narrow?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="tadas-app">
      {nav ? (
        <header className="tadas-topbar">
          <div className="tadas-topbar-inner">{nav}</div>
        </header>
      ) : null}
      <main className="tadas-page" data-narrow={narrow || undefined}>
        <div className="tadas-column">
          {narrow ? (
            <div className="tadas-brand">
              <BrandMark size={36} withName={false} />
            </div>
          ) : null}
          {notice ? <div className="tadas-page-notice">{notice}</div> : null}
          {back ? <div className="tadas-back">{back}</div> : null}
          {heading ?? <h1 className="tadas-title">{title}</h1>}
          {/* minmax(0, 1fr): a row that never wraps shrinks with the column instead of widening it. */}
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: tokens.space.lg }}>{children}</div>
        </div>
      </main>
    </div>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="tadas-card">
      {title ? <h2 className="tadas-card-title">{title}</h2> : null}
      {children}
    </section>
  );
}

export function Button({
  children,
  onClick,
  type = "button",
  disabled,
  tone = "accent",
  wide = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  disabled?: boolean;
  tone?: "accent" | "danger" | "plain";
  wide?: boolean;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="tadas-button"
      data-tone={tone}
      data-wide={wide || undefined}
    >
      {children}
    </button>
  );
}

export function TextField({
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "password" | "date";
  autoComplete?: string;
  placeholder?: string;
}) {
  return (
    <label className="tadas-label">
      <span>{label}</span>
      <input
        type={type}
        value={value}
        autoComplete={autoComplete}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="tadas-field"
      />
    </label>
  );
}

export function Banner({ children }: { children: ReactNode }) {
  return (
    <div role="status" className="tadas-banner">
      <svg className="tadas-banner-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6.75" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 4.75v3.75" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="8" cy="11" r="0.9" fill="currentColor" />
      </svg>
      <div className="tadas-banner-body">{children}</div>
    </div>
  );
}

/** What went wrong, in the danger colour, announced to a screen reader. */
export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <span role="alert" className="tadas-error">
      {children}
    </span>
  );
}

export function Muted({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <span style={{ color: tokens.color.muted, ...style }}>{children}</span>;
}

export function Table({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
  return (
    <table className="tadas-table">
      <thead>
        <tr>
          {headers.map((header) => (
            <th key={header}>{header}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((cells, index) => (
          <tr key={index}>
            {cells.map((cell, cellIndex) => (
              <td key={cellIndex}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Pill({
  children,
  title,
  tone = "plain",
}: {
  children: ReactNode;
  title?: string;
  tone?: "plain" | "accent" | "danger";
}) {
  return (
    <span title={title} className="tadas-pill" data-tone={tone}>
      {children}
    </span>
  );
}

export function LinkButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="tadas-link">
      {children}
    </button>
  );
}

/** `large` is the control that stands as a page's heading. */
export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  large = false,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  large?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="tadas-segmented" data-large={large || undefined}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className="tadas-segment"
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function TextArea({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="tadas-label">
      <span>{label}</span>
      <textarea value={value} rows={3} onChange={(event) => onChange(event.target.value)} className="tadas-field" />
    </label>
  );
}

export function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="tadas-label">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="tadas-field">
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** A square button that shows an icon; the label is what a screen reader says. */
export function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className="tadas-icon-button">
      {children}
    </button>
  );
}

interface MenuState {
  /** Closes the menu; the keyboard goes back to the button that opened it. */
  close: () => void;
}

const MenuContext = createContext<MenuState>({ close: () => undefined });

/** The items the arrows move through, in order; a disabled one is skipped. */
function menuItems(menu: HTMLElement | null): HTMLElement[] {
  if (!menu) return [];
  return [...menu.querySelectorAll<HTMLElement>('[role="menuitem"], [role="menuitemradio"]')].filter(
    (item) => !(item as HTMLButtonElement).disabled,
  );
}

/** A button that opens a menu under it. A click, Enter, or Space opens it and
 * the keyboard lands on the first item (ArrowUp on the button lands on the
 * last); the arrows, Home, and End move; Escape closes it and puts the
 * keyboard back on the button; a click anywhere else or Tab closes it. */
export function Menu({
  label,
  trigger,
  triggerLabel,
  triggerTitle,
  triggerClassName = "tadas-menu-trigger",
  align = "start",
  minWidth = 220,
  disabled = false,
  children,
}: {
  /** What a screen reader calls the open menu. */
  label: string;
  /** What the button shows. */
  trigger: ReactNode;
  /** What a screen reader calls the button, when its content does not say it. */
  triggerLabel?: string;
  triggerTitle?: string;
  triggerClassName?: string;
  /** Which edge of the button the menu lines up with. */
  align?: "start" | "end";
  minWidth?: number;
  disabled?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const landOn = useRef<"first" | "last">("first");
  const id = useId();

  const close = useCallback(() => {
    setOpen(false);
    button.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const items = menuItems(menu.current);
    (landOn.current === "last" ? items[items.length - 1] : items[0])?.focus();
    const outside = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  const onButtonKey = (event: KeyboardEvent) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    landOn.current = event.key === "ArrowUp" ? "last" : "first";
    setOpen(true);
  };

  const onMenuKey = (event: KeyboardEvent) => {
    const items = menuItems(menu.current);
    const at = items.indexOf(document.activeElement as HTMLElement);
    const go = (index: number) => items[(index + items.length) % items.length]?.focus();
    if (event.key === "ArrowDown") go(at + 1);
    else if (event.key === "ArrowUp") go(at < 0 ? -1 : at - 1);
    else if (event.key === "Home") go(0);
    else if (event.key === "End") go(-1);
    else if (event.key === "Escape") close();
    else if (event.key === "Tab") setOpen(false);
    else return;
    if (event.key !== "Tab") event.preventDefault();
  };

  return (
    <div ref={root} style={{ position: "relative", minWidth: 0, display: "flex" }}>
      <button
        ref={button}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={triggerLabel}
        title={triggerTitle}
        disabled={disabled}
        onClick={() => {
          landOn.current = "first";
          setOpen((value) => !value);
        }}
        onKeyDown={onButtonKey}
        className={triggerClassName}
      >
        {trigger}
      </button>
      {open ? (
        <div
          ref={menu}
          id={id}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKey}
          className="tadas-menu"
          style={{ position: "absolute", top: "calc(100% + 6px)", [align === "end" ? "right" : "left"]: 0, zIndex: 30, minWidth }}
        >
          <MenuContext.Provider value={{ close }}>{children}</MenuContext.Provider>
        </div>
      ) : null}
    </div>
  );
}

/** One thing a menu does. It closes the menu, then does it. */
export function MenuItem({
  onSelect,
  disabled,
  children,
}: {
  onSelect: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  const { close } = useContext(MenuContext);
  return (
    <button
      type="button"
      role="menuitem"
      tabIndex={-1}
      disabled={disabled}
      onClick={() => {
        close();
        onSelect();
      }}
      className="tadas-menu-item"
    >
      {children}
    </button>
  );
}

/** One of a set of choices, the current one checked. The menu stays open, so
 * the choice is seen taking effect. */
export function MenuItemRadio({
  checked,
  onSelect,
  children,
}: {
  checked: boolean;
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={checked}
      tabIndex={-1}
      onClick={onSelect}
      className="tadas-menu-item"
    >
      <span>{children}</span>
      {checked ? (
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" style={{ color: tokens.color.link }}>
          <path d="M3 7.5l2.75 2.75L11 4.5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : null}
    </button>
  );
}

/** Words in a menu that are not a choice: a group's name, or a fact. */
export function MenuText({ children, strong = false }: { children: ReactNode; strong?: boolean }) {
  return (
    <div role="presentation" className="tadas-menu-text" data-strong={strong || undefined}>
      {children}
    </div>
  );
}

export function MenuSeparator() {
  return <div role="separator" className="tadas-menu-separator" />;
}

/** The small down-pointing mark on a button that opens a menu. */
export function Caret() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
