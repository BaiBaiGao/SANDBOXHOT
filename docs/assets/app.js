/* SANDBOXHOT 前端：纯静态，读取 data/*.json，在浏览器里完成筛选、搜索与排序。 */
(function () {
  "use strict";
  var DOMAINS = {
    academic: { name: "学术论文", blurb: "预印本、期刊与会议论文：LLM 社会仿真、生成式智能体、兵棋推演、人类行为模拟、沙盒环境与评测基准。" },
    application: { name: "实际应用", blurb: "政府、军事、城市交通、公共卫生、应急管理、金融、供应链与企业决策中的 AI 推演和仿真实践，也包括用真实数据做案例推演的论文。" },
    business: { name: "商业", blurb: "合成用户与合成样本、AI 市场调研、数字孪生与仿真平台相关的公司、融资、合作、合同和新产品。" },
    game: { name: "游戏", blurb: "AI NPC、智能体驱动的模拟/沙盒游戏与游戏化推演。" },
    platform: { name: "平台工具", blurb: "开源框架、模拟器、平台与基础设施。" }
  };
  var ORDER = ["academic", "application", "business", "game", "platform"];
  var VALID = {
    real_data: ["真实数据校准", "与真实世界数据对比或校准"],
    human_experiment: ["真人对照", "与真人实验或问卷结果对照"],
    benchmark: ["基准评测", "只在基准或指标上评测"],
    none: ["未验证", "材料中没有验证仿真结果"]
  };
  var RES = { code: "代码", data: "数据集", benchmark: "基准", model: "模型", demo: "演示", project: "项目主页" };
  var BRIEF = [["question", "问题"], ["setup", "仿真设定"], ["method", "方法"], ["findings", "发现"], ["validation", "验证"], ["limits", "局限"], ["reuse", "可复用"]];
  var state = { items: [], meta: null, digests: { daily: [], weekly: [] }, byId: {}, topics: [], topicBy: {}, shards: {}, research: null, resources: null };
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
  function when(it) { var p = dt(it.published), a = dt(it.added); return p && (!a || p <= a) ? p : a; }
  function ago(s) {
    var d = s instanceof Date ? s : dt(s); if (!d) return "";
    var h = (Date.now() - d) / 36e5;
    if (h < 1) return "刚刚"; if (h < 24) return Math.floor(h) + " 小时前";
    if (h < 24 * 7) return Math.floor(h / 24) + " 天前";
    return (d.getMonth() + 1) + "月" + d.getDate() + "日" + (d.getFullYear() !== new Date().getFullYear() ? " " + d.getFullYear() : "");
  }
  function ymd(s) { var d = dt(s); return d ? d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2) : ""; }
  function ageDays(it) { var d = when(it); return d ? (Date.now() - d) / 864e5 : 999; }
  function rank(it) {
    var w = (it.domain === "academic" || it.domain === "application") ? 6 : 0;
    return it.score + w - Math.min(30, ageDays(it) * 2.5) + (it.cluster_size - 1) * 4 + (it.read ? 2 : 0);
  }
  function getJSON(u) { return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }
  function shardOf(id) { var c = (id || "0").charAt(0).toLowerCase(); return /[0-9a-f]/.test(c) ? c : "0"; }
  function loadDetail(id) {
    var c = shardOf(id);
    if (!state.shards[c]) state.shards[c] = getJSON("data/details/" + c + ".json").catch(function () { return {}; });
    return state.shards[c].then(function (s) { return s[id] || {}; });
  }

  function md(src) {
    var lines = esc(src || "").split(/\r?\n/), out = [], list = false, table = null;
    function inline(t) {
      return t.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    }
    function closeList() { if (list) { out.push("</ul>"); list = false; } }
    function closeTable() {
      if (!table) return;
      var rows = table.filter(function (r) { return !/^\s*\|?\s*:?-{2,}/.test(r); }).map(function (r) {
        return r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map(function (c) { return inline(c.trim()); });
      });
      if (rows.length) {
        out.push('<div class="table-wrap"><table class="mdt"><thead><tr>' + rows[0].map(function (c) { return "<th>" + c + "</th>"; }).join("") + "</tr></thead><tbody>" +
          rows.slice(1).map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div>");
      }
      table = null;
    }
    lines.forEach(function (l) {
      var m;
      if (/^\s*\|.*\|\s*$/.test(l)) { closeList(); (table = table || []).push(l); return; }
      closeTable();
      if (/^\s*[-*] /.test(l)) { if (!list) { out.push("<ul>"); list = true; } out.push("<li>" + inline(l.replace(/^\s*[-*] /, "")) + "</li>"); return; }
      closeList();
      if ((m = l.match(/^(#{1,4}) (.*)/))) { var n = Math.max(2, Math.min(4, m[1].length)); out.push("<h" + n + ">" + inline(m[2]) + "</h" + n + ">"); }
      else if (l.trim()) out.push("<p>" + inline(l) + "</p>");
    });
    closeList(); closeTable();
    return out.join("");
  }

  // ---------- 卡片 ----------
  function topicChips(it) {
    return (it.topics || []).map(function (s) { var t = state.topicBy[s]; return t ? '<a class="tag tlink" href="#/t/' + s + '">' + esc(t.name) + "</a>" : ""; }).join("");
  }
  function validBadge(v) { var x = VALID[v]; return x ? '<span class="vbadge v-' + v + '" title="' + esc(x[1]) + '">' + x[0] + "</span>" : ""; }
  function card(it, opts) {
    opts = opts || {};
    var d = DOMAINS[it.domain] || DOMAINS.application;
    var title = it.title_zh || it.title;
    var x = it.extra || {};
    var meta = ['<span>' + esc(it.source) + "</span>"];
    if (x.venue && x.venue !== "arXiv") meta.push("<span>" + esc(x.venue) + "</span>");
    if (it.authors && it.authors.length && !opts.compact) meta.push("<span>" + esc(it.authors.slice(0, 3).join(", ")) + (it.authors.length > 3 ? " 等" : "") + "</span>");
    meta.push('<span title="' + esc(it.published) + '">' + ago(when(it)) + "</span>");
    if (x.stars) meta.push("<span>★ " + x.stars + "</span>");
    if (x.points) meta.push("<span>▲ " + x.points + "</span>");
    if (it.cluster_size > 1) meta.push("<span>" + it.cluster_size + " 个来源</span>");
    var links = ['<a href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener">原文</a>'];
    if (x.pdf) links.push('<a href="' + esc(safeUrl(x.pdf)) + '" target="_blank" rel="noopener">PDF</a>');
    if (x.discussion) links.push('<a href="' + esc(safeUrl(x.discussion)) + '" target="_blank" rel="noopener">讨论</a>');
    var marks = (it.applied ? '<span class="mark">真实场景应用</span>' : "") + (it.read ? '<span class="mark">精读</span>' : "") + (it.brief ? '<span class="mark">速读卡</span>' : "") + (it.res ? '<span class="mark">资源 ' + it.res + "</span>" : "");
    return '<article class="card">' +
      '<div class="row"><span class="meta"><span class="pill d-' + esc(it.domain) + '">' + d.name + "</span>" + validBadge(it.validation) + "</span>" +
      '<span class="meta">' + (it.ai ? "" : '<span class="flag" title="模型暂未处理，按关键词规则入选">规则</span>') +
      '<span class="score' + (it.score >= 75 ? " hi" : "") + '" title="编辑评分 0–100">' + it.score + "</span></span></div>" +
      '<h3><a href="#/i/' + esc(it.id) + '">' + esc(title) + "</a></h3>" +
      (it.title_zh && !opts.compact ? '<div class="orig">' + esc(it.title) + "</div>" : "") +
      (opts.compact ? "" : '<p class="sum">' + esc(it.summary) + "</p>") +
      (it.why && !opts.compact ? '<p class="why"><b>为什么值得看</b>' + esc(it.why) + "</p>" : "") +
      (!opts.compact && (it.topics || []).length ? '<div class="meta">' + topicChips(it) + "</div>" : "") +
      '<div class="meta">' + meta.join("") + "<span>" + links.join(" · ") + "</span>" + (opts.compact ? "" : marks) + "</div>" +
      "</article>";
  }
  function leads() { return state.items.filter(function (it) { return it.lead; }); }
  // “实际应用”板块同时收录标了真实场景应用（applied）的论文等
  function inDomain(it, dom) { return it.domain === dom || (dom === "application" && it.applied); }
  function sectionHead(cls, title, link, linkText) {
    return '<div class="sec-head"><div class="sec-title ' + cls + '"><span class="bar"></span><h2>' + title + "</h2></div>" +
      (link ? '<a href="' + link + '">' + (linkText || "查看全部 →") + "</a>" : "") + "</div>";
  }

  // ---------- 首页 ----------
  function home() {
    var all = leads();
    var recent = all.filter(function (it) { return ageDays(it) <= 10; });
    var hot = recent.slice().sort(function (a, b) { return b.hot - a.hot; }).slice(0, 8);
    var picks = all.filter(function (it) { return ageDays(it) <= 4 && it.why; }).sort(function (a, b) { return rank(b) - rank(a); }).slice(0, 3);
    var dg = state.digests.daily[0] || state.digests.weekly[0];
    var counts = (state.meta && state.meta.counts) || {};
    var h = "<h1>AI 智能体 × 沙盘推演 / 仿真</h1>";
    h += '<p class="lede">' + esc((state.meta && state.meta.site && state.meta.site.tagline) || "") + "</p>";
    if (!all.length) h += '<div class="empty" style="margin-bottom:18px">还没有内容。首次运行后，这里会出现精选资讯。</div>';
    if (picks.length) {
      h += sectionHead("", "今日必读", "#/digest", "看日报 →") + '<div class="picks">' + picks.map(function (it, i) {
        return '<a class="pick" href="#/i/' + esc(it.id) + '"><span class="n">' + (i + 1) + '</span><span><b>' + esc(it.title_zh || it.title) + "</b><em>" + esc(it.why) + "</em></span></a>";
      }).join("") + "</div>";
    }
    h += '<div class="hero"><section class="panel md">' +
      (dg ? md(dg.markdown) + '<p class="muted small">' + esc(dg.label) + (dg.ai ? "" : " · 规则版") + ' · <a href="#/digest">往期日报 →</a></p>'
        : '<h2>日报</h2><p class="muted">凑够当天的条目后会自动生成日报。</p>') +
      "</section>" +
      '<section class="panel"><h2>热点</h2>' +
      (hot.length ? '<ol class="hot-list">' + hot.map(function (it) {
        return '<li><div><a href="#/i/' + esc(it.id) + '">' + esc(it.title_zh || it.title) + '</a><div class="meta"><span class="pill d-' + it.domain + '">' + DOMAINS[it.domain].name + "</span><span>" + esc(it.source) + "</span><span>" + ago(when(it)) + "</span></div></div></li>";
      }).join("") + "</ol>" : '<p class="muted">暂无</p>') +
      '<div class="stats">' + ORDER.map(function (k) {
        return '<a class="stat" href="#/d/' + k + '"><b>' + (counts[k] || 0) + "</b><span>" + DOMAINS[k].name + "</span></a>";
      }).join("") + "</div></section></div>";

    var tps = state.topics.filter(function (t) { return t.count; });
    if (tps.length) {
      h += sectionHead("", "按主题追踪", "#/topics") + '<div class="chips">' + tps.map(function (t) {
        return '<a class="chip" href="#/t/' + t.slug + '">' + esc(t.name) + " <span class=\"muted\">" + t.count + "</span></a>";
      }).join("") + "</div>";
    }
    function top(dom, n) {
      return all.filter(function (it) { return inDomain(it, dom); }).sort(function (a, b) { return rank(b) - rank(a); }).slice(0, n);
    }
    [["academic", 6], ["application", 6]].forEach(function (p) {
      var list = top(p[0], p[1]);
      h += sectionHead("d-" + p[0], DOMAINS[p[0]].name, "#/d/" + p[0]);
      h += list.length ? '<div class="grid">' + list.map(function (it) { return card(it); }).join("") + "</div>" : '<div class="empty">暂无内容</div>';
    });
    h += '<div id="home-research"></div>';
    h += '<div class="grid3">';
    ["business", "game", "platform"].forEach(function (dom) {
      var list = top(dom, 4);
      h += "<div>" + sectionHead("d-" + dom, DOMAINS[dom].name, "#/d/" + dom) + '<div class="list">' +
        (list.length ? list.map(function (it) { return card(it, { compact: true }); }).join("") : '<div class="empty">暂无内容</div>') + "</div></div>";
    });
    h += "</div>";
    h += '<a class="author-strip" href="#/about"><span class="avatar" aria-hidden="true">B</span><span><b>作者 Bianco</b>' +
      '<span class="muted">同济大学 × 米兰理工大学双学位博士生，研究用 LLM 多智能体推演极端情况下的人群行为。欢迎交流 →</span></span></a>';
    app.innerHTML = h;
    loadResearch().then(function (reps) {
      var el = document.getElementById("home-research");
      if (!el || !reps.length) return;
      el.innerHTML = sectionHead("", "专题研究", "#/research") + '<div class="grid">' + reps.slice(0, 2).map(reportCard).join("") + "</div>";
    });
  }

  // ---------- 列表页（领域 / 主题共用） ----------
  var view = { q: "", days: "90", sort: "rank", tag: "", limit: 40, key: "" };
  function listing(base, key, redraw) {
    if (view.key !== key) view = { q: "", days: key.indexOf("t:") === 0 ? "all" : "90", sort: "rank", tag: "", limit: 40, key: key };
    var tagCount = {};
    base.forEach(function (it) { (it.tags || []).forEach(function (t) { tagCount[t] = (tagCount[t] || 0) + 1; }); });
    var topTags = Object.keys(tagCount).sort(function (a, b) { return tagCount[b] - tagCount[a]; }).slice(0, 14);
    var h = '<div class="toolbar"><input id="q" type="search" placeholder="搜索标题、摘要、作者、标签…" value="' + esc(view.q) + '">' +
      '<select id="days"><option value="7">近 7 天</option><option value="30">近 30 天</option><option value="90">近 90 天</option><option value="365">近一年</option><option value="all">全部（含历史回填）</option></select>' +
      '<select id="sort"><option value="rank">综合排序</option><option value="new">最新</option><option value="score">最高分</option><option value="hot">最热</option></select></div>' +
      (topTags.length ? '<div class="chips">' + topTags.map(function (t) { return '<button class="chip' + (view.tag === t ? " on" : "") + '" data-tag="' + esc(t) + '">' + esc(t) + " " + tagCount[t] + "</button>"; }).join("") + "</div>" : "") +
      '<div id="res"></div>';
    return {
      html: h, bind: function () {
        var q = document.getElementById("q"), days = document.getElementById("days"), sort = document.getElementById("sort");
        days.value = view.days; sort.value = view.sort;
        function draw() {
          var words = view.q.toLowerCase().split(/\s+/).filter(Boolean);
          var list = base.filter(function (it) {
            if (view.days !== "all" && ageDays(it) > +view.days) return false;
            if (view.tag && (it.tags || []).indexOf(view.tag) < 0) return false;
            if (!words.length) return true;
            var hay = [it.title, it.title_zh, it.summary, it.why, it.source, (it.authors || []).join(" "), (it.tags || []).join(" ")].join(" ").toLowerCase();
            return words.every(function (w) { return hay.indexOf(w) >= 0; });
          });
          var k = { rank: rank, score: function (it) { return it.score; }, hot: function (it) { return it.hot; }, new: function (it) { return +when(it) || 0; } }[view.sort];
          list.sort(function (a, b) { return k(b) - k(a); });
          var res = document.getElementById("res");
          res.innerHTML = list.length ? '<p class="muted small">共 ' + list.length + " 条</p>" + '<div class="list">' + list.slice(0, view.limit).map(function (it) { return card(it); }).join("") + "</div>" +
            (list.length > view.limit ? '<button class="more" id="more">再看 40 条</button>' : "") : '<div class="empty">没有符合条件的内容，试试放宽时间范围。</div>';
          var more = document.getElementById("more");
          if (more) more.onclick = function () { view.limit += 40; draw(); };
        }
        q.oninput = function () { view.q = q.value; view.limit = 40; draw(); };
        days.onchange = function () { view.days = days.value; view.limit = 40; draw(); };
        sort.onchange = function () { view.sort = sort.value; draw(); };
        Array.prototype.forEach.call(app.querySelectorAll(".chip[data-tag]"), function (b) {
          b.onclick = function () { view.tag = view.tag === b.dataset.tag ? "" : b.dataset.tag; redraw(); };
        });
        draw();
      }
    };
  }
  function domainPage(dom) {
    var d = DOMAINS[dom];
    if (!d) return notFound();
    var l = listing(leads().filter(function (it) { return inDomain(it, dom); }), "d:" + dom, function () { domainPage(dom); });
    app.innerHTML = '<h1 class="d-' + dom + '">' + d.name + "</h1>" + '<p class="lede">' + d.blurb + "</p>" + l.html;
    l.bind();
  }

  // ---------- 主题 ----------
  function topicsPage() {
    app.innerHTML = "<h1>主题</h1><p class=\"lede\">按研究方向追踪。每个主题每周由长文模型写一段研判，档案积累到一定规模后会生成横纵专题报告。</p>" +
      '<div class="grid">' + state.topics.map(function (t) {
        return '<a class="card tcard" href="#/t/' + t.slug + '"><div class="row"><h3>' + esc(t.name) + '</h3><span class="score">' + t.count + "</span></div>" +
          '<p class="sum">' + esc(t.definition) + '</p><div class="meta"><span>近 30 天 ' + t.count_30d + " 条</span>" +
          (t.analysis ? "<span>研判更新于 " + ago(t.analysis.created) + "</span>" : "<span>研判待生成</span>") + "</div></a>";
      }).join("") + "</div>";
  }
  function topicPage(slug) {
    var t = state.topicBy[slug];
    if (!t) return notFound();
    var base = leads().filter(function (it) { return (it.topics || []).indexOf(slug) >= 0; });
    var l = listing(base, "t:" + slug, function () { topicPage(slug); });
    app.innerHTML = '<p class="crumb"><a href="#/topics">主题</a> /</p><h1>' + esc(t.name) + '</h1><p class="lede">' + esc(t.definition) + "</p>" +
      (t.analysis ? '<section class="panel md prose analysis"><p class="eyebrow">主题研判 · ' + ymd(t.analysis.created) + "</p>" + md(t.analysis.markdown) + "</section>" : "") +
      '<div id="topic-reports"></div>' + sectionHead("", "收录条目") + l.html;
    l.bind();
    loadResearch().then(function (reps) {
      var mine = reps.filter(function (r) { return r.topic === slug; });
      var el = document.getElementById("topic-reports");
      if (el && mine.length) el.innerHTML = sectionHead("", "专题研究", "#/research") + '<div class="grid">' + mine.slice(0, 2).map(reportCard).join("") + "</div>";
    });
  }

  // ---------- 专题研究 ----------
  function loadResearch() {
    if (!state.research) state.research = getJSON("data/research.json").then(function (d) { return d.reports || []; }).catch(function () { return []; });
    return state.research;
  }
  function plain(mdText, n) { return (mdText || "").replace(/^#+ .*$/gm, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[*|#>-]/g, " ").replace(/\s+/g, " ").trim().slice(0, n); }
  function reportCard(r) {
    var one = (r.markdown.match(/\*\*一句话结论\*\*[：:]?\s*([^\n]+)/) || [])[1];
    return '<a class="card rcard" href="#/research/' + esc(r.key) + '"><p class="eyebrow">横纵专题 · ' + esc(r.topic_name || "") + " · " + ymd(r.created) + "</p><h3>" + esc(r.title) + '</h3><p class="sum">' + esc(plain(one || r.markdown, 140)) + "…</p>" +
      '<div class="meta"><span>基于 ' + (r.item_ids || []).length + " 条档案</span>" + (r.span ? "<span>" + esc(r.span[0]) + " 至 " + esc(r.span[1]) + "</span>" : "") + "</div></a>";
  }
  function researchPage(key) {
    app.innerHTML = '<p class="muted">加载中…</p>';
    loadResearch().then(function (reps) {
      if (key) {
        var r = reps.filter(function (x) { return x.key === key; })[0];
        if (!r) return notFound();
        var refs = (r.item_ids || []).map(function (id) { return state.byId[id]; }).filter(Boolean);
        app.innerHTML = '<p class="crumb"><a href="#/research">专题研究</a> / <a href="#/t/' + esc(r.topic) + '">' + esc(r.topic_name || "") + "</a></p>" +
          '<article class="panel md prose report">' + md(r.markdown) +
          '<p class="muted small">生成于 ' + ymd(r.created) + " · 基于本站收录的 " + (r.item_ids || []).length + " 条档案" + (r.span ? "（" + esc(r.span[0]) + " 至 " + esc(r.span[1]) + "）" : "") +
          "。档案只覆盖本站收录范围，不是完整的文献综述；引用前请核对原文。</p></article>" +
          (refs.length ? sectionHead("", "参考条目（" + refs.length + "）") + '<div class="list">' + refs.slice().sort(function (a, b) { return b.score - a.score; }).map(function (it) { return card(it, { compact: true }); }).join("") + "</div>" : "");
        window.scrollTo(0, 0);
        return;
      }
      app.innerHTML = "<h1>专题研究</h1><p class=\"lede\">用“横纵分析法”写的长篇研究：纵轴梳理一个方向是怎么走到今天的，横轴对比今天的主要路线和框架，最后在交汇处给出判断。每周更新一到三篇。</p>" +
        (reps.length ? '<div class="grid">' + reps.map(reportCard).join("") + "</div>" : '<div class="empty">还没有专题报告。某个主题的档案积累到一定数量后会自动生成。</div>');
    });
  }

  // ---------- 资源库 ----------
  var rview = { type: "", q: "" };
  function resourcesPage() {
    app.innerHTML = '<p class="muted">加载中…</p>';
    if (!state.resources) state.resources = getJSON("data/resources.json").then(function (d) { return d.resources || []; }).catch(function () { return []; });
    state.resources.then(function (rs) {
      var counts = {};
      rs.forEach(function (r) { counts[r.type] = (counts[r.type] || 0) + 1; });
      app.innerHTML = "<h1>资源库</h1><p class=\"lede\">从入选论文和项目里整理出的代码、数据集、基准和模型。链接都来自原文，没有凭空补充。</p>" +
        '<div class="toolbar"><input id="rq" type="search" placeholder="搜索资源或论文…" value="' + esc(rview.q) + '"></div>' +
        '<div class="chips"><button class="chip' + (rview.type ? "" : " on") + '" data-t="">全部 ' + rs.length + "</button>" +
        Object.keys(RES).filter(function (k) { return counts[k]; }).map(function (k) { return '<button class="chip' + (rview.type === k ? " on" : "") + '" data-t="' + k + '">' + RES[k] + " " + counts[k] + "</button>"; }).join("") + "</div>" +
        '<div id="rlist"></div>';
      function draw() {
        var w = rview.q.toLowerCase();
        var list = rs.filter(function (r) { return (!rview.type || r.type === rview.type) && (!w || (r.name + " " + r.title + " " + r.url).toLowerCase().indexOf(w) >= 0); });
        document.getElementById("rlist").innerHTML = list.length ? '<div class="panel table-wrap"><table class="src"><thead><tr><th>资源</th><th>类型</th><th>出处</th><th>日期</th></tr></thead><tbody>' +
          list.slice(0, 400).map(function (r) {
            return '<tr><td><a href="' + esc(safeUrl(r.url)) + '" target="_blank" rel="noopener">' + esc(r.name) + '</a><div class="q">' + esc(r.url) + "</div></td><td>" + (RES[r.type] || esc(r.type)) +
              '</td><td><a href="#/i/' + esc(r.item) + '">' + esc(r.title) + "</a></td><td>" + esc(r.published) + "</td></tr>";
          }).join("") + "</tbody></table></div>" : '<div class="empty">暂无资源。模型精读入选内容后，这里会自动积累。</div>';
      }
      document.getElementById("rq").oninput = function (e) { rview.q = e.target.value; draw(); };
      Array.prototype.forEach.call(app.querySelectorAll(".chip[data-t]"), function (b) { b.onclick = function () { rview.type = b.dataset.t; resourcesPage(); }; });
      draw();
    });
  }

  // ---------- 详情 ----------
  function itemPage(id) {
    var it = state.byId[id];
    if (!it) return notFound();
    var d = DOMAINS[it.domain] || DOMAINS.application;
    var x = it.extra || {};
    app.innerHTML = '<p class="crumb"><a href="#/d/' + it.domain + '">' + d.name + "</a> /</p>" +
      '<article class="detail"><div class="meta"><span class="pill d-' + it.domain + '">' + d.name + "</span>" + validBadge(it.validation) +
      '<span class="score' + (it.score >= 75 ? " hi" : "") + '">' + it.score + " 分</span>" + (it.ai ? "" : '<span class="flag">规则</span>') + "</div>" +
      "<h1>" + esc(it.title_zh || it.title) + "</h1>" + (it.title_zh ? '<p class="orig big">' + esc(it.title) + "</p>" : "") +
      '<div class="meta">' + "<span>" + esc(it.source) + "</span>" + (x.venue ? "<span>" + esc(x.venue) + "</span>" : "") + "<span>" + ymd(it.published) + "</span>" +
      (x.stars ? "<span>★ " + x.stars + "</span>" : "") + '<a href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener">原文 ↗</a>' +
      (x.pdf ? '<a href="' + esc(safeUrl(x.pdf)) + '" target="_blank" rel="noopener">PDF ↗</a>' : "") + "</div>" +
      ((it.topics || []).length ? '<div class="meta">' + topicChips(it) + "</div>" : "") +
      '<p class="lead-sum">' + esc(it.summary) + "</p>" + (it.why ? '<p class="why"><b>为什么值得看</b>' + esc(it.why) + "</p>" : "") +
      '<div id="detail-body"><p class="muted">加载详情…</p></div></article>';
    window.scrollTo(0, 0);
    loadDetail(id).then(function (det) {
      var h = "";
      if (det.story) h += '<section class="panel"><p class="eyebrow">事件综述 · ' + it.cluster_size + " 个来源</p><p>" + esc(det.story) + "</p></section>";
      if (det.abstract_zh) h += '<section class="panel prose"><p class="eyebrow">中文精读</p>' + det.abstract_zh.split(/\n+/).map(function (p) { return "<p>" + esc(p) + "</p>"; }).join("") + "</section>";
      if (det.brief) {
        h += '<section class="panel"><p class="eyebrow">速读卡</p><dl class="bdl">' + BRIEF.map(function (b) {
          var v = det.brief[b[0]]; return v && v !== "未说明" ? "<dt>" + b[1] + "</dt><dd>" + esc(v) + "</dd>" : "";
        }).join("") + "</dl></section>";
      }
      if ((det.resources || []).length) {
        h += '<section class="panel"><p class="eyebrow">资源</p><ul class="res">' + det.resources.map(function (r) {
          return '<li><span class="tag">' + (RES[r.type] || esc(r.type)) + '</span> <a href="' + esc(safeUrl(r.url)) + '" target="_blank" rel="noopener">' + esc(r.name) + "</a></li>";
        }).join("") + "</ul></section>";
      }
      if (det.text) h += '<details class="panel orig-abs"><summary>原文摘要</summary><p>' + esc(det.text) + "</p>" + ((det.authors || []).length ? '<p class="muted small">作者：' + esc(det.authors.join(", ")) + "</p>" : "") + "</details>";
      var rel = (det.related || []).map(function (r) { return state.byId[r]; }).filter(Boolean);
      var same = state.items.filter(function (o) { return o.cluster === it.cluster && o.id !== it.id; });
      if (same.length) h += sectionHead("", "同一事件的其他报道") + '<div class="list">' + same.map(function (o) { return card(o, { compact: true }); }).join("") + "</div>";
      if (rel.length) h += sectionHead("", "相关研究") + '<div class="grid">' + rel.map(function (o) { return card(o, { compact: true }); }).join("") + "</div>";
      if (det.scores || det.models) h += '<p class="muted small">' + (det.scores ? "两位模型评审分别打分 " + det.scores.join(" / ") + "。" : "") + (det.models ? "处理模型：" + esc(det.models.join("、")) + "。" : "") + "模型生成的内容可能有误，请以原文为准。</p>";
      if (!h) h = '<p class="muted">这条内容还没有精读，模型有余额时会自动补上。</p>';
      var el = document.getElementById("detail-body");
      if (el) el.innerHTML = h;
    });
  }

  // ---------- 日报 / 信源 / 关于 ----------
  function digestPage(kind, key) {
    var all = [].concat(state.digests.daily.map(function (d) { d.kind = "daily"; return d; }), state.digests.weekly.map(function (d) { d.kind = "weekly"; return d; }));
    if (!all.length) { app.innerHTML = '<h1>日报</h1><div class="empty">还没有日报。每天第一次运行时会为前一天生成日报，每周一生成上周周报。</div>'; return; }
    var cur = all.filter(function (d) { return d.kind === kind && d.key === key; })[0] || state.digests.daily[0] || state.digests.weekly[0];
    var nav = function (list, k) {
      return list.slice(0, 30).map(function (d) { return '<a class="chip' + (d === cur ? " on" : "") + '" href="#/digest/' + k + "/" + d.key + '">' + esc(k === "daily" ? d.key.slice(5) : d.key) + "</a>"; }).join("");
    };
    app.innerHTML = "<h1>日报与周报</h1>" +
      (state.digests.weekly.length ? '<p class="muted" style="margin:6px 0">周报</p><div class="digest-nav">' + nav(state.digests.weekly, "weekly") + "</div>" : "") +
      '<p class="muted" style="margin:6px 0">日报</p><div class="digest-nav">' + nav(state.digests.daily, "daily") + "</div>" +
      '<article class="panel md prose">' + md(cur.markdown) + '<p class="muted small">' + esc(cur.label) + (cur.ai ? "" : " · 规则版（模型可用后自动改写）") + "</p></article>";
  }

  function sourcesPage() {
    var s = (state.meta && state.meta.sources) || [];
    var G = { aihot: "AIHOT 同款信源", academic: "学术（重点）", community: "社区 / 应用", platform: "平台 / 开源", game: "游戏" };
    app.innerHTML = "<h1>信源</h1><p class=\"lede\">与 AIHOT 开源仓库的示范信源保持一致，并加强学术论文与实际应用。arXiv 源会持续回填 2023 年以来的论文。所有内容先经本地关键词预筛，再由大模型精选。</p>" +
      '<div class="panel table-wrap"><table class="src"><thead><tr><th>信源</th><th>分组</th><th>类型</th><th>入选</th><th>状态</th></tr></thead><tbody>' +
      s.map(function (x) {
        return "<tr><td>" + (x.home ? '<a href="' + esc(safeUrl(x.home)) + '" target="_blank" rel="noopener">' + esc(x.name) + "</a>" : esc(x.name)) +
          (x.query ? '<div class="q">' + esc(x.query) + "</div>" : "") + "</td><td>" + esc(G[x.group] || x.group) + "</td><td>" + esc(x.kind) +
          "</td><td>" + x.items + "</td><td>" + (!x.enabled ? "停用" : x.ok ? "正常" : "上次失败") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  // 作者邮箱分段存放、运行时拼接：页面上正常显示和点击，网页源码里不出现完整地址，减少爬虫收集
  var CONTACTS = [["baihaointongji", ["gmail", "com"], "邮箱"]];
  function mailLinks() {
    return CONTACTS.map(function (c) {
      var addr = c[0] + String.fromCharCode(64) + c[1].join(".");
      return '<a class="mail" href="mailto:' + esc(addr) + '"><span class="muted">' + esc(c[2]) + "</span> " + esc(addr) + "</a>";
    }).join("");
  }
  function authorCard() {
    return '<section class="author panel">' +
      '<p class="eyebrow">关于作者</p>' +
      '<div class="author-head"><span class="avatar" aria-hidden="true">B</span><div><h2>Bianco</h2>' +
      '<p class="muted">同济大学土木工程学院 × 米兰理工大学能源系 双学位博士生</p></div></div>' +
      "<p>我一直对用大语言模型做多智能体仿真很感兴趣，尤其是在假想的极端情况下：不同的个体，面对不同的基础设施条件和外界干扰，会怎样反应。" +
      "把这些反应放进推演里算一算，就有机会提前看到一些由人引发的极端情况，给管理者的决策提供参考。</p>" +
      "<p>SANDBOXHOT 是我为这个方向做的资讯站，希望它对你也有用。也欢迎同样在做 sandbox simulation based on LLM agents 的同仁来信交流。</p>" +
      '<div class="mails">' + mailLinks() + "</div>" +
      '<p class="muted small">网站参考了数字生命卡兹克的 <a href="https://github.com/KKKKhazix/AIHOT" target="_blank" rel="noopener">AIHOT</a> 和 ' +
      '<a href="https://github.com/KKKKhazix/khazix-skills" target="_blank" rel="noopener">khazix-skills</a> 等仓库，主要借助 Codex 和 Claude 搭建。</p>' +
      "</section>";
  }

  function aboutPage() {
    app.innerHTML = '<div class="prose">' + authorCard() + '<h1>关于 SANDBOXHOT</h1>' +
      "<p>SANDBOXHOT 收集“利用 AI 智能体做沙盘推演、仿真、模拟”的资讯，覆盖学术论文、实际应用、商业、游戏与平台工具，并且更重视前两者。</p>" +
      "<h2>它怎么工作</h2><ul>" +
      "<li><b>采集</b>：AIHOT 同款 RSS 信源，加上 arXiv（含 2023 年以来的历史回填）、OpenAlex 定向检索，以及 Hacker News、GitHub 和公众号。</li>" +
      "<li><b>本地预筛</b>：关键词打分，必须同时涉及“仿真/推演”和“AI/智能体”才会进入下一步，不消耗模型额度。</li>" +
      "<li><b>批量精选与双评</b>：一个模型判断相关性、领域和分数；分数在边界上的再交给另一个模型独立评一次，分歧大时取更谨慎的结果。</li>" +
      "<li><b>中文精读</b>：入选内容由中文写作更好的模型写中文全文梳理、“为什么值得看”、主题、验证强度，并从原文里整理代码和数据链接。</li>" +
      "<li><b>速读卡</b>：学术与应用条目生成结构化速读卡（问题、仿真设定、方法、发现、验证、局限、可复用点）。</li>" +
      "<li><b>相关推荐与事件综述</b>：用向量找相关研究；多个来源报道的同一件事合成一段综述。</li>" +
      "<li><b>主题研判与横纵专题</b>：每个主题每周一段趋势判断；档案够多的主题，每周用长文模型写一到三篇横纵专题报告。</li>" +
      "<li><b>日报/周报</b>：每天为前一天、每周一为上一周生成编辑版综述，含今日必读、方法动向和可复用资源。</li></ul>" +
      "<p>标有“规则”的条目暂时只经过关键词预筛，之后有模型额度时会自动改写。分数是编辑评估的阅读价值，不代表内容真伪；所有模型生成内容都可能出错，请以原文为准。</p>" +
      '<h2>给 Agent 用</h2><p>本站所有数据都是公开 JSON，说明见 <a href="llms.txt">llms.txt</a>，最新精选在 <a href="api/latest.json">api/latest.json</a>。</p>' +
      '<p class="muted">网站为纯静态页面，没有账号、评论和追踪。框架思路参考 <a href="https://github.com/KKKKhazix/AIHOT" target="_blank" rel="noopener">AIHOT</a> 与“横纵分析法”。</p></div>';
  }

  function notFound() { app.innerHTML = '<div class="empty">页面不存在，<a href="#/">回首页</a></div>'; }

  function route() {
    var h = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    var r = h[0] || "home";
    var navKey = r === "d" ? h[1] : (r === "t" ? "topics" : (r === "i" ? (state.byId[h[1]] || {}).domain : r));
    Array.prototype.forEach.call(document.querySelectorAll("#nav a"), function (a) { a.classList.toggle("on", a.dataset.r === navKey); });
    if (r === "home") home();
    else if (r === "d") domainPage(h[1]);
    else if (r === "t") topicPage(h[1]);
    else if (r === "topics") topicsPage();
    else if (r === "research") researchPage(h[1]);
    else if (r === "resources") resourcesPage();
    else if (r === "i") itemPage(h[1]);
    else if (r === "digest") digestPage(h[1], h[2]);
    else if (r === "sources") sourcesPage();
    else if (r === "about") aboutPage();
    else notFound();
    if (r !== "d" && r !== "t") window.scrollTo(0, 0);
  }

  Promise.all([getJSON("data/items.json"), getJSON("data/meta.json"),
    getJSON("data/digests.json").catch(function () { return { daily: [], weekly: [] }; }),
    getJSON("data/topics.json").catch(function () { return { topics: [] }; })])
    .then(function (res) {
      state.items = res[0].items || [];
      state.items.forEach(function (it) { state.byId[it.id] = it; });
      state.meta = res[1];
      state.digests = { daily: res[2].daily || [], weekly: res[2].weekly || [] };
      state.topics = res[3].topics || [];
      state.topics.forEach(function (t) { state.topicBy[t.slug] = t; });
      var g = dt(state.meta.generated);
      document.getElementById("foot-meta").textContent = "更新于 " + (g ? g.toLocaleString("zh-CN", { hour12: false }) : "—") + " · 收录 " + state.items.length + " 条（模型精选 " + (state.meta.ai_items || 0) + " 条，精读 " + (state.meta.reads || 0) + " 篇）";
      window.addEventListener("hashchange", route);
      route();
    })
    .catch(function (e) {
      app.innerHTML = '<div class="empty">数据加载失败：' + esc(e.message) + "<br>本地预览请运行 <code>python run.py serve</code>，不要直接双击打开 HTML 文件。</div>";
    });
})();
