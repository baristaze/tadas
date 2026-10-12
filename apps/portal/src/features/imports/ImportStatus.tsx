// The imports the page follows, one card each, newest first: a line of how
// far each is, pushed as the worker moves it; when one parks on the plan, the
// upgrade and its Resume; while one runs or waits, its Cancel, which asks
// first; when one ends, what it did, until dismissed.
import { Button, Card, LinkButton, Muted } from "../../design/kit";
import { tokens } from "../../design/tokens";
import type { ImportCard } from "./importModel";
import type { ImportVm } from "./useImportVm";

export function ImportStatus({ vm }: { vm: ImportVm }) {
  if (vm.cards.length === 0) return null;
  return (
    <div aria-label="Imports" style={{ display: "grid", gap: tokens.space.sm }}>
      {vm.cards.map((card) => (
        <ImportStatusCard key={card.id} card={card} vm={vm} />
      ))}
    </div>
  );
}

function ImportStatusCard({ card, vm }: { card: ImportCard; vm: ImportVm }) {
  return (
    <Card>
      <div role="status" aria-live="polite" style={{ display: "grid", gap: tokens.space.sm }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: tokens.space.md,
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontWeight: card.failed ? 600 : undefined, color: card.failed ? tokens.color.danger : undefined }}>
            {card.headline}
          </span>
          <ImportActions card={card} vm={vm} />
        </div>
        {card.running && card.percent !== null ? (
          <div className="tadas-progress" aria-hidden="true">
            <div className="tadas-progress-bar" style={{ width: `${card.percent}%` }} />
          </div>
        ) : null}
        {asking(card, vm) ? (
          <Muted>Cancel this import? The tasks it made stay, and the rest of the file is not imported.</Muted>
        ) : card.parkedOnThePlan ? (
          <Muted>
            {vm.canUpgrade
              ? "A higher plan resumes it by itself. Or finish some tasks, then Resume."
              : "Ask an owner or an admin to upgrade, or finish some tasks, then Resume."}
          </Muted>
        ) : null}
        {card.skipped.length > 0 && !card.running ? (
          <details>
            <summary style={{ cursor: "pointer", color: tokens.color.muted }}>Skipped rows</summary>
            <ul style={{ margin: `${tokens.space.xs} 0 0`, paddingLeft: tokens.space.lg }}>
              {card.skipped.map((line) => (
                <li key={line}>
                  <Muted>{line}</Muted>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </Card>
  );
}

/** Whether the card asks before its import is cancelled: only while there
 * is still something to cancel. */
function asking(card: ImportCard, vm: ImportVm): boolean {
  return (card.running || card.parked) && vm.askingCancel(card.id);
}

const actionsStyle = { display: "flex", gap: tokens.space.sm, alignItems: "center", flexShrink: 0 } as const;

/** Everything a person can do to one import, in one place: the upgrade and
 * Resume while it waits on the plan, Cancel while it runs or waits, and
 * Dismiss once it ended. Every Resume has a Cancel beside it. */
function ImportActions({ card, vm }: { card: ImportCard; vm: ImportVm }) {
  if (asking(card, vm)) {
    return (
      <div style={actionsStyle}>
        <Button tone="danger" onClick={() => void vm.cancel(card.id)} disabled={vm.cancelling(card.id)}>
          Cancel import
        </Button>
        <Button tone="plain" onClick={vm.keepImport}>
          Keep it
        </Button>
      </div>
    );
  }
  return (
    <div style={actionsStyle}>
      {card.parkedOnThePlan && vm.canUpgrade ? <Button onClick={vm.upgrade}>See plans</Button> : null}
      {card.parked ? (
        <Button tone="plain" onClick={() => void vm.resume(card.id)} disabled={vm.resuming(card.id)}>
          Resume
        </Button>
      ) : null}
      {card.running || card.parked ? (
        <Button tone="plain" onClick={() => vm.askCancel(card.id)}>
          Cancel
        </Button>
      ) : null}
      {card.ended ? <LinkButton onClick={() => vm.dismiss(card.id)}>Dismiss</LinkButton> : null}
    </div>
  );
}
