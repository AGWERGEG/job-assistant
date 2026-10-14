// Render a small, safe subset of Markdown used by completed chat replies.
// All source content enters the DOM as text nodes; source HTML is never parsed.
(function (global) {
  function inline(parent, source) {
    const pattern = /(\*\*([^*\n]+)\*\*|__([^_\n]+)__|`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\n]+)\))/g;
    let start = 0, match;
    while ((match = pattern.exec(source))) {
      if (match.index > start) parent.append(document.createTextNode(source.slice(start, match.index)));
      if (match[2] || match[3]) {
        const strong = document.createElement('strong');
        strong.textContent = match[2] || match[3];
        parent.append(strong);
      } else if (match[4]) {
        const code = document.createElement('code');
        code.textContent = match[4];
        parent.append(code);
      } else {
        parent.append(document.createTextNode(match[5] + ' (' + match[6] + ')'));
      }
      start = pattern.lastIndex;
    }
    if (start < source.length) parent.append(document.createTextNode(source.slice(start)));
  }

  function renderReply(source) {
    const root = document.createElement('div');
    root.className = 'reply-format';
    const lines = String(source == null ? '' : source).replace(/\r\n?/g, '\n').split('\n');
    let paragraph = [], list = null, listType = '';
    function flushParagraph() {
      if (!paragraph.length) return;
      const p = document.createElement('p');
      paragraph.forEach((line, index) => {
        if (index) p.append(document.createElement('br'));
        inline(p, line);
      });
      root.append(p);
      paragraph = [];
    }
    function closeList() { list = null; listType = ''; }
    for (const raw of lines) {
      const line = raw.trim();
      if (!line) { flushParagraph(); closeList(); continue; }
      const heading = line.match(/^#{1,3}\s+(.+)$/);
      const item = line.match(/^(?:([-*+])\s+|(\d+)[.)]\s+)(.+)$/);
      if (heading) {
        flushParagraph(); closeList();
        const h = document.createElement('h' + Math.min(line.match(/^#+/)[0].length + 2, 5));
        inline(h, heading[1]); root.append(h);
      } else if (item) {
        flushParagraph();
        const type = item[2] ? 'ol' : 'ul';
        if (!list || listType !== type) { list = document.createElement(type); if (type === 'ol') list.start = Number(item[2]); root.append(list); listType = type; }
        const li = document.createElement('li'); inline(li, item[3]); list.append(li);
      } else {
        closeList(); paragraph.push(line);
      }
    }
    flushParagraph();
    return root;
  }
  global.JobAssistantReply = {render: renderReply};
})(window);
