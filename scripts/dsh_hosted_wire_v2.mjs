/** Retired URL image transport. Current DSH uses the inline v3/v4 adapters. */
function removed() {
  throw new Error('Compressed-context image hosting has been removed; use inline data:image payloads.');
}
export const guardedFetch = removed;
export const pythonBridge = removed;
if (process.env.ACL_HOSTED_DSH_LEDGER) removed();
