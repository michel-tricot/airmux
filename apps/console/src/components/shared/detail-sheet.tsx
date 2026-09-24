import type { ReactNode } from 'react';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/elements';

export function DetailSheet({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  children: ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto border-border bg-card p-6 sm:max-w-2xl">
        <SheetHeader className="border-b border-border pb-4 pr-8">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription className="break-all">{description}</SheetDescription>
        </SheetHeader>
        {children}
      </SheetContent>
    </Sheet>
  );
}
