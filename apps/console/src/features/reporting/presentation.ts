import { formatUsdAmount, parseUsdAmount } from '@/lib/money';

function formatAmount(value: bigint) {
  if (value === 0n) return '$0.00';
  const digits = value >= 1_000_000_000_000n ? 2 : value >= 1_000_000n ? 6 : 12;
  return `$${formatUsdAmount(value, digits)}`;
}

export function formatReportCost(amount: string) {
  return formatAmount(parseUsdAmount(amount));
}

export function formatReportCostExact(amount: string) {
  return `$${amount}`;
}

export function formatAverageCost(amount: string, requests: number) {
  if (!requests) return '—';
  const cost = parseUsdAmount(amount);
  const average = cost / BigInt(requests);
  return cost > 0n && average === 0n ? '<$0.000000000001' : formatAmount(average);
}

export function formatChange(current: string, previous: string) {
  const difference = parseUsdAmount(current) - parseUsdAmount(previous);
  if (difference === 0n) return '$0.00';
  return `${difference > 0n ? '+' : '−'}${formatAmount(difference > 0n ? difference : -difference)}`;
}

export function formatShare(amount: string, total: string) {
  const denominator = parseUsdAmount(total);
  if (denominator === 0n) return '—';
  return `${(Number((parseUsdAmount(amount) * 1000n) / denominator) / 10).toFixed(1)}%`;
}
