// A minimal component kit over the tokens. Components render; nothing here decides.
import type { CSSProperties, ReactNode } from "react";
import { tokens } from "../tokens";

/** A page: one centered column. `narrow` is the sign-in and sign-up width,
 * a single column of fields; the side padding shrinks with a narrow window. */
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
    <main
      style={{
        minHeight: "100vh",
        background: tokens.color.bg,
        color: tokens.color.text,
        fontFamily: tokens.font.family,
        fontSize: tokens.font.size.md,
        padding: `${narrow ? "12vh" : tokens.space.xl} clamp(${tokens.space.md}, 4vw, ${tokens.space.xl})`,
      }}
    >
      <div style={{ maxWidth: narrow ? 400 : 880, margin: "0 auto" }}>
        {nav}
        <h1
          style={{
            fontSize: tokens.font.size.xl,
            margin: 0,
            marginBottom: tokens.space.lg,
            textAlign: narrow ? "center" : undefined,
          }}
        >
          {title}
        </h1>
        {/* minmax(0, 1fr): a row that never wraps shrinks with the column instead of widening it. */}
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: tokens.space.lg }}>{children}</div>
      </div>
    </main>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section
      style={{
        background: tokens.color.surface,
        border: `1px solid ${tokens.color.border}`,
        borderRadius: tokens.radius.md,
        padding: `clamp(${tokens.space.md}, 4vw, ${tokens.space.lg})`,
      }}
    >
      {title ? (
        <h2 style={{ fontSize: tokens.font.size.lg, margin: 0, marginBottom: tokens.space.md }}>
          {title}
        </h2>
      ) : null}
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
  const background =
    tone === "accent" ? tokens.color.accent : tone === "danger" ? tokens.color.danger : "transparent";
  const color = tone === "plain" ? tokens.color.text : tokens.color.accentText;
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="tadas-button"
      style={{
        width: wide ? "100%" : undefined,
        background,
        color,
        border: tone === "plain" ? `1px solid ${tokens.color.border}` : "none",
        borderRadius: tokens.radius.sm,
        padding: `${tokens.space.sm} ${tokens.space.md}`,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        font: "inherit",
      }}
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
  type?: "text" | "email" | "password";
  autoComplete?: string;
  placeholder?: string;
}) {
  return (
    <label style={{ display: "grid", gap: tokens.space.xs, fontSize: tokens.font.size.sm }}>
      <span style={{ color: tokens.color.muted }}>{label}</span>
      <input
        type={type}
        value={value}
        autoComplete={autoComplete}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        style={{
          font: "inherit",
          fontSize: tokens.font.size.md,
          padding: tokens.space.sm,
          border: `1px solid ${tokens.color.border}`,
          borderRadius: tokens.radius.sm,
        }}
      />
    </label>
  );
}

export function Banner({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      style={{
        background: tokens.color.warningBg,
        color: tokens.color.warningText,
        borderRadius: tokens.radius.sm,
        padding: `${tokens.space.sm} ${tokens.space.md}`,
      }}
    >
      {children}
    </div>
  );
}

/** What went wrong, in the danger colour, announced to a screen reader. */
export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <span role="alert" style={{ color: tokens.color.danger, fontSize: tokens.font.size.sm }}>
      {children}
    </span>
  );
}

export function Muted({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <span style={{ color: tokens.color.muted, ...style }}>{children}</span>;
}

export function Table({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: tokens.font.size.sm }}>
      <thead>
        <tr>
          {headers.map((header) => (
            <th
              key={header}
              style={{
                textAlign: "left",
                padding: tokens.space.sm,
                borderBottom: `1px solid ${tokens.color.border}`,
                color: tokens.color.muted,
                fontWeight: 500,
              }}
            >
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((cells, index) => (
          <tr key={index}>
            {cells.map((cell, cellIndex) => (
              <td
                key={cellIndex}
                style={{ padding: tokens.space.sm, borderBottom: `1px solid ${tokens.color.border}` }}
              >
                {cell}
              </td>
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
  tone?: "plain" | "accent";
}) {
  return (
    <span
      title={title}
      style={{
        display: "inline-block",
        flexShrink: 0,
        fontSize: tokens.font.size.sm,
        color: tone === "accent" ? tokens.color.accent : tokens.color.muted,
        background: tone === "accent" ? tokens.color.surface : tokens.color.bg,
        border: `1px solid ${tone === "accent" ? tokens.color.accent : tokens.color.border}`,
        borderRadius: 999,
        padding: `0 ${tokens.space.sm}`,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

export function LinkButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        flexShrink: 0,
        background: "none",
        border: "none",
        padding: 0,
        color: tokens.color.accent,
        font: "inherit",
        fontSize: tokens.font.size.sm,
        cursor: "pointer",
      }}
    >
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
    <div
      role="radiogroup"
      aria-label={label}
      style={{
        display: "inline-flex",
        border: `1px solid ${tokens.color.border}`,
        borderRadius: tokens.radius.sm,
        overflow: "hidden",
      }}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            style={{
              font: "inherit",
              fontSize: tokens.font.size.sm,
              padding: `${tokens.space.xs} ${tokens.space.md}`,
              border: "none",
              cursor: "pointer",
              background: selected ? tokens.color.accent : tokens.color.surface,
              color: selected ? tokens.color.accentText : tokens.color.text,
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

const fieldStyle: CSSProperties = {
  font: "inherit",
  fontSize: tokens.font.size.md,
  padding: tokens.space.sm,
  border: `1px solid ${tokens.color.border}`,
  borderRadius: tokens.radius.sm,
  background: tokens.color.surface,
};

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
    <label style={{ display: "grid", gap: tokens.space.xs, fontSize: tokens.font.size.sm }}>
      <span style={{ color: tokens.color.muted }}>{label}</span>
      <textarea
        value={value}
        rows={3}
        onChange={(event) => onChange(event.target.value)}
        style={{ ...fieldStyle, resize: "vertical" }}
      />
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
    <label style={{ display: "grid", gap: tokens.space.xs, fontSize: tokens.font.size.sm }}>
      <span style={{ color: tokens.color.muted }}>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} style={fieldStyle}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
