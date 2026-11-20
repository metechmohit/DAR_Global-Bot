const test = require('node:test');
const assert = require('node:assert/strict');
const {ConversationStore, KEY} = require('../static/history.js');
function memory() { const data = new Map(); return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)}; }
const response = {answer:'AIDA evidence [S1]',records:[{id:'abc',title:'AIDA',price:123,description:'Very long original source text'}],sources:[{id:'S1',url:'https://darglobal.co.uk/landing-page/aida'}],filters:{city:'Muscat'},model:'internal-provider',notice:'',mode:'ai'};
test('new conversation retains previous conversation, cards and filters across reload',()=>{
  const storage=memory(); const first=new ConversationStore(storage);const id=first.create().id;
  first.addUser('Tell me about AIDA');first.addAnswer(response);first.create();
  assert.equal(first.list().length,1);
  const restored=new ConversationStore(storage);restored.select(id);
  assert.equal(restored.current().messages[1].result.answer,response.answer);
  assert.equal(restored.current().messages[1].result.records[0].price,123);
  assert.deepEqual(restored.current().filters,{city:'Muscat'});
});
test('provider metadata and large source descriptions are not persisted',()=>{
  const storage=memory();const store=new ConversationStore(storage);store.create();store.addUser('AIDA');store.addAnswer(response);
  const saved=JSON.parse(storage.getItem(KEY)).conversations[0].messages[1].result;
  assert.equal(saved.model,undefined);assert.equal(saved.records[0].description,undefined);assert.equal(saved.sources[0].id,'S1');
});
test('deleting a conversation does not delete other conversations',()=>{
  const store=new ConversationStore(memory());const a=store.create().id;store.addUser('One');store.create();store.addUser('Two');store.remove(a);
  assert.equal(store.list().length,1);assert.equal(store.current().title,'Two');
});
test('storage quota failure keeps chat in memory and reports failure',()=>{
  let warnings=[];const store=new ConversationStore({getItem:()=>null,setItem:()=>{throw new Error('quota');}},m=>warnings.push(m));
  store.create();store.addUser('Do not lose this conversation');
  assert.equal(store.current().messages[0].content,'Do not lose this conversation');assert.ok(warnings.length);
});
test('malformed saved history is ignored safely',()=>{
  const storage=memory();storage.setItem(KEY,'not json');let errors=0;const store=new ConversationStore(storage,()=>errors++);
  assert.equal(store.current(),null);assert.equal(errors,1);
});
test('multiple new blank conversations do not accumulate empty history entries',()=>{
  const store=new ConversationStore(memory());const first=store.create().id;assert.equal(store.create().id,first);assert.equal(store.list().length,0);
});
