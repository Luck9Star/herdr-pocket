/** A camera result cannot update a newer or hidden pairing attempt. */
export function scanCurrent(start,current) {
  return start.revision===current.revision && start.request===current.request &&
    !!current.request && current.showingRemote && !current.hidden && !current.pending;
}
