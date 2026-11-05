/** Backgrounding or leaving requires a fresh review, but retains the public response. */
export function invalidatePairReview(sourceReview, preview) {
  sourceReview.checked = false;
  preview.hidden = true;
  return '';
}
