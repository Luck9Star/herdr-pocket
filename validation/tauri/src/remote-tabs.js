/** In-memory view identity. Backend handles and target identity never come from a label. */
export class RemoteTabs {
  #tabs = new Map();
  #active = null;
  #newId;
  #generation = 0;
  constructor(newId = () => crypto.randomUUID()) { this.#newId = newId; }
  get activeId() { return this.#active; }
  list() { return [...this.#tabs.values()]; }
  get(id) { return this.#tabs.get(id) ?? null; }
  create(hostId) {
    if (this.#tabs.size >= 8) throw Error('tab_capacity');
    if (typeof hostId !== 'string' || !hostId) throw Error('invalid_host');
    const id = this.#newId();
    if (typeof id !== 'string' || !id || this.#tabs.has(id)) throw Error('invalid_tab_id');
    const tab = {id, hostId, generation: 0, live: false, target: null, state: 'disconnected', draft: '', unknown: false};
    this.#tabs.set(id, tab);
    if (this.#active === null) this.#active = id;
    return tab;
  }
  select(id) {
    if (!this.#tabs.has(id)) throw Error('tab_missing');
    const previous = this.#active;
    this.#active = id;
    return previous;
  }
  begin(id) {
    const tab = this.get(id);
    if (!tab) throw Error('tab_missing');
    if (!Number.isSafeInteger(this.#generation + 1)) throw Error('generation_exhausted');
    tab.generation = ++this.#generation;
    tab.live = true;
    return Object.freeze({id, generation: tab.generation});
  }
  accepts(token) { return !!token && Number.isSafeInteger(token.generation) && token.generation > 0 && this.get(token.id)?.live === true && this.get(token.id)?.generation === token.generation; }
  invalidate(id) {
    const tab = this.get(id);
    if (!tab) return false;
    if (!Number.isSafeInteger(this.#generation + 1)) throw Error('generation_exhausted');
    tab.generation = ++this.#generation;
    tab.live = false;
    tab.state = 'disconnected';
    return true;
  }
  affected(hostIds) {
    const ids = new Set(hostIds);
    return this.list().filter(tab => ids.has(tab.hostId));
  }
  close(id) {
    if (!this.#tabs.delete(id)) return false;
    if (this.#active === id) this.#active = null;
    return true;
  }
  background() {
    const tabs = this.list();
    for (const tab of tabs) this.invalidate(tab.id);
    return tabs;
  }
}
