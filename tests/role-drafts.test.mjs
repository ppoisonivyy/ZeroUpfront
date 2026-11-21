import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import test from 'node:test';
import vm from 'node:vm';

const directory = process.env.ROLE_DRAFT_DIR || new URL('../docs/workspace-review/', import.meta.url).pathname;

// Run the shipped, self-contained scripts against disposable browser storage.
// The small DOM adapter covers the modal controls, page navigation and case output.
function desk(role, id, storage = new Map(), mobile = false) {
  const nodes = new Map();
  const note = {value:'', setCustomValidity(message){this.message=message}, reportValidity(){return !this.message}};
  const reference = {value:''};
  function node(key) {
    if (!nodes.has(key)) nodes.set(key, {
      innerHTML:'', classList:{add(){},remove(){}}, dataset:{}, open:false,
      addEventListener(){}, focus(){}, contains(){return false},
      showModal(){this.open=true}, close(){this.open=false},
      querySelector(selector) {
        if(selector==='#review-note') return this.innerHTML.includes('id="review-note"') ? note : null;
        if(selector==='#review-reference') return this.innerHTML.includes('id="review-reference"') ? reference : null;
        return ['span','.wm-close'].includes(selector)?node(key+selector):null;
      }
    });
    return nodes.get(key);
  }
  const context=vm.createContext({
    STATIC_BUILD:true,URLSearchParams,Intl, Date, setTimeout:()=>1,clearTimeout(){},
    navigator:{},location:{hash:'#case='+id,pathname:'/'+role+'.html'},
    localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
    history:{replaceState(){},pushState(){}},
    window:{addEventListener(){},scrollTo(){}, matchMedia:()=>({matches:mobile,addEventListener(){}})},
    document:{body:{dataset:{role}},addEventListener(){},querySelector:node,querySelectorAll:()=>[],
      getElementById:id=>id.startsWith('workspace-menu')?node(id):null},
  });
  const html=readFileSync(join(directory,role+'.html'),'utf8');
  const scripts=Array.from(html.matchAll(/<script>([\s\S]*?)<\/script>/g),m=>m[1]);
  const bundle=scripts.find(script=>script.includes('function applyLocation()'));
  assert.ok(bundle);
  vm.runInContext(bundle,context);
  const run=code=>vm.runInContext(code,context);
  run('applyLocation()');
  return {run, note, reference, main:()=>node('main').innerHTML,
    body:()=>node('.dialog-body').innerHTML,
    apply:(code='a')=>run('applyEvent(activeModal,'+JSON.stringify(code)+')'),
    source:()=>run('commitSource(activeModal.stage,activeModal.event,activeModal)')};
}

test('unavailable insurer links render no patient, action or document; submission makes the same link available',()=>{
  for(const id of ['Z002','typo','ZU-0248','']){
    const receiver=desk('insurer',id);
    assert.match(receiver.main(),/Case unavailable/);
    assert.doesNotMatch(receiver.main(),/Theo Bennett|data-action="advance"|data-source-action|Guarantee requested/);
    assert.equal(receiver.run('selected()'),undefined);
  }
  const shared=new Map(), sender=desk('hospital','Z002',shared);
  for(const step of ['open-comparison','mark-compared','send']){
    sender.run('sourceAction('+JSON.stringify(step)+',selected())');
    if(step==='send')sender.source();
  }
  assert.equal(desk('insurer','Z002',shared).run('selected().id'),'Z002');
  assert.equal(desk('insurer','ZU-0243').run('selected().name'),'Theo Bennett');
});

test('the insurer question, cited page and hospital reply stay with the same case and packet revision',()=>{
  const shared=new Map(), payer=desk('insurer','ZU-0243',shared);
  payer.run("openAction('query',selected())");
  payer.reference.value='ward';
  payer.note.value='  ';
  payer.apply('0');
  assert.equal(payer.run('selected().stage'),'finalSent');
  payer.note.value='Which services cover this ward night?';
  payer.apply('0');
  const ward=desk('hospital','ZU-0243',shared);
  assert.match(ward.main(),/Which services cover this ward night/);
  ward.run("openAction('advance',selected())");
  assert.match(ward.body(),/Revised estimate · p. 1 · Additional ward night/);
  ward.note.value='Monitoring & supplies <itemized>.';
  ward.apply();
  const reopened=desk('insurer','ZU-0243',shared);
  assert.match(reopened.main(),/Hospital replied · packet r3/);
  assert.match(reopened.main(),/Monitoring &amp; supplies &lt;itemized&gt;/);
  assert.match(reopened.main(),/data-review-reference="ward"/);
  assert.equal(reopened.run('queueAction(selected())'),'Review hospital reply · r3');
  reopened.run("openAction('advance',selected())");
  assert.match(reopened.body(),/GOP-02 · r3/);
  assert.doesNotMatch(desk('insurer','ZU-0246',shared).main(),/Monitoring|Which services cover this ward night/);
});

test('Z002 clarification persists the custom question and reply through role switching and reload',()=>{
  const shared=new Map(), ward=desk('hospital','Z002',shared);
  ward.run("sourceAction('open-comparison',selected());sourceAction('mark-compared',selected());sourceAction('send',selected())");
  ward.source();
  const insurer=desk('insurer','Z002',shared);
  insurer.run("sourceAction('open-review',selected());sourceAction('request-clarification',selected())");
  insurer.note.value='What is included in hospital services?';
  insurer.reference.value='services';
  insurer.source();
  const hospital=desk('hospital','Z002',shared);
  assert.match(hospital.main(),/What is included in hospital services/);
  hospital.run("sourceAction('reply',selected())");
  hospital.note.value='The facility portion includes room and nursing.';
  hospital.source();
  const result=desk('insurer','Z002',shared);
  assert.match(result.main(),/includes room and nursing/);
  assert.match(result.main(),/Hospital replied · packet r3/);
  assert.match(result.main(),/Hospital services, THB 52,000/);
});

test('opening the signature preview preserves the unsigned case until the replacement is confirmed',()=>{
  const shared=new Map(), hospital=desk('hospital','ZU-0248',shared);
  assert.match(hospital.main(),/Orthopaedics/);
  hospital.run("openAction('advance',selected())");
  assert.match(hospital.body(),/Signed replacement on file/);
  assert.equal(hospital.run('selected().stage'),'gap');
  assert.equal(desk('hospital','ZU-0248',shared).run('selected().stage'),'gap');
  hospital.apply();
  assert.equal(desk('hospital','ZU-0248',shared).run('selected().stage'),'recheck');
});

test('legacy questions remain legible; mobile opens the readable original text',()=>{
  const prior={v:1,t:2,added:false,events:{'ZU-0243':'2a'},sourceStage:'compare',sourceLog:[]};
  const state=new Map([['zeroupfront.two-desks.v1',JSON.stringify(prior)]]);
  assert.match(desk('insurer','ZU-0243',state).main(),/Itemize the additional room night/);
  assert.match(desk('hospital','Z002',new Map(),true).main(),/Document text · Page 1/);
});

test('FX handoffs preserve the insurer reference and settle only on confirmed hospital receipt',async()=>{
  const shared=new Map();
  const deskFor=role=>desk(role,'ZU-0243',shared);
  const insurer=deskFor('insurer');
  assert.equal(insurer.run('fxReview().nextAction'),'book');
  assert.match(insurer.run('fxQuotePicker(fxReview())'),/7 days early/);
  assert.match(insurer.run('fxQuotePicker(fxReview())'),/USD 161.59 less/);
  assert.doesNotMatch(insurer.run('fxQuotePicker(fxReview())'),/checked/);
  assert.equal((await insurer.run("fxApply('book_forward',0)")).ok,true);
  const hospital=deskFor('hospital');
  assert.match(hospital.run('fxNextStep(fxReview(),true)'),/Beneficiary credit advice PDF/);
  assert.equal((await hospital.run("fxApply('record_short_credit',1)")).ok,true);
  assert.equal((await hospital.run("fxApply('record_topup',2)")).ok,false);
  assert.equal((await hospital.run("fxApply('record_remittance',2,'wrong desk')")).ok,false);
  assert.equal((await insurer.run("fxApply('record_remittance',2,' INS-T239 ')")).ok,true);
  assert.equal((await insurer.run("fxApply('record_remittance',2,'INS-T239')")).changed,false);
  assert.equal((await insurer.run("fxApply('record_remittance',2,'different')")).ok,false);
  const receivables=deskFor('hospital');
  assert.deepEqual(Array.from(receivables.run('[fxReview().nextAction,fxReview().insurerReference,fxReview().outstandingMinor,fxReview().patientFxMinor]')),
    ['confirm_topup','INS-T239',30000,0]);
  assert.match(receivables.run('fxNextStep(fxReview(),true)'),/Top-up credit advice PDF/);
  assert.match(receivables.run('fxNextStep(fxReview(),true)'),/INS-T239/);
  assert.equal((await receivables.run("fxApply('record_topup',3)")).ok,true);
  assert.equal(deskFor('insurer').run('fxReview().outstandingMinor'),0);
});

test('legacy paid and partial Pattaya ledgers preserve receipts and do not invent remittance evidence',async()=>{
  const s=desk('hospital','ZU-0243');
  const fx=s.run("fxReview({fx:{v:1,events:[['book_spot',1],['record_short_credit',2],['record_topup',3]]}})");
  assert.deepEqual([fx.nextAction,fx.outstandingMinor,fx.remittedAt,fx.credits.length],['complete',0,null,2]);
  const partial=s.run("fxReview({fx:{v:1,events:[['book_spot',1],['record_short_credit',2]]}})");
  assert.deepEqual([partial.nextAction,partial.outstandingMinor,partial.remittedAt],['top_up',30000,null]);
});
