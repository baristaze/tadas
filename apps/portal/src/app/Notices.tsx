// The transient notices, one banner each, above whatever page is shown.
import { Banner, LinkButton } from "../design/kit";
import { useNoticesStore } from "../store/notices";

export function Notices() {
  const notices = useNoticesStore((s) => s.notices);
  const dismiss = useNoticesStore((s) => s.dismiss);
  if (notices.length === 0) return null;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {notices.map((notice) => (
        <Banner key={notice.id}>
          {notice.message} <LinkButton onClick={() => dismiss(notice.id)}>dismiss</LinkButton>
        </Banner>
      ))}
    </div>
  );
}
