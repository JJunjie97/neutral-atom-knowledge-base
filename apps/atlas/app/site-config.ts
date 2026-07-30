const basePath = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL ?? "").replace(/\/$/, "");

function normalizePath(path: string): string {
  if (!path || path === "/") return "/";
  return path.startsWith("/") ? path : `/${path}`;
}

/** Return a path that works both at localhost root and under a GitHub Pages repo path. */
export function publicUrl(path: string): string {
  const normalizedPath = normalizePath(path);
  if (normalizedPath === "/") return basePath || "/";
  return `${basePath}${normalizedPath}`;
}

/** Return an absolute URL for Open Graph metadata when Pages supplies its base URL. */
export function absoluteUrl(path: string): string {
  const normalizedPath = normalizePath(path);
  return siteUrl ? `${siteUrl}${normalizedPath}` : publicUrl(normalizedPath);
}
