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

function legacyCopy(target: HTMLElement) {
  const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  selectCopyTarget(target);
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } catch {
    copied = false;
  }
  if (copied) {
    window.getSelection()?.removeAllRanges();
    previousFocus?.focus({ preventScroll: true });
  }
  return copied;
}

export function useClipboardCopy(value: string, targetRef: RefObject<HTMLElement | null>, resetKey: unknown = value) {
  const [result, setResult] = useState<{ resetKey: unknown; status: ClipboardCopyStatus }>({ resetKey, status: 'idle' });
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const copyAttempt = useRef(0);
  const copyingKey = useRef<{ resetKey: unknown } | null>(null);
  const status = result.resetKey === resetKey ? result.status : 'idle';

  useEffect(
    () => () => {
      copyAttempt.current += 1;
      copyingKey.current = null;
      clearTimeout(copyTimer.current);
    },
    [],
  );

  const copy = async () => {
    if (copyingKey.current?.resetKey === resetKey) return;
    copyingKey.current = { resetKey };
    const attempt = ++copyAttempt.current;
    const copiedValue = value;
    clearTimeout(copyTimer.current);
    setResult({ resetKey, status: 'copying' });
    let copied = false;
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
      await navigator.clipboard.writeText(copiedValue);
      copied = true;
    } catch {
      const target = targetRef.current;
      copied = target ? legacyCopy(target) : false;
    }
    if (copyAttempt.current !== attempt) return;
    copyingKey.current = null;
    if (!copied) {
      const target = targetRef.current;
      if (target) selectCopyTarget(target);
      setResult({ resetKey, status: 'manual' });
      return;
    }
    setResult({ resetKey, status: 'copied' });
    copyTimer.current = setTimeout(() => setResult({ resetKey, status: 'idle' }), 2_000);
  };

  return { copy, status };
}
