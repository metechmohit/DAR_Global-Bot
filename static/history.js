/* Browser-only conversation storage. No account, hosted database or extra package. */
(function (root) {
  'use strict';
  const KEY = 'atlas.conversations.v1';
  const copy = value => JSON.parse(JSON.stringify(value));
  function compactResult(result) {
    const saved = copy(result);
    // Property descriptions already live in the search index. Reload them only
    // when opening Details; retain displayed prices/specifications as snapshots.
    saved.records = (saved.records || []).map(record => {
      const item = {...record}; delete item.description; return item;
    });
    delete saved.model;
    saved.notice = saved.notice ? 'temporarily_unavailable' : '';
    return saved;
  }
  class ConversationStore {
    constructor(storage, onError = () => {}) {
      this.storage = storage; this.onError = onError;
      this.data = {version: 1, currentId: null, conversations: []};
      try {
        const saved = this.storage && JSON.parse(this.storage.getItem(KEY) || 'null');
        if (saved && saved.version === 1 && Array.isArray(saved.conversations)) {
          this.data.conversations = saved.conversations.filter(c => c && typeof c.id === 'string' && typeof c.title === 'string' && Array.isArray(c.messages) && c.messages.every(m => m && ((m.role === 'user' && typeof m.content === 'string') || (m.role === 'assistant' && m.result && typeof m.result.answer === 'string') || (m.role === 'error' && typeof m.content === 'string'))));
          this.data.currentId = this.data.conversations.some(c => c.id === saved.currentId) ? saved.currentId : null;
        }
      } catch { this.onError('Saved conversations could not be read. Your current chat will still work.'); }
    }
    save() {
      try {
        if (!this.storage) throw new Error('Storage unavailable');
        this.storage.setItem(KEY, JSON.stringify(this.data));
        return true;
      } catch {
        this.onError('Your browser could not save this conversation. It remains open here; download it before closing the page.');
        return false;
      }
    }
    current() { return this.data.conversations.find(c => c.id === this.data.currentId) || null; }
    list() { return this.data.conversations.filter(c => c.messages.length).slice().sort((a,b) => String(b.updatedAt).localeCompare(String(a.updatedAt))); }
    create() {
      const existing = this.current();
      if (existing && !existing.messages.length) return existing;
      // Empty drafts are not conversation history and can be replaced safely.
      this.data.conversations = this.data.conversations.filter(c => c.messages.length);
      const id = root.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
      const conversation = {id, title: 'New conversation', createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), messages: [], filters: {}};
      this.data.conversations.push(conversation); this.data.currentId = id; this.save(); return conversation;
    }
    select(id) {
      const found = this.data.conversations.find(c => c.id === id);
      if (found) { this.data.currentId = id; this.save(); }
      return found || null;
    }
    addUser(content) {
      const conversation = this.current() || this.create();
      if (!conversation.messages.some(m => m.role === 'user')) conversation.title = content.replace(/\s+/g, ' ').slice(0, 72);
      conversation.messages.push({role: 'user', content});
      conversation.updatedAt = new Date().toISOString(); this.save(); return conversation;
    }
    addAnswer(result) {
      const conversation = this.current() || this.create();
      conversation.messages.push({role: 'assistant', result: compactResult(result)});
      conversation.filters = copy(result.filters || {});
      conversation.updatedAt = new Date().toISOString(); this.save(); return conversation;
    }
    addError(content) {
      const conversation = this.current() || this.create();
      conversation.messages.push({role: 'error', content}); this.save();
    }
    setFilters(filters) {
      const conversation = this.current();
      if (conversation) { conversation.filters = copy(filters); this.save(); }
    }
    remove(id) {
      this.data.conversations = this.data.conversations.filter(c => c.id !== id);
      if (this.data.currentId === id) this.data.currentId = this.list()[0]?.id || null;
      this.save(); return this.current();
    }
    exportCurrent() { return copy(this.current()); }
  }
  root.AtlasHistory = {ConversationStore, KEY};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.AtlasHistory;
})(globalThis);
