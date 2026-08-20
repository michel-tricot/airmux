import { useEffect, useRef, useState, type RefObject } from 'react';

export type ClipboardCopyStatus = 'idle' | 'copied' | 'manual';

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
  const status = result.resetKey === resetKey ? result.status : 'idle';

  useEffect(
    () => () => {
      copyAttempt.current += 1;
      clearTimeout(copyTimer.current);
    },
    [],
  );

  const copy = async () => {
    const attempt = ++copyAttempt.current;
    const copiedValue = value;
    let clipboardWrite: Promise<void> | undefined;
    try {
      clipboardWrite = navigator.clipboard?.writeText(copiedValue);
    } catch {
      clipboardWrite = undefined;
    }
    clearTimeout(copyTimer.current);
    setResult({ resetKey, status: 'copied' });
    copyTimer.current = setTimeout(() => setResult({ resetKey, status: 'idle' }), 2_000);
    try {
      if (!clipboardWrite) throw new Error('Clipboard API unavailable');
      await clipboardWrite;
    } catch {
      if (copyAttempt.current !== attempt) return;
      const target = targetRef.current;
      if (target && legacyCopy(target)) {
        clearTimeout(copyTimer.current);
        setResult({ resetKey, status: 'copied' });
        copyTimer.current = setTimeout(() => setResult({ resetKey, status: 'idle' }), 2_000);
        return;
      }
      clearTimeout(copyTimer.current);
      if (target) selectCopyTarget(target);
      setResult({ resetKey, status: 'manual' });
    }
  };

  return { copy, status };
}
