import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/elements';

type RefreshableReport = { isFetching: boolean; refetch: () => unknown };

export function ReportRefreshButton({ queries }: { queries: readonly RefreshableReport[] }) {
  const [clicked, setClicked] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const refresh = () => {
    clearTimeout(timer.current);
    setClicked(true);
    timer.current = setTimeout(() => setClicked(false), 500);
    queries.forEach((query) => void query.refetch());
  };
  const refreshing = clicked || queries.some((query) => query.isFetching);

  return (
    <Button variant="outline" size="sm" aria-busy={refreshing} onClick={refresh}>
      <RefreshCw className={refreshing ? 'h-3.5 w-3.5 motion-safe:animate-spin' : 'h-3.5 w-3.5'} aria-hidden="true" />
      Refresh
    </Button>
  );
}
