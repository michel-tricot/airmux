import { useState } from 'react';
import { addDays, addMonths, format, isSameDay, isSameMonth, isValid, parseISO, startOfMonth, startOfWeek } from 'date-fns';
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react';
import { Button, Input, Label } from '@/components/ui/elements';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export function ReportingDatePicker({
  id,
  label,
  value,
  onValueChange,
}: {
  id: string;
  label: string;
  value: string;
  onValueChange: (value: string) => void;
}) {
  const parsedDate = parseISO(value);
  const selectedDate = isValid(parsedDate) ? parsedDate : undefined;
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(() => startOfMonth(selectedDate ?? new Date()));
  const [draft, setDraft] = useState(value);
  const [error, setError] = useState(false);
  const firstDay = startOfWeek(month);
  const days = Array.from({ length: 42 }, (_, index) => addDays(firstDay, index));

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (nextOpen) {
          setMonth(startOfMonth(selectedDate ?? new Date()));
          setDraft(value);
          setError(false);
        }
        setOpen(nextOpen);
      }}
    >
      <DialogTrigger asChild>
        <Button
          id={id}
          variant="outline"
          className="h-9 w-full justify-between px-3 text-left text-sm font-normal normal-case tracking-normal"
          aria-label={`Choose ${label.toLowerCase()}${selectedDate ? `, ${format(selectedDate, 'MMMM d, yyyy')}` : ''}`}
        >
          <span className="font-mono">{selectedDate ? format(selectedDate, 'yyyy-MM-dd') : 'Choose date'}</span>
          <CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground" />
        </Button>
      </DialogTrigger>
      <DialogContent className="w-[calc(100%-2rem)] max-w-sm gap-4 border-border bg-card p-4 text-card-foreground">
        <DialogHeader className="space-y-1">
          <DialogTitle className="text-base">{label}</DialogTitle>
          <DialogDescription>Select a date or enter one as YYYY-MM-DD.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            const date = parseISO(draft);
            if (!/^\d{4}-\d{2}-\d{2}$/.test(draft) || !isValid(date) || format(date, 'yyyy-MM-dd') !== draft) {
              setError(true);
              return;
            }
            onValueChange(draft);
            setOpen(false);
          }}
        >
          <Label htmlFor={`${id}-entry`}>Enter date</Label>
          <div className="flex gap-2">
            <Input
              id={`${id}-entry`}
              aria-label="Date in YYYY-MM-DD format"
              aria-invalid={error}
              aria-describedby={error ? `${id}-error` : undefined}
              inputMode="numeric"
              placeholder="YYYY-MM-DD"
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setError(false);
              }}
            />
            <Button type="submit" variant="secondary" className="shrink-0">
              Apply date
            </Button>
          </div>
          {error && (
            <p id={`${id}-error`} role="alert" className="text-xs text-destructive">
              Enter a valid date as YYYY-MM-DD.
            </p>
          )}
        </form>
        <div className="flex items-center justify-between">
          <Button variant="ghost" size="icon" aria-label="Previous month" onClick={() => setMonth((current) => addMonths(current, -1))}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="font-mono text-sm font-semibold">{format(month, 'MMMM yyyy')}</span>
          <Button variant="ghost" size="icon" aria-label="Next month" onClick={() => setMonth((current) => addMonths(current, 1))}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        <div className="grid grid-cols-7 gap-1 text-center">
          {weekdays.map((weekday) => (
            <span key={weekday} className="py-2 font-mono text-xs text-muted-foreground">
              {weekday}
            </span>
          ))}
          {days.map((day) => {
            const selected = selectedDate && isSameDay(day, selectedDate);
            return (
              <Button
                key={format(day, 'yyyy-MM-dd')}
                variant="ghost"
                aria-label={`${format(day, 'MMMM d, yyyy')}${selected ? ', selected' : ''}`}
                className={cn(
                  'h-9 min-h-0 w-full p-0 text-sm font-normal normal-case tracking-normal',
                  !isSameMonth(day, month) && 'text-muted-foreground/50',
                  selected && 'bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground',
                )}
                onClick={() => {
                  onValueChange(format(day, 'yyyy-MM-dd'));
                  setOpen(false);
                }}
              >
                {format(day, 'd')}
              </Button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
