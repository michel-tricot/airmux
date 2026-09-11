import { useState, type ReactNode } from 'react';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/elements';

export function SettingsLayout({
  categories,
  header,
  children,
}: {
  header: ReactNode;
  categories: ReadonlyArray<{ id: string; label: string }>;
  children: ReactNode;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const active = categories.find((category) => category.id === selected)?.id ?? categories[0]?.id;

  if (!active) return null;

  return (
    <Tabs orientation="vertical" value={active} onValueChange={setSelected} className="grid min-h-full lg:grid-cols-[13rem_minmax(0,1fr)]">
      <aside className="border-b border-border bg-sidebar lg:border-b-0 lg:border-r">
        <div className="flex h-14 items-center border-b border-border px-5 font-mono text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Settings
        </div>
        <div className="p-4 lg:sticky lg:top-0">
          <TabsList aria-label="Settings categories" className="h-auto w-full flex-col items-stretch gap-1 bg-transparent p-0">
            {categories.map((category) => (
              <TabsTrigger
                key={category.id}
                value={category.id}
                className="justify-start whitespace-normal rounded-md border-l-2 border-transparent px-3 py-2.5 text-left text-[11px] text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground data-[state=active]:border-primary data-[state=active]:bg-sidebar-accent data-[state=active]:text-sidebar-accent-foreground data-[state=active]:shadow-none"
              >
                {category.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </aside>
      <div className="min-w-0 px-4 py-6 sm:p-8">
        <div className="mx-auto max-w-6xl space-y-6">
          {header}
          {children}
        </div>
      </div>
    </Tabs>
  );
}
