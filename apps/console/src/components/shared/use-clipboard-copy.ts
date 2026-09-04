import { useEffect, useRef, useState, type RefObject } from 'react';

export type ClipboardCopyStatus = 'idle' | 'copying' | 'copied' | 'manual';

function selectCopyTarget(target: HTMLElement) {
  target.focus({ preventScroll: true });
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
    target.select();
    return;
  }
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(target);
  selection?.removeAllRanges();
  selection?.addRange(range);
}

export function useClipboardCopy(value: string, targetRef: RefObject<HTMLElement | null>, resetKey: unknown = value) {
  const [result, setResult] = useState<{ resetKey: unknown; status: ClipboardCopyStatus }>({ resetKey, status: 'idle' });
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const copyAttempt = useRef(0);
  const status = result.resetKey === resetKey ? result.status : 'idle';

  useEffect(
    () => () => {
      copyAttempt.current += 1;
      clearTimeout(copyTimer.current);
    },
    [resetKey],
  );

  const copy = async () => {
    const attempt = ++copyAttempt.current;
    clearTimeout(copyTimer.current);
    setResult({ resetKey, status: 'copying' });
    try {
      if (!navigator.clipboard) throw new Error('Clipboard API unavailable');
      await navigator.clipboard.writeText(value);
    } catch {
      if (copyAttempt.current !== attempt) return;
      const target = targetRef.current;
      if (target) selectCopyTarget(target);
      setResult({ resetKey, status: 'manual' });
      return;
    }
    if (copyAttempt.current !== attempt) return;
    setResult({ resetKey, status: 'copied' });
    copyTimer.current = setTimeout(() => setResult({ resetKey, status: 'idle' }), 2_000);
  };

  return { copy, status };
}
