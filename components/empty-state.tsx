export function EmptyState({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-xl border border-dashed border-white/15 bg-zinc-900/40 px-4 py-8 text-center">
      <p className="text-sm font-medium text-zinc-200">{title}</p>
      <p className="mt-1 text-sm text-zinc-500">{body}</p>
    </div>
  );
}
