const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');

function render(text){
  const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'outside-only'});
  dom.window.eval(fs.readFileSync(path.join(__dirname,'..','extension','reply-format.js'),'utf8'));
  const node=dom.window.JobAssistantReply.render(text);
  dom.window.document.body.append(node);
  return {dom,node};
}

test('headings, emphasis, lists, paragraphs and single line breaks share compact spacing',()=>{
  const {dom,node}=render('## 建议\n\n\n第一行\n第二行\n\n- **准备**材料\n- 核对经历\n\n结束');
  assert.equal(node.querySelectorAll('h4').length,1);
  assert.equal(node.querySelectorAll('p').length,2);
  assert.equal(node.querySelectorAll('br').length,1);
  assert.equal(node.querySelectorAll('li').length,2);
  assert.equal(node.querySelector('strong').textContent,'准备');
  assert.equal(node.querySelectorAll('br + br').length,0);
  dom.window.close();
});

test('source HTML stays text and creates no active image, link or script',()=>{
  const {dom,node}=render('<img src=x onerror=alert(1)> **安全** [站点](https://example.com) ![图](https://example.com/a.png)');
  assert.equal(node.querySelectorAll('img,a,script').length,0);
  assert.match(node.textContent,/<img src=x onerror=alert\(1\)>/);
  assert.match(node.textContent,/https:\/\/example.com/);
  dom.window.close();
});

test('long URLs are preserved as text for CSS wrapping',()=>{
  const url='https://example.com/'+ 'x'.repeat(300);
  const {dom,node}=render(url);
  assert.equal(node.textContent,url);
  assert.equal(node.querySelector('a'),null);
  dom.window.close();
});

test('numbered lists keep their starting number',()=>{
  const {dom,node}=render('3. 第三步\n4. 第四步');
  assert.equal(node.querySelector('ol').start,3);
  assert.equal(node.querySelectorAll('li').length,2);
  dom.window.close();
});
