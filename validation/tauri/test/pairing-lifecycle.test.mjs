import test from 'node:test';
import assert from 'node:assert/strict';
import { invalidatePairReview } from '../src/pairing-lifecycle.js';

test('leaving clears response approval while retaining the public response for review', () => {
  const review = { checked: true }, preview = { hidden: false }, response = { value: 'public response' };
  let acceptedPreview = 'public response';
  acceptedPreview = invalidatePairReview(review, preview);
  assert.equal(acceptedPreview, '');
  assert.equal(review.checked, false);
  assert.equal(preview.hidden, true);
  assert.equal(response.value, 'public response');
});
