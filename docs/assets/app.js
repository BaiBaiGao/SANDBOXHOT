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
  var state = { items: [], meta: null, digests: { daily: [], weekly: [] }, byId: {}, topics: [], topicBy: {}, shards: {}, research: null, resources: null, hot: null };
  var app = document.getElementById("app");

  // ---------- 外观：浅色 / 跟随系统 / 深色 ----------
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { return null; } }
  var THEMES = [["light", "浅色", "ic-sun"], ["auto", "跟随系统", "ic-monitor"], ["dark", "深色", "ic-moon"]];
  function curTheme() { var t = store("sbh-theme"); return t === "light" || t === "dark" ? t : "auto"; }
  function setTheme(t) {
    if (t === "auto") { document.documentElement.removeAttribute("data-theme"); store("sbh-theme", null); }
    else { document.documentElement.setAttribute("data-theme", t); store("sbh-theme", t); }
    paintThemeSwitches();
  }
  function themeSwitchHTML() {
    var cur = curTheme();
    return THEMES.map(function (t) {
      return '<button type="button" data-set-theme="' + t[0] + '" aria-pressed="' + (cur === t[0]) + '" title="' + t[1] + '" aria-label="外观：' + t[1] + '"><i class="ic ' + t[2] + '"></i><span>' + t[1] + "</span></button>";
    }).join("");
  }
  function paintThemeSwitches() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-theme-switch]"), function (el) { el.innerHTML = themeSwitchHTML(); });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-set-theme]");
    if (b) setTheme(b.getAttribute("data-set-theme"));
  });
  paintThemeSwitches();

  // ---------- 收藏：只存在本机浏览器里，可导出、导入 ----------
  var STAR_KEY = "sbh-stars";
  function stars() { try { var v = JSON.parse(store(STAR_KEY) || "{}"); return v && typeof v === "object" && !Array.isArray(v) ? v : {}; } catch (e) { return {}; } }
  function saveStars(v) { store(STAR_KEY, JSON.stringify(v)); paintStarCount(); }
  function isStarred(id) { return !!stars()[id]; }
  function toggleStar(id) {
    var v = stars(), it = state.byId[id];
    if (v[id]) delete v[id];
    else v[id] = { t: new Date().toISOString(), title: it ? (it.title_zh || it.title) : id, url: it ? it.url : "", domain: it ? it.domain : "", source: it ? it.source : "" };
    saveStars(v);
    return !!v[id];
  }
  function paintStarCount() {
    var n = Object.keys(stars()).length, el = document.getElementById("star-count");
    if (el) el.textContent = n ? String(n) : "";
  }
  function starBtn(id) {
    var on = isStarred(id);
    return '<button type="button" class="star' + (on ? " on" : "") + '" data-star="' + esc(id) + '" aria-pressed="' + on + '" title="' + (on ? "取消收藏" : "收藏") + '" aria-label="' + (on ? "取消收藏" : "收藏") + '"><i class="ic ic-star"></i></button>';
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-star]");
    if (!b) return;
    e.preventDefault();
    var on = toggleStar(b.getAttribute("data-star"));
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", on); b.title = on ? "取消收藏" : "收藏"; b.setAttribute("aria-label", b.title);
    if (b.dataset.label) b.querySelector("span").textContent = on ? "已收藏" : "收藏";
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
  // 路由形如 #/d/academic?q=agent&days=30：筛选和搜索状态写进地址，刷新、返回、分享都能保留
  function hashQuery() { var i = location.hash.indexOf("?"); var o = {}; if (i < 0) return o; location.hash.slice(i + 1).split("&").forEach(function (kv) { if (!kv) return; var p = kv.split("="); try { o[decodeURIComponent(p[0])] = decodeURIComponent((p[1] || "").replace(/\+/g, " ")); } catch (e) { } }); return o; }
  function setHashQuery(obj) {
    var path = location.hash.split("?")[0] || "#/";
    var qs = Object.keys(obj).filter(function (k) { return obj[k] !== "" && obj[k] != null; }).map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]); }).join("&");
    history.replaceState(null, "", location.pathname + location.search + path + (qs ? "?" + qs : ""));
  }
  function hhmm(s) { var d = dt(s); if (!d || /T00:00:00/.test(s || "")) return ""; return ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2); }
  var WEEK = "日一二三四五六";
  function dayLabel(d) {
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var x = new Date(d); x.setHours(0, 0, 0, 0);
    var diff = Math.round((today - x) / 864e5);
    var rel = diff === 0 ? "今天" : diff === 1 ? "昨天" : "星期" + WEEK.charAt(x.getDay());
    return { main: (x.getMonth() + 1) + "月" + x.getDate() + "日" + (x.getFullYear() !== today.getFullYear() ? " " + x.getFullYear() : ""), rel: rel };
  }
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
  function cardMeta(it, opts) {
    var x = it.extra || {};
    var meta = ['<span>' + esc(it.source) + "</span>"];
    if (x.venue && x.venue !== "arXiv") meta.push("<span>" + esc(x.venue) + "</span>");
    if (it.authors && it.authors.length && !opts.compact && !opts.timeline) meta.push("<span>" + esc(it.authors.slice(0, 3).join(", ")) + (it.authors.length > 3 ? " 等" : "") + "</span>");
    if (!opts.timeline) meta.push('<span title="' + esc(it.published) + '">' + ago(when(it)) + "</span>");
    if (x.stars) meta.push("<span>★ " + x.stars + "</span>");
    if (x.points) meta.push("<span>▲ " + x.points + "</span>");
    if (it.cluster_size > 1) meta.push("<span>" + it.cluster_size + " 个来源</span>");
    var links = ['<a href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener">原文</a>'];
    if (x.pdf) links.push('<a href="' + esc(safeUrl(x.pdf)) + '" target="_blank" rel="noopener">PDF</a>');
    if (x.discussion) links.push('<a href="' + esc(safeUrl(x.discussion)) + '" target="_blank" rel="noopener">讨论</a>');
    meta.push("<span>" + links.join(" · ") + "</span>");
    return meta.join("");
  }
  function card(it, opts) {
    opts = opts || {};
    var d = DOMAINS[it.domain] || DOMAINS.application;
    var title = it.title_zh || it.title;
    var marks = (it.applied ? '<span class="mark">真实场景应用</span>' : "") + (it.read ? '<span class="mark">精读</span>' : "") + (it.brief ? '<span class="mark">速读卡</span>' : "") + (it.res ? '<span class="mark">资源 ' + it.res + "</span>" : "");
    return '<article class="card' + (opts.timeline ? " tl-card" : "") + '">' +
      '<div class="row"><span class="meta"><span class="pill d-' + esc(it.domain) + '">' + d.name + "</span>" + validBadge(it.validation) + "</span>" +
      '<span class="meta">' + (it.ai ? "" : '<span class="flag" title="模型暂未处理，按关键词规则入选">规则</span>') +
      '<span class="score' + (it.score >= 75 ? " hi" : "") + '" title="编辑评分：阅读价值 0–100，45 分入选，75 分以上标红">' + it.score + "</span>" + starBtn(it.id) + "</span></div>" +
      '<h3><a href="#/i/' + esc(it.id) + '">' + esc(title) + "</a></h3>" +
      (it.title_zh && !opts.compact && !opts.timeline ? '<div class="orig">' + esc(it.title) + "</div>" : "") +
      (opts.compact || !it.summary ? "" : '<p class="sum' + (opts.timeline ? " clamp2" : "") + '">' + esc(it.summary) + "</p>") +
      (it.why && !opts.compact ? '<p class="why" title="' + esc(it.why) + '">推荐理由：' + esc(it.why) + "</p>" : "") +
      (!opts.compact && !opts.timeline && (it.topics || []).length ? '<div class="meta">' + topicChips(it) + "</div>" : "") +
      '<div class="meta">' + cardMeta(it, opts) + (opts.compact || opts.timeline ? "" : marks) + "</div>" +
      "</article>";
  }
  function leads() { return state.items.filter(function (it) { return it.lead; }); }
  // “实际应用”板块同时收录标了真实场景应用（applied）的论文等
  function inDomain(it, dom) { return it.domain === dom || (dom === "application" && it.applied); }
  function sectionHead(cls, title, link, linkText) {
    return '<div class="sec-head"><div class="sec-title ' + cls + '"><span class="bar"></span><h2>' + title + "</h2></div>" +
      (link ? '<a href="' + link + '">' + (linkText || "查看全部 →") + "</a>" : "") + "</div>";
  }

  // ---------- 首页：今日必读 + 日报导读 + 按天分组的时间线 ----------
  function digestTeaser(dg) {
    var lines = (dg.markdown || "").split(/\r?\n/);
    var title = "", lede = "";
    for (var k = 0; k < lines.length; k++) {
      var l = lines[k].trim();
      if (!title && /^#{1,3} /.test(l)) { title = l.replace(/^#+ /, ""); continue; }
      if (title && l && !/^[#\-*|（(]/.test(l)) { lede = l; break; }
      if (/^#{1,3} /.test(l) && title) break;
    }
    return '<a class="teaser" href="#/digest/' + (dg.kind || "daily") + "/" + esc(dg.key) + '"><p class="eyebrow">' + esc(dg.label) + (dg.ai ? "" : " · 规则版") + "</p>" +
      "<b>" + esc(plainInline(title || dg.label)) + "</b>" + (lede ? "<span>" + esc(plainInline(lede)) + "</span>" : "") + '<em>读全文 →</em></a>';
  }
  function plainInline(t) { return String(t || "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/\*\*/g, ""); }
  var CATS = [["", "全部"]].concat(ORDER.map(function (k) { return [k, DOMAINS[k].name]; }));
  function home() {
    var all = leads();
    var qy = hashQuery();
    var hv = { c: DOMAINS[qy.c] ? qy.c : "", q: qy.q || "", n: Math.max(30, +qy.n || 30) };
    var picks = all.filter(function (it) { return ageDays(it) <= 4 && it.why; }).sort(function (a, b) { return rank(b) - rank(a); }).slice(0, 3);
    state.digests.daily.forEach(function (d) { d.kind = "daily"; });
    var dg = state.digests.daily[0];
    var h = '<div class="page-head"><div><h1>精选</h1><p class="lede">' + esc((state.meta && state.meta.site && state.meta.site.tagline) || "AI 智能体 × 沙盘推演 / 仿真") + "</p></div>" +
      '<label class="search"><i class="ic ic-search"></i><input id="q" type="search" placeholder="搜索标题、摘要、作者…" value="' + esc(hv.q) + '" aria-label="搜索"><kbd title="按 / 键快速搜索">/</kbd></label></div>';
    if (!all.length) h += '<div class="empty" style="margin-bottom:18px">还没有内容。首次运行后，这里会出现精选资讯。</div>';
    if (picks.length || dg) {
      h += '<div class="today">';
      if (picks.length) {
        h += '<section><div class="sec-head"><div class="sec-title"><span class="bar"></span><h2>今日必读</h2></div></div><div class="picks">' + picks.map(function (it, n) {
          return '<a class="pick" href="#/i/' + esc(it.id) + '"><span class="n">' + (n + 1) + '</span><span><b>' + esc(it.title_zh || it.title) + "</b><em>" + esc(it.why) + "</em></span></a>";
        }).join("") + "</div></section>";
      }
      if (dg) h += '<section class="today-digest"><div class="sec-head"><div class="sec-title"><span class="bar"></span><h2>日报</h2></div><a href="#/digest">往期 →</a></div>' + digestTeaser(dg) + "</section>";
      h += "</div>";
    }
    h += '<div class="tabs" role="tablist" aria-label="按栏目筛选">' + CATS.map(function (c) {
      return '<button type="button" role="tab" data-cat="' + c[0] + '" aria-selected="' + (hv.c === c[0]) + '">' + c[1] + "</button>";
    }).join("") + "</div>" + '<div id="timeline"></div>';
    h += '<a class="author-strip" href="#/about"><span class="avatar" aria-hidden="true">B</span><span><b>作者 Bianco</b>' +
      '<span class="muted">同济大学 × 米兰理工大学双学位博士生，研究用 LLM 多智能体推演极端情况下的人群行为。欢迎交流 →</span></span></a>';
    app.innerHTML = h;

    function draw() {
      setHashQuery({ c: hv.c, q: hv.q, n: hv.n > 30 ? hv.n : "" });
      var words = hv.q.toLowerCase().split(/\s+/).filter(Boolean);
      // 不搜索时只看新内容（历史回填的论文在各栏目的“全部”里）；搜索时查全部
      var list = all.filter(function (it) {
        if (hv.c && !inDomain(it, hv.c)) return false;
        if (!words.length) return !it.backfill;
        var hay = [it.title, it.title_zh, it.summary, it.why, it.source, (it.authors || []).join(" "), (it.tags || []).join(" ")].join(" ").toLowerCase();
        return words.every(function (w) { return hay.indexOf(w) >= 0; });
      }).sort(function (a, b) { return (+when(b) || 0) - (+when(a) || 0); });
      var el = document.getElementById("timeline");
      if (!list.length) { el.innerHTML = '<div class="empty">' + (words.length ? "没有找到相关内容，换个关键词试试。" : "这个栏目最近没有新内容。") + "</div>"; return; }
      var shown = list.slice(0, hv.n), out = "", lastKey = "";
      shown.forEach(function (it) {
        var d = when(it) || new Date(0), key = ymd(d.toISOString());
        if (key !== lastKey) {
          if (lastKey) out += "</div></section>";
          var lab = dayLabel(d), cnt = list.filter(function (o) { return ymd((when(o) || new Date(0)).toISOString()) === key; }).length;
          out += '<section class="day"><h2 class="day-head">' + lab.main + '<span class="muted">' + lab.rel + " · " + cnt + " 条</span></h2><div class=\"tl\">";
          lastKey = key;
        }
        out += '<div class="tl-row"><time class="tl-time">' + esc(hhmm(it.published) || "") + '</time><span class="tl-dot" aria-hidden="true"></span>' + card(it, { timeline: true }) + "</div>";
      });
      out += "</div></section>";
      if (list.length > hv.n) out += '<button class="more" id="more">再看 30 条（还有 ' + (list.length - hv.n) + " 条）</button>";
      else if (!words.length) out += '<p class="muted small center">更早的论文在 <a href="#/d/academic?days=all">学术论文 → 全部</a> 里。</p>';
      if (words.length) out = '<p class="muted small">找到 ' + list.length + " 条（含历史论文）</p>" + out;
      el.innerHTML = out;
      var more = document.getElementById("more");
      if (more) more.onclick = function () { hv.n += 30; draw(); };
    }
    var q = document.getElementById("q");
    q.oninput = function () { hv.q = q.value; hv.n = 30; draw(); };
    Array.prototype.forEach.call(app.querySelectorAll("[data-cat]"), function (b) {
      b.onclick = function () {
        hv.c = b.dataset.cat; hv.n = 30;
        Array.prototype.forEach.call(app.querySelectorAll("[data-cat]"), function (x) { x.setAttribute("aria-selected", x === b); });
        draw();
      };
    });
    draw();
  }

  // ---------- 热点榜 ----------
  var TREND = { new: ["新", "首报 6 小时内，或 6 小时前还不在榜上"], up: ["上升", "名次上升，或有新的来源加入讨论"] };
  function loadHot() {
    if (!state.hot) state.hot = getJSON("data/hot.json").catch(function () { return null; });
    return state.hot;
  }
  function hotRows(hot) {
    if (hot && hot.list) return hot.list.map(function (r) { return { it: state.byId[r.id], r: r }; }).filter(function (x) { return x.it; });
    // hot.json 还没生成时（旧数据），退回按条目的热度字段排序
    return leads().filter(function (it) { return it.hot > 0 && !it.backfill; }).sort(function (a, b) { return b.hot - a.hot; }).slice(0, 30)
      .map(function (it, n) { return { it: it, r: { rank: n + 1, hot: it.hot, sources: it.cluster_size, trend: "" } }; });
  }
  function trendBadge(t) { var x = TREND[t]; return x ? '<span class="trend t-' + t + '" title="' + x[1] + '">' + (t === "up" ? '<i class="ic ic-up"></i>' : "") + x[0] + "</span>" : ""; }
  function hotPage() {
    app.innerHTML = '<p class="muted">加载中…</p>';
    loadHot().then(function (hot) {
      var rows = hotRows(hot);
      var win = hot ? Math.round(hot.window_h / 24) : 7, hl = hot ? hot.half_life_h : 48, cmp = hot ? hot.compare_h : 6;
      app.innerHTML = '<div class="page-head"><div><h1>热点榜</h1><p class="lede">按事件算热度：近 ' + win + " 天里，每个独立来源只算一次，同一家媒体发十篇也只算一次；按首次报道时间每 " + hl + " 小时减半，再乘编辑评分。和约 " + cmp + " 小时前的榜单比，新上榜的标“新”，名次上升或有新来源加入的标“上升”。</p></div></div>" +
        (rows.length ? '<ol class="hot-board">' + rows.map(function (x) {
          var it = x.it, r = x.r;
          return '<li><span class="rk' + (r.rank <= 3 ? " top" : "") + '">' + r.rank + '</span><div class="hb-main"><div class="hb-title"><a href="#/i/' + esc(it.id) + '">' + esc(it.title_zh || it.title) + "</a>" + trendBadge(r.trend) + "</div>" +
            '<div class="meta"><span class="pill d-' + esc(it.domain) + '">' + (DOMAINS[it.domain] || DOMAINS.application).name + "</span><span>" + esc(it.source) + "</span>" +
            (r.sources > 1 ? "<span>" + r.sources + " 个来源</span>" : "") + "<span>" + ago(when(it)) + "</span></div></div>" +
            '<span class="hb-heat" title="热度">' + (Math.round(r.hot * 10) / 10) + "</span>" + starBtn(it.id) + "</li>";
        }).join("") + "</ol>" : '<div class="empty">最近一周没有新内容进入热点榜。</div>') +
        (hot ? '<p class="muted small">榜单更新于 ' + esc(ago(hot.generated)) + "。</p>" : "");
    });
  }

  // ---------- 列表页（领域 / 主题共用） ----------
  var view = { q: "", days: "90", sort: "rank", tag: "", limit: 40, key: "" };
  function listing(base, key, redraw) {
    var qy = hashQuery(), keep = view.key === key ? view.limit : 40;
    view = { q: qy.q || "", days: qy.days || (key.indexOf("t:") === 0 ? "all" : "90"), sort: qy.sort || "rank", tag: qy.tag || "", limit: keep, key: key };
    var defDays = key.indexOf("t:") === 0 ? "all" : "90";
    function sync() { setHashQuery({ q: view.q, days: view.days === defDays ? "" : view.days, sort: view.sort === "rank" ? "" : view.sort, tag: view.tag }); }
    var tagCount = {};
    base.forEach(function (it) { (it.tags || []).forEach(function (t) { tagCount[t] = (tagCount[t] || 0) + 1; }); });
    var topTags = Object.keys(tagCount).sort(function (a, b) { return tagCount[b] - tagCount[a]; }).slice(0, 14);
    var h = '<div class="toolbar"><label class="search"><i class="ic ic-search"></i><input id="q" type="search" placeholder="搜索标题、摘要、作者、标签…" value="' + esc(view.q) + '" aria-label="搜索"><kbd>/</kbd></label>' +
      '<select id="days"><option value="7">近 7 天</option><option value="30">近 30 天</option><option value="90">近 90 天</option><option value="365">近一年</option><option value="all">全部（含历史回填）</option></select>' +
      '<select id="sort"><option value="rank">综合排序</option><option value="new">最新</option><option value="score">最高分</option><option value="hot">最热</option></select></div>' +
      (topTags.length ? '<div class="chips">' + topTags.map(function (t) { return '<button class="chip' + (view.tag === t ? " on" : "") + '" data-tag="' + esc(t) + '">' + esc(t) + " " + tagCount[t] + "</button>"; }).join("") + "</div>" : "") +
      '<div id="res"></div>';
    return {
      html: h, bind: function () {
        var q = document.getElementById("q"), days = document.getElementById("days"), sort = document.getElementById("sort");
        days.value = view.days; sort.value = view.sort;
        function draw() {
          sync();
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
          b.onclick = function () { view.tag = view.tag === b.dataset.tag ? "" : b.dataset.tag; view.limit = 40; sync(); redraw(); };
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
    app.innerHTML = '<p class="crumb"><a href="#/d/' + it.domain + '">' + d.name + "</a></p>" +
      '<article class="detail"><div class="meta"><span class="pill d-' + it.domain + '">' + d.name + "</span>" + validBadge(it.validation) +
      '<span class="score' + (it.score >= 75 ? " hi" : "") + '" title="编辑评分：阅读价值 0–100">' + it.score + " 分</span>" + (it.ai ? "" : '<span class="flag">规则</span>') +
      '<button type="button" class="star-btn' + (isStarred(it.id) ? " on" : "") + '" data-star="' + esc(it.id) + '" data-label="1" aria-pressed="' + isStarred(it.id) + '"><i class="ic ic-star"></i><span>' + (isStarred(it.id) ? "已收藏" : "收藏") + "</span></button></div>" +
      "<h1>" + esc(it.title_zh || it.title) + "</h1>" + (it.title_zh ? '<p class="orig big">' + esc(it.title) + "</p>" : "") +
      '<div class="meta">' + "<span>" + esc(it.source) + "</span>" + (x.venue ? "<span>" + esc(x.venue) + "</span>" : "") + "<span>" + ymd(it.published) + "</span>" +
      (x.stars ? "<span>★ " + x.stars + "</span>" : "") + '<a href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener">原文 ↗</a>' +
      (x.pdf ? '<a href="' + esc(safeUrl(x.pdf)) + '" target="_blank" rel="noopener">PDF ↗</a>' : "") + "</div>" +
      ((it.topics || []).length ? '<div class="meta">' + topicChips(it) + "</div>" : "") +
      '<p class="lead-sum">' + esc(it.summary) + "</p>" + (it.why ? '<p class="why-full"><b>为什么值得看</b>' + esc(it.why) + "</p>" : "") +
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
      '<article class="panel md prose">' + md(dropEmptySections(cur.markdown)) + '<p class="muted small">' + esc(cur.label) + (cur.ai ? "" : " · 规则版（模型可用后自动改写）") + "</p></article>";
  }

  // 旧日报里“本期暂无”的空栏目不显示（新日报生成时已经不写空栏目）
  function dropEmptySections(src) {
    var lines = (src || "").split(/\r?\n/), out = [], k = 0;
    while (k < lines.length) {
      if (/^#{3,4} /.test(lines[k])) {
        var block = [lines[k]], body = [], m = k + 1;
        while (m < lines.length && !/^#{1,4} /.test(lines[m])) { block.push(lines[m]); if (lines[m].trim()) body.push(lines[m].trim()); m++; }
        var empty = body.every(function (b) { return /^[-*]\s*(本期|本周)?暂无[。.]?$/.test(b); });
        if (!empty) out = out.concat(block);
        k = m; continue;
      }
      out.push(lines[k]); k++;
    }
    return out.join("\n");
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

  // ---------- 关于：信源河 + 四个数字 ----------
  function river(srcs, lastPick) {
    // 每条线是一个启用的信源；近期有内容入选的信源穿过筛选线汇入日报，其余在筛选线前淡出
    var on = srcs.filter(function (x) { return x.enabled; });
    var W = 1000, H = 300, n = Math.min(on.length, 64), fx = 620, cx = 780, cy = 150;
    var lines = "", pass = "";
    for (var k = 0; k < n; k++) {
      var y = 12 + (H - 24) * (n === 1 ? 0.5 : k / (n - 1)), x = on[k];
      var wob = Math.sin(k * 2.3) * 14;
      if (x.items > 0) pass += '<path class="rv-pass" style="animation-delay:' + (-(k * 0.37) % 4).toFixed(2) + 's" d="M0 ' + y.toFixed(1) + " C 260 " + (y + wob).toFixed(1) + ", 420 " + (y * 0.6 + cy * 0.4).toFixed(1) + ", " + fx + " " + (y * 0.35 + cy * 0.65).toFixed(1) + " S " + (cx - 40) + " " + cy + ", " + cx + " " + cy + '"><title>' + esc(x.name) + " · 在展 " + x.items + " 条</title></path>";
      else lines += '<path class="rv-drop" d="M0 ' + y.toFixed(1) + " C 240 " + (y + wob).toFixed(1) + ", 420 " + (y * 0.7 + cy * 0.3).toFixed(1) + ", " + fx + " " + (y * 0.5 + cy * 0.5).toFixed(1) + '"><title>' + esc(x.name) + "</title></path>";
    }
    return '<figure class="river"><svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + on.length + ' 个信源汇入精选和日报">' + lines + pass +
      '<line class="rv-filter" x1="' + fx + '" y1="6" x2="' + fx + '" y2="' + (H - 6) + '"/>' +
      '<path class="rv-band" d="M' + cx + " " + cy + " L 905 " + cy + '"/>' +
      '<g class="rv-doc" transform="translate(905 ' + (cy - 26) + ')"><rect width="40" height="52" rx="5"/><path d="M9 14h22M9 23h22M9 32h14"/></g></svg>' +
      '<figcaption><span>信源</span><span>预筛 · 两次评分</span><span>日报</span></figcaption>' +
      (lastPick ? '<a class="rv-latest" href="#/i/' + esc(lastPick.id) + '"><span class="eyebrow">最近精选</span><b>' + esc(lastPick.title_zh || lastPick.title) + "</b><span class=\"muted small\">" + esc(lastPick.source) + "</span></a>" : "") +
      "</figure>";
  }
  function aboutPage() {
    var m = state.meta || {}, srcs = m.sources || [];
    var f = m.funnel || { sources: srcs.filter(function (x) { return x.enabled; }).length, collected_7d: null, selected_7d: null, digests_7d: null };
    var fresh = leads().filter(function (it) { return !it.backfill && it.ai; }).sort(function (a, b) { return (+when(b) || 0) - (+when(a) || 0); });
    var num = function (v) { return v == null ? "—" : String(v); };
    var steps = [
      ["01", "采集", num(f.sources), "个信源", "arXiv 定向检索、OpenAlex 期刊、AIHOT 同款 RSS、Google 新闻检索、GitHub、公众号；每 4 小时看一遍，arXiv 还在回填 2023 年以来的论文。"],
      ["02", "收录", num(f.collected_7d), "条 · 近 7 天", "抓到的都先过本地关键词预筛：必须同时涉及“仿真/推演”和“AI/智能体”，" + (f.kept_7d != null ? "近 7 天留下 " + f.kept_7d + " 条，" : "") + "这一步不花模型额度。"],
      ["03", "精选", num(f.selected_7d), "条 · 近 7 天", "模型判断相关性和阅读价值，边界上的再由另一个模型独立评一次；入选的写中文标题、精读和速读卡。"],
      ["04", "成刊", num(f.digests_7d), "期 · 近 7 天", "每天为前一天出日报，每周一出周报；每个主题每周写一段研判，档案够多的主题写横纵专题。"]
    ];
    app.innerHTML = '<section class="about-hero"><p class="eyebrow">关于 SANDBOXHOT</p>' +
      "<h1>智能体仿真的新东西每天都有，<br><em>值得细看的，只有几条。</em></h1>" +
      '<p class="lede">SANDBOXHOT 替你盯着 ' + num(f.sources) + " 个信源，专看用 AI 智能体做沙盘推演、仿真和模拟的论文、应用和项目：抓取、预筛、两次评分、中文精读，每天出一份日报。免费，不用注册。</p>" +
      '<div class="cta"><a class="btn primary" href="#/">看今天的精选 →</a><a class="btn" href="#/digest">读最新日报</a></div></section>' +
      river(srcs, fresh[0]) +
      '<div class="funnel">' + steps.map(function (x) {
        return '<div class="fstep"><p class="eyebrow">' + x[0] + " " + x[1] + "</p><p class=\"fnum\"><b>" + x[2] + "</b><span>" + x[3] + "</span></p><p class=\"muted small\">" + x[4] + "</p></div>";
      }).join("") + "</div>" +
      '<div class="prose about-body">' + authorCard() +
      "<h2>它怎么工作</h2><ul>" +
      "<li><b>批量精选与双评</b>：一个模型判断相关性、领域和分数；分数在边界上的再交给另一个模型独立评一次，分歧大时取更谨慎的结果。</li>" +
      "<li><b>中文精读与速读卡</b>：入选内容写中文全文梳理、推荐理由、主题和验证强度，并从原文里整理代码和数据链接；学术与应用条目另有速读卡（问题、仿真设定、方法、发现、验证、局限、可复用点）。</li>" +
      "<li><b>事件与热度</b>：多个来源报道的同一件事合成一个事件；热度按独立来源数算，每个来源只算一次，随时间减半。</li>" +
      "<li><b>主题研判与横纵专题</b>：每个主题每周一段趋势判断；档案够多的主题，用长文模型写横纵专题报告。</li></ul>" +
      "<p>标有“规则”的条目暂时只经过关键词预筛，之后有模型额度时会自动改写。分数是编辑评估的阅读价值（0–100，45 分入选），不代表内容真伪；所有模型生成内容都可能出错，请以原文为准。</p>" +
      '<p class="muted">网站为纯静态页面，没有账号和评论，收藏只保存在你自己的浏览器里。访问量用 <a href="https://www.goatcounter.com/" target="_blank" rel="noopener">GoatCounter</a> 统计，它不使用 Cookie，也不收集可以识别个人的信息。框架思路参考 <a href="https://github.com/KKKKhazix/AIHOT" target="_blank" rel="noopener">AIHOT</a> 与“横纵分析法”。</p></div>';
  }

  // ---------- 收藏 ----------
  function starredPage() {
    var v = stars(), ids = Object.keys(v).sort(function (a, b) { return (v[b].t || "") < (v[a].t || "") ? -1 : 1; });
    var live = ids.filter(function (id) { return state.byId[id]; }), gone = ids.filter(function (id) { return !state.byId[id]; });
    app.innerHTML = '<div class="page-head"><div><h1>收藏</h1><p class="lede">收藏只保存在这台设备的这个浏览器里，不上传。换设备或清理浏览器数据前，先导出备份。</p></div>' +
      '<div class="actions"><button type="button" class="btn" id="star-export"' + (ids.length ? "" : " disabled") + '>导出备份</button><label class="btn">导入备份<input type="file" id="star-import" accept="application/json,.json" hidden></label></div></div>' +
      (live.length ? '<div class="list">' + live.map(function (id) { return card(state.byId[id]); }).join("") + "</div>" : "") +
      (gone.length ? sectionHead("", "已下架的条目（" + gone.length + "）") + '<p class="muted small">这些条目已经不在网站的展示范围里，保留了标题和原文链接。</p><ul class="gone">' + gone.map(function (id) {
        var x = v[id];
        return '<li><a href="' + esc(safeUrl(x.url)) + '" target="_blank" rel="noopener">' + esc(x.title || id) + "</a> <span class=\"muted small\">" + esc(x.source || "") + "</span> " + starBtn(id) + "</li>";
      }).join("") + "</ul>" : "") +
      (ids.length ? "" : '<div class="empty">还没有收藏。点条目右上角的星标就能收藏。</div>') +
      '<p class="muted small" id="star-msg"></p>';
    document.getElementById("star-export").onclick = function () {
      var blob = new Blob([JSON.stringify({ app: "SANDBOXHOT", version: 1, exported: new Date().toISOString(), stars: stars() }, null, 2)], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "sandboxhot-收藏-" + ymd(new Date().toISOString()) + ".json";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    };
    document.getElementById("star-import").onchange = function (e) {
      var file = e.target.files[0]; if (!file) return;
      var r = new FileReader();
      r.onload = function () {
        try {
          var data = JSON.parse(r.result), inc = data && data.stars, cur = stars(), n = 0;
          if (!inc || typeof inc !== "object") throw new Error("格式不对");
          Object.keys(inc).forEach(function (id) {
            var x = inc[id];
            if (!/^[\w-]{1,64}$/.test(id) || !x || typeof x !== "object" || cur[id]) return;
            cur[id] = { t: String(x.t || ""), title: String(x.title || ""), url: String(x.url || ""), domain: String(x.domain || ""), source: String(x.source || "") };
            n++;
          });
          saveStars(cur); starredPage();
          document.getElementById("star-msg").textContent = "导入了 " + n + " 条新收藏。";
        } catch (err) { document.getElementById("star-msg").textContent = "导入失败：文件不是 SANDBOXHOT 的收藏备份。"; }
      };
      r.readAsText(file);
    };
  }

  // ---------- 我的（手机底部最后一个标签）/ Agent 接入 ----------
  function rowLink(href, icon, label, detail, ext) {
    return '<li><a href="' + href + '"' + (ext ? ' target="_blank" rel="noopener"' : "") + '><i class="ic ' + icon + '"></i><span>' + label + "</span>" + (detail ? '<span class="muted small">' + detail + "</span>" : "") + '<i class="ic ic-chev"></i></a></li>';
  }
  function mePage() {
    var n = Object.keys(stars()).length;
    app.innerHTML = "<h1>我的</h1>" +
      '<section class="group"><h2>本机</h2><ul class="rows">' + rowLink("#/starred", "ic-star", "收藏", n ? n + " 条" : "") +
      '<li class="row-theme"><span class="rt-label"><i class="ic ic-monitor"></i><span>外观</span></span><div class="theme-switch" data-theme-switch></div></li></ul></section>' +
      '<section class="group"><h2>栏目</h2><ul class="rows">' + ORDER.map(function (k) { return rowLink("#/d/" + k, "ic-dot d-" + k, DOMAINS[k].name, ((state.meta && state.meta.counts) || {})[k] ? state.meta.counts[k] + " 条" : ""); }).join("") + "</ul></section>" +
      '<section class="group"><h2>研究</h2><ul class="rows">' + rowLink("#/research", "ic-layers", "专题研究", "") + rowLink("#/resources", "ic-box", "资源库", "代码 · 数据 · 基准") + "</ul></section>" +
      '<section class="group"><h2>更多</h2><ul class="rows">' + rowLink("#/agent", "ic-plug", "Agent 接入", "RSS · API · llms.txt") + rowLink("#/sources", "ic-list", "信源", "") + rowLink("#/about", "ic-info", "关于", "") + "</ul></section>";
    paintThemeSwitches();
  }
  function agentPage() {
    var base = location.origin + location.pathname.replace(/index\.html$/, "");
    var rows = [["RSS", "feed.xml", "最新 60 条精选，标准 RSS 2.0，任何阅读器都能订阅。"],
      ["llms.txt", "llms.txt", "给大模型和 Agent 的入口说明：有哪些数据文件、字段是什么意思。"],
      ["最新精选", "api/latest.json", "最新 120 条精选的中文标题、摘要、领域、分数、主题和链接，加上最新一期日报。"],
      ["热点榜", "data/hot.json", "按事件热度排名，带“新 / 上升”标记。"],
      ["全部条目", "data/items.json", "当前在展的全部条目（列表字段）。"],
      ["日报周报", "data/digests.json", "日报和周报的 Markdown 原文。"],
      ["资源库", "data/resources.json", "从原文里整理的代码、数据集、基准、模型链接。"]];
    app.innerHTML = '<div class="page-head"><div><h1>Agent 接入</h1><p class="lede">本站没有服务器，所有内容都是公开的静态文件：人看网页，Agent 直接读同一份数据。不需要 Key，也不限流。</p></div></div>' +
      '<div class="list">' + rows.map(function (r) {
        return '<div class="card agent-row"><div class="row"><h3>' + r[0] + '</h3><a class="btn small" href="' + r[1] + '" target="_blank" rel="noopener">打开</a></div><p class="sum">' + r[2] + '</p><code class="url">' + esc(base + r[1]) + "</code></div>";
      }).join("") + "</div>" +
      '<p class="muted small">让 Agent 先读 llms.txt，它会告诉 Agent 其余文件在哪里。分数是编辑评估的阅读价值，不代表真伪；引用前请打开原文核对。</p>';
  }

  function notFound() { app.innerHTML = '<div class="empty">页面不存在，<a href="#/">回首页</a></div>'; }

  // ---------- 访问统计（GoatCounter，无 Cookie）----------
  // 站长在自己的设备上打开一次 #owner，这台设备之后不再计数；打开 #owner-off 恢复计数。
  // localStorage 键名 skipgc 与 GoatCounter 官方的“跳过本机”约定一致。
  var GC_ENDPOINT = "https://sandboxhot.goatcounter.com/count";
  var gcReady = false;
  function isOwner() { return store("skipgc") === "t"; }
  function handleOwnerToggle() {
    var h = location.hash;
    if (h !== "#owner" && h !== "#owner-off") return false;
    try { if (h === "#owner") localStorage.setItem("skipgc", "t"); else localStorage.removeItem("skipgc"); } catch (e) { }
    alert(h === "#owner" ? "已设置：这台设备的访问不再计入访问统计。" : "已恢复：这台设备的访问会计入访问统计。");
    history.replaceState(null, "", location.pathname + "#/");
    return true;
  }
  function countView() {
    if (!gcReady || isOwner() || !window.goatcounter || !window.goatcounter.count) return;
    var route = location.hash.replace(/^#/, "") || "/";
    window.goatcounter.count({ path: location.pathname.replace(/\/$/, "") + route, title: document.title });
  }
  function loadCounter() {
    if (isOwner() || /^(localhost|127\.|0\.0\.0\.0)/.test(location.hostname)) return;
    window.goatcounter = { no_onload: true };
    var sc = document.createElement("script");
    sc.async = true;
    sc.setAttribute("data-goatcounter", GC_ENDPOINT);
    sc.src = "https://gc.zgo.at/count.v4.js";
    sc.onload = function () { gcReady = true; countView(); };
    document.head.appendChild(sc);
  }

  function route() {
    var h = location.hash.replace(/^#\/?/, "").split("?")[0].split("/").map(function (x) { try { return decodeURIComponent(x); } catch (e) { return x; } });
    var r = h[0] || "home";
    var navKey = r === "d" ? h[1] : (r === "t" ? "topics" : (r === "i" ? (state.byId[h[1]] || {}).domain : r));
    // 手机底部只有五个标签：其余页面归到“我的”
    var tabKey = ({ home: "home", hot: "hot", digest: "digest", topics: "topics" })[navKey] || (r === "i" ? "home" : "me");
    Array.prototype.forEach.call(document.querySelectorAll("#nav a"), function (a) { a.classList.toggle("on", a.dataset.r === navKey); if (a.dataset.r === navKey) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    Array.prototype.forEach.call(document.querySelectorAll("#tabbar a"), function (a) { a.classList.toggle("on", a.dataset.r === tabKey); });
    if (r === "home") home();
    else if (r === "hot") hotPage();
    else if (r === "d") domainPage(h[1]);
    else if (r === "t") topicPage(h[1]);
    else if (r === "topics") topicsPage();
    else if (r === "research") researchPage(h[1]);
    else if (r === "resources") resourcesPage();
    else if (r === "i") itemPage(h[1]);
    else if (r === "digest") digestPage(h[1], h[2]);
    else if (r === "starred") starredPage();
    else if (r === "me") mePage();
    else if (r === "agent") agentPage();
    else if (r === "sources") sourcesPage();
    else if (r === "about") aboutPage();
    else notFound();
    if (lastPath !== r + "/" + (h[1] || "")) window.scrollTo(0, 0);
    lastPath = r + "/" + (h[1] || "");
    countView();
  }
  var lastPath = "";

  // 按 / 键聚焦搜索框（当前页没有搜索框就去首页搜），Esc 退出
  document.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    var typing = tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable;
    if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      var q = document.getElementById("q") || document.getElementById("rq");
      if (q) { q.focus(); q.select(); }
      else { location.hash = "#/"; setTimeout(function () { var x = document.getElementById("q"); if (x) x.focus(); }, 50); }
    } else if (e.key === "Escape" && typing && tag === "input") e.target.blur();
  });

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
      paintStarCount();
      handleOwnerToggle();
      loadCounter();
      window.addEventListener("hashchange", function () { handleOwnerToggle(); route(); });
      route();
    })
    .catch(function (e) {
      app.innerHTML = '<div class="empty">数据加载失败：' + esc(e.message) + "<br>本地预览请运行 <code>python run.py serve</code>，不要直接双击打开 HTML 文件。</div>";
    });
})();
