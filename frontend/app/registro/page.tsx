import { AuditLog } from "@/components/AuditLog";

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<{ demanda?: string }>;
}) {
  const { demanda } = await searchParams;
  return <AuditLog key={demanda ?? "todas"} requestId={demanda || undefined} />;
}
