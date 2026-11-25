import { DemandWorkspace } from "@/components/DemandWorkspace";

export default async function DemandPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DemandWorkspace requestId={id} />;
}
