const AMOUNT_SCALE = 12;
const RATE_SCALE = 6;

function parseFixed(value: string, scale: number): bigint {
  const match = /^(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match || (match[2]?.length ?? 0) > scale) throw new Error(`Invalid fixed-point value: ${value}`);
  return BigInt(match[1]) * 10n ** BigInt(scale) + BigInt((match[2] ?? '').padEnd(scale, '0'));
}

function formatFixed(value: bigint, scale: number, maximumFractionDigits: number, minimumFractionDigits = 2): string {
  const discardedDigits = scale - maximumFractionDigits;
  const divisor = 10n ** BigInt(discardedDigits);
  const rounded = (value + divisor / 2n) / divisor;
  const rendered = rounded.toString().padStart(maximumFractionDigits + 1, '0');
  const whole = rendered.slice(0, -maximumFractionDigits) || '0';
  const fraction = rendered.slice(-maximumFractionDigits).replace(/0+$/, '').padEnd(minimumFractionDigits, '0');
  return fraction ? `${whole}.${fraction}` : whole;
}

export const parseUsdAmount = (value: string) => parseFixed(value, AMOUNT_SCALE);
export const parseUsdRate = (value: string) => parseFixed(value, RATE_SCALE);
export const sumUsdAmounts = (values: string[]) => values.reduce((sum, value) => sum + parseUsdAmount(value), 0n);
export const estimateUsd = (buckets: Array<{ tokens: number; rate: string }>) =>
  buckets.reduce((sum, { tokens, rate }) => sum + BigInt(tokens) * parseUsdRate(rate), 0n);
export const formatUsdAmount = (value: bigint, fractionDigits = 4) => formatFixed(value, AMOUNT_SCALE, fractionDigits, fractionDigits);
export const formatUsdRate = (value: bigint) => formatFixed(value, RATE_SCALE, 4);
export const formatUsd = (value: bigint) => `$${formatUsdAmount(value, value >= 1_000_000_000_000n ? 2 : 4)}`;
