import { NewRequest } from "@/components/NewRequest";

export default function NewRequestPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Nova demanda</h1>
        <p className="text-sm text-slate-600">
          Descreva o pedido do seu jeito. O harness pergunta só o que faltar para o briefing.
        </p>
      </div>
      <NewRequest />
    </div>
  );
}
