// A minimal component kit over the tokens and kit.css. Components render;
// nothing here decides.
import type { CSSProperties, ReactNode } from "react";
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
 * side padding shrinks with a narrow window. */
export function Page({
  title,
  nav,
  narrow = false,
  children,
}: {
  title: string;
  nav?: ReactNode;
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
          <h1 className="tadas-title">{title}</h1>
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

export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="tadas-segmented">
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
