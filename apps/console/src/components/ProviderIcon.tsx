import DOMPurify from 'dompurify';

export function ProviderIcon({ markup }: { markup: string }) {
  const sanitized = DOMPurify.sanitize(markup, {
    USE_PROFILES: { svg: true, svgFilters: false },
    FORBID_TAGS: ['foreignObject', 'image', 'script', 'style', 'use'],
    FORBID_ATTR: ['href', 'src', 'style', 'xlink:href'],
  });
  if (!sanitized) return null;
  return <span aria-hidden="true" className="w-4 h-4 shrink-0 [&_svg]:w-full [&_svg]:h-full" dangerouslySetInnerHTML={{ __html: sanitized }} />;
}
