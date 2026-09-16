// A minimal component kit over the tokens. Components render; nothing here decides.
import type { CSSProperties, ReactNode } from "react";
import { tokens } from "../tokens";

export function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main
      style={{
        minHeight: "100vh",
        background: tokens.color.bg,
        color: tokens.color.text,
        fontFamily: tokens.font.family,
        fontSize: tokens.font.size.md,
        padding: tokens.space.xl,
      }}
    >
      <h1 style={{ fontSize: tokens.font.size.xl, margin: 0, marginBottom: tokens.space.lg }}>
        {title}
      </h1>
      <div style={{ display: "grid", gap: tokens.space.lg, maxWidth: 880 }}>{children}</div>
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
        padding: tokens.space.lg,
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
}: {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  disabled?: boolean;
  tone?: "accent" | "danger" | "plain";
}) {
  const background =
    tone === "accent" ? tokens.color.accent : tone === "danger" ? tokens.color.danger : "transparent";
  const color = tone === "plain" ? tokens.color.text : tokens.color.accentText;
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
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
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "password";
  autoComplete?: string;
}) {
  return (
    <label style={{ display: "grid", gap: tokens.space.xs, fontSize: tokens.font.size.sm }}>
      <span style={{ color: tokens.color.muted }}>{label}</span>
      <input
        type={type}
        value={value}
        autoComplete={autoComplete}
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
