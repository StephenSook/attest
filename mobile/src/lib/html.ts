/** Escape a value before it enters generated certificate markup.
 *
 * Two of the interpolated fields make this load-bearing rather than defensive
 * habit: the supporting span is verbatim speech from a phone call, and the
 * organization name is caller-supplied. Raw interpolation lets either render
 * as markup, so a document whose entire purpose is attesting to exact wording
 * could display something other than what the transcript holds.
 */
export function esc(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
