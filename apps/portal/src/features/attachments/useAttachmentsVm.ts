import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { storeFetch, uploadFile, UploadStopped, type media } from "@tadas/client";
import { api } from "../../app/api";
import { errorMessage } from "../../app/errorMessage";
import { mediaCalls, useAttachments, useRemoveAttachment } from "../../queries/attachments";
import { keys } from "../../queries/keys";
import { notify } from "../../store/notices";
import { humanSize } from "../settings/storageModel";
import { attachmentRow } from "./attachmentsModel";
import { downloadAttachment, saveBlob, uploadAttachment, type DownloadEffects, type UploadEffects } from "./transfer";

const uploadEffects: UploadEffects = {
  start: mediaCalls.start,
  send: (file, fileId, contentType) => uploadFile(api, file, { fileId, contentType }),
};

const downloadEffects: DownloadEffects = {
  issueDownload: mediaCalls.issueDownload,
  fetchFromStore: (url) => storeFetch(url),
  save: saveBlob,
};

export interface Uploading {
  key: string;
  name: string;
  size: string;
  /** The file the person picked, kept so a stopped upload can go on. */
  file: File;
  /** Set while the upload stands stopped: the id it goes on under, which
   * sends only the parts the store does not hold. */
  stoppedId?: string;
}

export function useAttachmentsVm(taskId: string) {
  const queryClient = useQueryClient();
  const attachments = useAttachments(taskId);
  const remove = useRemoveAttachment();
  const [uploading, setUploading] = useState<Uploading[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const files = useMemo(() => attachments.data?.items ?? [], [attachments.data]);
  const rows = useMemo(() => files.map(attachmentRow), [files]);
  // The list and the usage both carry the file; a push from another window
  // refreshes them the same way.
  const refresh = () => void queryClient.invalidateQueries({ queryKey: keys.files.all });

  const put = (key: string, change: Partial<Uploading>) =>
    setUploading((now) => now.map((u) => (u.key === key ? { ...u, ...change } : u)));
  const drop = (key: string) => setUploading((now) => now.filter((u) => u.key !== key));

  /** One upload, new or going on: gone from the list once stored, or kept
   * with its id when it stopped after it started. */
  const send = async (key: string, file: File, stoppedId?: string) => {
    put(key, { stoppedId: undefined });
    try {
      await uploadAttachment(taskId, file, uploadEffects, stoppedId);
      drop(key);
    } catch (caught) {
      if (caught instanceof UploadStopped) {
        notify(`${file.name} stopped uploading. Resume sends the rest.`);
        put(key, { stoppedId: caught.fileId });
      } else {
        notify(errorMessage(caught, `Could not attach ${file.name}.`));
        drop(key);
      }
    } finally {
      refresh();
    }
  };

  const upload = async (picked: readonly File[]) => {
    await Promise.all(
      picked.map(async (file) => {
        const key = crypto.randomUUID();
        setUploading((now) => [...now, { key, name: file.name, size: humanSize(file.size), file }]);
        await send(key, file);
      }),
    );
  };

  const resume = async (key: string) => {
    const stopped = uploading.find((u) => u.key === key);
    if (stopped?.stoppedId) await send(key, stopped.file, stopped.stoppedId);
  };

  const byId = (id: string): media.FileView | undefined => files.find((f) => f.id === id);

  const download = async (id: string) => {
    const file = byId(id);
    if (!file) return;
    setBusyId(id);
    try {
      await downloadAttachment(file, downloadEffects);
    } catch (caught) {
      notify(errorMessage(caught, `Could not download ${file.name}.`));
    } finally {
      setBusyId(null);
    }
  };

  const destroy = async (id: string) => {
    setBusyId(id);
    try {
      await remove.mutateAsync({ taskId, fileId: id });
    } catch (caught) {
      notify(errorMessage(caught, "Could not remove the file."));
    } finally {
      setBusyId(null);
      refresh();
    }
  };

  return {
    loading: attachments.isLoading,
    rows,
    hasMore: attachments.data?.next_cursor != null,
    uploading,
    busyId,
    upload,
    resume,
    dismiss: drop,
    download,
    destroy,
  };
}

export type AttachmentsVm = ReturnType<typeof useAttachmentsVm>;
