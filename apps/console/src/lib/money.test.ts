import { describe, expect, it } from 'vitest';
import {
  estimateUsd,
  formatExactUsd,
  formatSignedExactUsd,
  formatUsdAmount,
  formatUsdRate,
  parseUsdAmount,
  parseUsdRate,
  sumUsdAmounts,
} from './money';

describe('fixed-scale money', () => {
  it('parses and sums amounts without numeric conversion', () => {
    expect(parseUsdAmount('0.000000000001')).toBe(1n);
    expect(sumUsdAmounts(['0.1', '0.2'])).toBe(300_000_000_000n);
  });

  it('calculates token costs directly in pico-USD', () => {
    expect(estimateUsd([{ tokens: 1, rate: '0.000001' }])).toBe(1n);
    expect(
      estimateUsd([
        { tokens: 500, rate: '2' },
        { tokens: 300, rate: '0.25' },
      ]),
    ).toBe(1_075_000_000n);
  });

  it('rounds only for display', () => {
    expect(formatUsdAmount(parseUsdAmount('0.00995'), 4)).toBe('0.0100');
    expect(formatUsdRate(parseUsdRate('0.3'))).toBe('0.30');
    expect(formatUsdRate(parseUsdRate('3.75'))).toBe('3.75');
  });

  it('preserves nonzero sub-cent amounts and signed deltas', () => {
    expect(formatExactUsd('0.000000000444')).toBe('$0.000000000444');
    expect(formatExactUsd('1.234560000001')).toBe('$1.234560000001');
    expect(formatExactUsd('0')).toBe('$0.0000');
    expect(formatSignedExactUsd('-0.000000000444')).toBe('-$0.000000000444');
    expect(formatSignedExactUsd('1.25')).toBe('+$1.2500');
  });
});
