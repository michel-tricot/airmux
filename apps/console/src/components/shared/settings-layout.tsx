import { useState, type ReactNode } from 'react';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/elements';

export function SettingsLayout({ categories, children }: { categories: ReadonlyArray<{ id: string; label: string }>; children: ReactNode }) {
  const [selected, setSelected] = useState<string | null>(null);
  const active = categories.find((category) => category.id === selected)?.id ?? categories[0]?.id;

  if (!active) return null;

  return (
    <Tabs orientation="vertical" value={active} onValueChange={setSelected} className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_13rem]">
      <aside className="lg:col-start-2 lg:row-start-1 lg:sticky lg:top-6">
        <TabsList aria-label="Settings categories" className="h-auto w-full flex-col items-stretch gap-1 bg-transparent p-0">
          {categories.map((category) => (
            <TabsTrigger
              key={category.id}
              value={category.id}
              className="justify-start whitespace-normal px-3 py-2.5 text-left normal-case tracking-normal data-[state=active]:bg-muted data-[state=active]:shadow-none"
            >
              {category.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </aside>
      <div className="min-w-0 lg:col-start-1 lg:row-start-1">{children}</div>
    </Tabs>
  );
}
