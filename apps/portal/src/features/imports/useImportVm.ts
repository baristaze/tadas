import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { uploadFile, UploadStopped } from "@tadas/client";
import { api } from "../../app/api";
import { errorMessage } from "../../app/errorMessage";
import { useBilling } from "../../queries/billing";
import { importCalls, useCancelImport, useRecentImports, useResumeImport } from "../../queries/imports";
import { keys } from "../../queries/keys";
import { useMe } from "../../queries/tenancy";
import { notify } from "../../store/notices";
import { usePreferencesStore } from "../../store/preferences";
import { useUpgradeStore } from "../../store/upgrade";
import { startImport, type ImportEffects } from "./importFlow";
import { activeTasksLimit, importCard, shownImports } from "./importModel";

const effects: ImportEffects = {
  startFile: importCalls.startFile,
  send: (file, fileId, contentType) => uploadFile(api, file, { fileId, contentType }),
  start: importCalls.start,
};

export function useImportVm(canWrite: boolean) {
  const queryClient = useQueryClient();
  const recent = useRecentImports(canWrite);
  const billing = useBilling();
  const resume = useResumeImport();
  const cancel = useCancelImport();
  const orgId = useMe().data?.org.id ?? null;
  const dismissedByOrg = usePreferencesStore((s) => s.dismissedImports);
  const dismissImport = usePreferencesStore((s) => s.dismissImport);
  const pruneDismissed = usePreferencesStore((s) => s.pruneDismissedImports);
  const openUpgrade = useUpgradeStore((s) => s.open);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [picked, setPicked] = useState<File | null>(null);
  // The upload of the picked file that stopped: starting again goes on with it.
  const [stoppedId, setStoppedId] = useState<string | undefined>(undefined);
  const [starting, setStarting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // The import whose Cancel asks before it ends it: a cancel is final.
  const [asking, setAsking] = useState<string | null>(null);
  // An import that ended long before the page opened is not news; one that
  // ends while it is open stays until dismissed.
  const [openedAt] = useState(() => Date.now());

  // A dismissal is kept per org across visits; one whose import is no longer
  // among the recent ones is pruned, so the kept list stays small.
  const items = recent.data?.items;
  useEffect(() => {
    if (orgId !== null && items) pruneDismissed(orgId, items.map((view) => view.id));
  }, [orgId, items, pruneDismissed]);

  const cards = useMemo(() => {
    const dismissed = new Set(orgId === null ? [] : (dismissedByOrg[orgId] ?? []));
    return shownImports(items ?? [], dismissed, openedAt).map(importCard);
  }, [items, orgId, dismissedByOrg, openedAt]);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: keys.imports.all });

  const openDialog = () => {
    setPicked(null);
    setStoppedId(undefined);
    setFailure(null);
    setDialogOpen(true);
  };

  const closeDialog = () => {
    if (!starting) setDialogOpen(false);
  };

  const start = async () => {
    if (!picked || starting) return;
    setStarting(true);
    setFailure(null);
    try {
      await startImport(picked, effects, stoppedId);
      setStoppedId(undefined);
      setDialogOpen(false);
    } catch (caught) {
      if (caught instanceof UploadStopped) {
        setStoppedId(caught.fileId);
        setFailure(`${picked.name} stopped uploading. Start again to send the rest.`);
      } else {
        setFailure(errorMessage(caught, `Could not import ${picked.name}.`));
      }
    } finally {
      setStarting(false);
      refresh();
    }
  };

  const resumeImport = async (id: string) => {
    try {
      await resume.mutateAsync(id);
    } catch (caught) {
      notify(errorMessage(caught, "Could not resume the import."));
    } finally {
      refresh();
    }
  };

  const cancelImport = async (id: string) => {
    try {
      await cancel.mutateAsync(id);
    } catch (caught) {
      notify(errorMessage(caught, "Could not cancel the import."));
    } finally {
      setAsking(null);
      refresh();
    }
  };

  const upgrade = () => {
    if (billing.data) openUpgrade(activeTasksLimit(billing.data));
  };

  return {
    canImport: canWrite,
    dialogOpen,
    openDialog,
    closeDialog,
    picked,
    pick: (file: File | null) => {
      setPicked(file);
      setStoppedId(undefined);
      setFailure(null);
    },
    starting,
    failure,
    start,
    /** Every import the page shows, newest first, one card each. */
    cards,
    /** Whether this import's Resume is on its way. */
    resuming: (id: string) => resume.isPending && resume.variables === id,
    resume: resumeImport,
    /** Whether this import's Cancel waits on the person's yes. */
    askingCancel: (id: string) => asking === id,
    askCancel: (id: string) => setAsking(id),
    keepImport: () => setAsking(null),
    /** Whether this import's cancel is on its way. */
    cancelling: (id: string) => cancel.isPending && cancel.variables === id,
    cancel: cancelImport,
    upgrade,
    canUpgrade: billing.data?.can_manage ?? false,
    dismiss: (id: string) => {
      if (orgId !== null) dismissImport(orgId, id);
    },
  };
}

export type ImportVm = ReturnType<typeof useImportVm>;
