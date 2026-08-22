'use client';

export default function ThinkingCard() {
  return (
    <div className="card flex items-center gap-3 p-5" role="status" aria-live="polite">
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent-500"
            style={{ animationDelay: `${i * 140}ms`, animationDuration: '900ms' }}
          />
        ))}
      </span>
      <span className="text-sm text-slate-500">
        Generating SQL and running it against your data…
      </span>
    </div>
  );
}
