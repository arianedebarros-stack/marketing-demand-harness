import { TaskBoard } from "@/components/TaskBoard";

export default async function TasksPage({
  searchParams,
}: {
  searchParams: Promise<{ tarefa?: string }>;
}) {
  const { tarefa } = await searchParams;
  const id = Number(tarefa);
  return <TaskBoard initialTaskId={Number.isInteger(id) && id > 0 ? id : undefined} />;
}
