/* SANDBOXHOT 前端：纯静态，读取 data/*.json，在浏览器里完成筛选、搜索与排序。 */
(function () {
  "use strict";
  var DOMAINS = {
    academic: { name: "学术论文", blurb: "预印本、期刊与会议论文：LLM 社会仿真、生成式智能体、兵棋推演、人类行为模拟、沙盒环境与评测基准。" },
    application: { name: "实际应用", blurb: "政府、军事、城市、公共卫生、金融、供应链、教育与企业决策中的 AI 推演和仿真实践。" },
    business: { name: "商业", blurb: "做 AI 仿真与合成用户的公司、融资、收购和商业产品。" },
    game: { name: "游戏", blurb: "AI NPC、智能体驱动的模拟/沙盒游戏与游戏化推演。" },
    platform: { name: "平台工具", blurb: "开源框架、模拟器、平台与基础设施。" }
  };
  var ORDER = ["academic", "application", "business", "game", "platform"];
  var state = { items: [], meta: null, digests: { daily: [], weekly: [] }, byId: {} };
  var app = document.getElementById("app");

  // ---------- 主题 ----------
  var themeBtn = document.getElementById("theme");
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  var saved = store("sbh-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  themeBtn.addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme");
    var dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    var next = dark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    store("sbh-theme", next);
  });

  // ---------- 工具 ----------
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : "#"; }
  function dt(s) { var d = new Date(s); return isNaN(d) ? null : d; }
  function ago(s) {
    var d = dt(s); if (!d) return "";
    var h = (Date.now() - d) / 36e5;
    if (h < 1) return "刚刚"; if (h < 24) return Math.floor(h) + " 小时前";
    if (h < 24 * 7) return Math.floor(h / 24) + " 天前";
    return (d.getMonth() + 1) + "月" + d.getDate() + "日" + (d.getFullYear() !== new Date().getFullYear() ? " " + d.getFullYear() : "");
  }
  function ageDays(it) { var d = dt(it.added); return d ? (Date.now() - d) / 864e5 : 999; }
  function rank(it) {
    var w = (it.domain === "academic" || it.domain === "application") ? 6 : 0;
    return it.score + w - Math.min(30, ageDays(it) * 2.5) + (it.cluster_size - 1) * 4;
  }
  function getJSON(u) { return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }

  function md(src) {
    var lines = esc(src || "").split(/\r?\n/), out = [], inList = false;
    function inline(t) {
      return t.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    }
    lines.forEach(function (l) {
      var m;
      if (/^\s*[-*] /.test(l)) { if (!inList) { out.push("<ul>"); inList = true; } out.push("<li>" + inline(l.replace(/^\s*[-*] /, "")) + "</li>"); return; }
      if (inList) { out.push("</ul>"); inList = false; }
      if ((m = l.match(/^(#{1,4}) (.*)/))) { var n = Math.max(2, Math.min(3, m[1].length)); out.push("<h" + n + ">" + inline(m[2]) + "</h" + n + ">"); }
      else if (l.trim()) out.push("<p>" + inline(l) + "</p>");
    });
    if (inList) out.push("</ul>");
    return out.join("");
  }

  // ---------- 卡片 ----------
  var BRIEF = [["question", "问题"], ["setup", "仿真设定"], ["method", "方法"], ["findings", "发现"], ["validation", "验证"], ["limits", "局限"], ["reuse", "可复用"]];
  function card(it, opts) {
    opts = opts || {};
    var d = DOMAINS[it.domain] || DOMAINS.application;
    var title = it.title_zh || it.title;
    var x = it.extra || {};
    var meta = [];
    meta.push('<span>' + esc(it.source) + "</span>");
    if (x.venue && x.venue !== "arXiv") meta.push("<span>" + esc(x.venue) + "</span>");
    if (it.authors && it.authors.length) meta.push("<span>" + esc(it.authors.slice(0, 3).join(", ")) + (it.authors.length > 3 ? " 等" : "") + "</span>");
    meta.push('<span title="' + esc(it.published) + '">' + ago(it.published) + "</span>");
    if (x.stars) meta.push("<span>★ " + x.stars + "</span>");
    if (x.points) meta.push("<span>▲ " + x.points + "</span>");
    if (it.cluster_size > 1) meta.push("<span>" + it.cluster_size + " 个来源</span>");
    var links = ['<a href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener">原文</a>'];
    if (x.pdf) links.push('<a href="' + esc(safeUrl(x.pdf)) + '" target="_blank" rel="noopener">PDF</a>');
    if (x.discussion) links.push('<a href="' + esc(safeUrl(x.discussion)) + '" target="_blank" rel="noopener">讨论</a>');
    var brief = "";
    if (it.brief && !opts.compact) {
      brief = '<details class="brief"><summary>▸ 速读卡</summary><dl>' + BRIEF.map(function (b) {
        var v = it.brief[b[0]]; return v && v !== "未说明" ? "<dt>" + b[1] + "</dt><dd>" + esc(v) + "</dd>" : "";
      }).join("") + "</dl></details>";
    }
    var tags = (it.tags || []).map(function (t) { return '<span class="tag">' + esc(t) + "</span>"; }).join("");
    return '<article class="card">' +
      '<div class="row"><span class="pill d-' + esc(it.domain) + '">' + d.name + "</span>" +
      '<span class="meta">' + (it.ai ? "" : '<span class="flag" title="模型暂未处理，按关键词规则入选">规则</span>') +
      '<span class="score' + (it.score >= 75 ? " hi" : "") + '" title="编辑评分 0–100">' + it.score + "</span></span></div>" +
      '<h3><a href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener">' + esc(title) + "</a></h3>" +
      (it.title_zh ? '<div class="orig">' + esc(it.title) + "</div>" : "") +
      (opts.compact ? "" : '<p class="sum">' + esc(it.summary) + "</p>") +
      (tags && !opts.compact ? '<div class="meta">' + tags + "</div>" : "") +
      '<div class="meta">' + meta.join("") + "<span>" + links.join(" · ") + "</span></div>" +
      brief + "</article>";
  }

  function leads() { return state.items.filter(function (it) { return it.lead; }); }

  // ---------- 页面 ----------
  function sectionHead(dom, title, link) {
    return '<div class="sec-head"><div class="sec-title d-' + dom + '" ><span class="bar"></span><h2>' + title + "</h2></div>" +
      (link ? '<a href="' + link + '">查看全部 →</a>' : "") + "</div>";
  }

  function home() {
    var all = leads();
    var recent = all.filter(function (it) { return ageDays(it) <= 10; });
    var hot = recent.slice().sort(function (a, b) { return b.hot - a.hot; }).slice(0, 8);
    var dg = state.digests.daily[0] || state.digests.weekly[0];
    var counts = (state.meta && state.meta.counts) || {};
    var h = "";
    h += "<h1>AI 智能体 × 沙盘推演 / 仿真</h1>";
    h += '<p class="lede">' + esc((state.meta && state.meta.site && state.meta.site.tagline) || "") + "</p>";
    if (!all.length) h += '<div class="empty" style="margin-bottom:18px">还没有内容。首次运行 <code>scripts\\update.ps1</code> 后，这里会出现精选资讯。</div>';
    h += '<div class="hero"><section class="panel md">' +
      (dg ? md(dg.markdown) + '<p class="muted" style="font-size:12.5px;margin-top:10px">' + esc(dg.label) + (dg.ai ? "" : " · 规则版") + ' · <a href="#/digest">往期日报 →</a></p>'
        : '<h2>日报</h2><p class="muted">凑够当天的条目后会自动生成日报。</p>') +
      "</section>" +
      '<section class="panel"><h2>热点</h2>' +
      (hot.length ? '<ol class="hot-list">' + hot.map(function (it) {
        return '<li><div><a href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener">' + esc(it.title_zh || it.title) + '</a><div class="meta"><span class="pill d-' + it.domain + '">' + DOMAINS[it.domain].name + "</span><span>" + esc(it.source) + "</span><span>" + ago(it.added) + "</span></div></div></li>";
      }).join("") + "</ol>" : '<p class="muted">暂无</p>') +
      '<div class="stats">' + ORDER.map(function (k) {
        return '<a class="stat" href="#/d/' + k + '"><b>' + (counts[k] || 0) + "</b><span>" + DOMAINS[k].name + "</span></a>";
      }).join("") + "</div></section></div>";

    function top(dom, n) {
      return all.filter(function (it) { return it.domain === dom; }).sort(function (a, b) { return rank(b) - rank(a); }).slice(0, n);
    }
    // 学术、应用两栏优先且篇幅更大
    [["academic", 6], ["application", 6]].forEach(function (p) {
      var list = top(p[0], p[1]);
      h += sectionHead(p[0], DOMAINS[p[0]].name, "#/d/" + p[0]);
      h += list.length ? '<div class="grid">' + list.map(function (it) { return card(it); }).join("") + "</div>" : '<div class="empty">暂无内容</div>';
    });
    h += '<div class="grid3">';
    ["business", "game", "platform"].forEach(function (dom) {
      var list = top(dom, 4);
      h += "<div>" + sectionHead(dom, DOMAINS[dom].name, "#/d/" + dom) + '<div class="list">' +
        (list.length ? list.map(function (it) { return card(it, { compact: true }); }).join("") : '<div class="empty">暂无内容</div>') + "</div></div>";
    });
    h += "</div>";
    app.innerHTML = h;
  }

  var view = { q: "", days: "30", sort: "rank", tag: "", limit: 40 };
  function domainPage(dom) {
    var d = DOMAINS[dom];
    if (!d) return notFound();
    var base = leads().filter(function (it) { return it.domain === dom; });
    var tagCount = {};
    base.forEach(function (it) { (it.tags || []).forEach(function (t) { tagCount[t] = (tagCount[t] || 0) + 1; }); });
    var topTags = Object.keys(tagCount).sort(function (a, b) { return tagCount[b] - tagCount[a]; }).slice(0, 14);
    app.innerHTML = '<h1 class="d-' + dom + '">' + d.name + "</h1>" + '<p class="lede">' + d.blurb + "</p>" +
      '<div class="toolbar"><input id="q" type="search" placeholder="搜索标题、摘要、作者、标签…" value="' + esc(view.q) + '">' +
      '<select id="days"><option value="7">近 7 天</option><option value="30">近 30 天</option><option value="90">近 90 天</option><option value="all">全部</option></select>' +
      '<select id="sort"><option value="rank">综合排序</option><option value="new">最新</option><option value="score">最高分</option><option value="hot">最热</option></select></div>' +
      (topTags.length ? '<div class="chips">' + topTags.map(function (t) { return '<button class="chip' + (view.tag === t ? " on" : "") + '" data-tag="' + esc(t) + '">' + esc(t) + " " + tagCount[t] + "</button>"; }).join("") + "</div>" : "") +
      '<div id="res"></div>';
    var q = document.getElementById("q"), days = document.getElementById("days"), sort = document.getElementById("sort");
    days.value = view.days; sort.value = view.sort;
    function draw() {
      var words = view.q.toLowerCase().split(/\s+/).filter(Boolean);
      var list = base.filter(function (it) {
        if (view.days !== "all" && ageDays(it) > +view.days) return false;
        if (view.tag && (it.tags || []).indexOf(view.tag) < 0) return false;
        if (!words.length) return true;
        var hay = [it.title, it.title_zh, it.summary, it.source, (it.authors || []).join(" "), (it.tags || []).join(" ")].join(" ").toLowerCase();
        return words.every(function (w) { return hay.indexOf(w) >= 0; });
      });
      var key = { rank: rank, score: function (it) { return it.score; }, hot: function (it) { return it.hot; }, new: function (it) { return +dt(it.added) || 0; } }[view.sort];
      list.sort(function (a, b) { return key(b) - key(a); });
      var res = document.getElementById("res");
      res.innerHTML = list.length ? '<p class="muted" style="font-size:13px">共 ' + list.length + " 条</p>" + '<div class="list">' + list.slice(0, view.limit).map(function (it) { return card(it); }).join("") + "</div>" +
        (list.length > view.limit ? '<button class="more" id="more">再看 40 条</button>' : "") : '<div class="empty">没有符合条件的内容，试试放宽时间范围。</div>';
      var more = document.getElementById("more");
      if (more) more.onclick = function () { view.limit += 40; draw(); };
    }
    q.oninput = function () { view.q = q.value; view.limit = 40; draw(); };
    days.onchange = function () { view.days = days.value; view.limit = 40; draw(); };
    sort.onchange = function () { view.sort = sort.value; draw(); };
    Array.prototype.forEach.call(app.querySelectorAll(".chip"), function (b) {
      b.onclick = function () { view.tag = view.tag === b.dataset.tag ? "" : b.dataset.tag; domainPage(dom); };
    });
    draw();
  }

  function digestPage(kind, key) {
    var all = [].concat(state.digests.daily.map(function (d) { d.kind = "daily"; return d; }), state.digests.weekly.map(function (d) { d.kind = "weekly"; return d; }));
    if (!all.length) { app.innerHTML = '<h1>日报</h1><div class="empty">还没有日报。每天第一次运行时会为前一天生成日报，每周一生成上周周报。</div>'; return; }
    var cur = all.filter(function (d) { return d.kind === kind && d.key === key; })[0] || state.digests.daily[0] || state.digests.weekly[0];
    var nav = function (list, k) {
      return list.slice(0, 30).map(function (d) { return '<a class="chip' + (d === cur ? " on" : "") + '" href="#/digest/' + k + "/" + d.key + '" style="text-decoration:none">' + esc(k === "daily" ? d.key.slice(5) : d.key) + "</a>"; }).join("");
    };
    app.innerHTML = "<h1>日报与周报</h1>" +
      (state.digests.weekly.length ? '<p class="muted" style="margin:6px 0">周报</p><div class="digest-nav">' + nav(state.digests.weekly, "weekly") + "</div>" : "") +
      '<p class="muted" style="margin:6px 0">日报</p><div class="digest-nav">' + nav(state.digests.daily, "daily") + "</div>" +
      '<article class="panel md prose">' + md(cur.markdown) + '<p class="muted" style="font-size:12.5px">' + esc(cur.label) + (cur.ai ? "" : " · 规则版（模型可用后自动改写）") + "</p></article>";
  }

  function sourcesPage() {
    var s = (state.meta && state.meta.sources) || [];
    var G = { aihot: "AIHOT 同款信源", academic: "学术（重点）", community: "社区 / 应用", platform: "平台 / 开源", game: "游戏" };
    app.innerHTML = "<h1>信源</h1><p class=\"lede\">与 AIHOT 开源仓库的示范信源保持一致，并加强学术论文与实际应用。所有内容先经本地关键词预筛，再由大模型精选。</p>" +
      '<div class="panel table-wrap"><table class="src"><thead><tr><th>信源</th><th>分组</th><th>类型</th><th>入选</th><th>状态</th></tr></thead><tbody>' +
      s.map(function (x) {
        return "<tr><td>" + (x.home ? '<a href="' + esc(safeUrl(x.home)) + '" target="_blank" rel="noopener">' + esc(x.name) + "</a>" : esc(x.name)) +
          (x.query ? '<div class="q">' + esc(x.query) + "</div>" : "") + "</td><td>" + esc(G[x.group] || x.group) + "</td><td>" + esc(x.kind) +
          "</td><td>" + x.items + "</td><td>" + (!x.enabled ? "停用" : x.ok ? "正常" : "上次失败") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function aboutPage() {
    app.innerHTML = '<div class="prose"><h1>关于 SANDBOXHOT</h1>' +
      "<p>SANDBOXHOT 收集“利用 AI 智能体做沙盘推演、仿真、模拟”的资讯，覆盖学术论文、实际应用、商业、游戏与平台工具，并且更重视前两者。</p>" +
      "<h2>它怎么工作</h2><ul>" +
      "<li><b>采集</b>：AIHOT 同款 RSS 信源，加上 arXiv、OpenAlex 的定向检索，以及 Hacker News、GitHub。</li>" +
      "<li><b>本地预筛</b>：关键词打分，必须同时涉及“仿真/推演”和“AI/智能体”才会进入下一步，不消耗任何模型额度。</li>" +
      "<li><b>批量精选</b>：一次请求同时完成相关性判断、领域分类、0–100 打分和中文标题摘要；学术与应用的入选门槛更低。</li>" +
      "<li><b>速读卡</b>：高分论文和应用额外生成结构化速读卡（问题、仿真设定、方法、发现、验证、局限、可复用点）。</li>" +
      "<li><b>聚簇与热度</b>：多个来源报道的同一件事合并显示，热度按独立来源数与时间衰减计算。</li>" +
      "<li><b>日报/周报</b>：每天为前一天、每周一为上一周生成编辑版综述。</li></ul>" +
      "<p>标有“规则”的条目暂时只经过关键词预筛，之后有模型额度时会自动改写。分数是编辑评估的阅读价值，不代表内容真伪；请以原文为准。</p>" +
      '<p class="muted">网站为纯静态页面，没有账号、评论和追踪。框架思路参考 <a href="https://github.com/KKKKhazix/AIHOT" target="_blank" rel="noopener">AIHOT</a>。</p></div>';
  }

  function notFound() { app.innerHTML = '<div class="empty">页面不存在，<a href="#/">回首页</a></div>'; }

  function route() {
    var h = location.hash.replace(/^#\/?/, "").split("/");
    var r = h[0] || "home";
    Array.prototype.forEach.call(document.querySelectorAll("#nav a"), function (a) {
      var on = a.dataset.r === (r === "d" ? h[1] : r);
      a.classList.toggle("on", on);
    });
    if (r === "home") home();
    else if (r === "d") { if (view.dom !== h[1]) { view = { q: "", days: "30", sort: "rank", tag: "", limit: 40, dom: h[1] }; } domainPage(h[1]); }
    else if (r === "digest") digestPage(h[1], h[2]);
    else if (r === "sources") sourcesPage();
    else if (r === "about") aboutPage();
    else notFound();
    if (r !== "d") window.scrollTo(0, 0);
  }

  Promise.all([getJSON("data/items.json"), getJSON("data/meta.json"), getJSON("data/digests.json").catch(function () { return { daily: [], weekly: [] }; })])
    .then(function (res) {
      state.items = res[0].items || [];
      state.meta = res[1];
      state.digests = { daily: res[2].daily || [], weekly: res[2].weekly || [] };
      var g = dt(state.meta.generated);
      document.getElementById("foot-meta").textContent = "更新于 " + (g ? g.toLocaleString("zh-CN", { hour12: false }) : "—") + " · 收录 " + state.items.length + " 条";
      window.addEventListener("hashchange", route);
      route();
    })
    .catch(function (e) {
      app.innerHTML = '<div class="empty">数据加载失败：' + esc(e.message) + "<br>本地预览请运行 <code>python run.py serve</code>，不要直接双击打开 HTML 文件。</div>";
    });
})();
