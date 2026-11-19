import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sandboxhot import build, collect, enrich, pipeline, relevance, store as store_mod  # noqa: E402
from sandboxhot.budget import Budget, BudgetExceeded, credits_for  # noqa: E402
from sandboxhot.config import iso, keywords, now_utc, settings  # noqa: E402
from sandboxhot.digest import run_digests  # noqa: E402
from sandboxhot.llm import LLM, parse_json_block  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
SRC = {"id": "t", "name": "Test", "kind": "rss", "tier": "T2", "group": "aihot", "focused": False}
ARX = {"id": "ax", "name": "arXiv", "kind": "arxiv", "tier": "T1", "group": "academic", "focused": True}


class FakeLLM(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLLM.calls.append(body)
        assert self.headers["Authorization"] == "Bearer sk-test"
        if self.path.endswith("/embeddings"):
            vecs = []
            for t in body["input"]:
                v = [0.0] * 8
                v[0] = 1.0
                v[1 + (len(t) % 7)] = 0.3
                vecs.append(v)
            return self._send({"data": [{"index": i, "embedding": v} for i, v in enumerate(vecs)],
                               "usage": {"prompt_tokens": 50 * len(vecs)}})
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        if "逐条判断" in user:
            mats = json.loads(user.split("\n", 1)[1])
            text = json.dumps({"items": [{"i": m["i"], "applied": True} for m in mats]})
        elif "逐条评估" in user or "独立评估" in user:
            mats = json.loads(user.split("\n", 1)[1])
            out = {"items": [{"i": m["i"], "relevant": "GPU" not in m["title"], "domain": "academic" if m["kind"] == "paper" else "application",
                              "score": 80, "title_zh": "中文标题" + str(m["i"]), "summary_zh": "摘要", "topics": ["wargame", "bogus"],
                              "tags": ["社会仿真"]} for m in mats]}
            text = json.dumps(out, ensure_ascii=False)
        elif "中文精读" in system:
            links = json.loads(user)["links"]
            text = json.dumps({"title_zh": "精读标题", "summary_zh": "精读摘要", "abstract_zh": "中文全文梳理", "why": "值得看",
                               "topics": ["wargame"], "validation": "real_data",
                               "resources": [{"type": "code", "name": "repo", "url": u} for u in links] +
                                            [{"type": "code", "name": "fake", "url": "https://evil.example/fake"}]}, ensure_ascii=False)
        elif "速读卡" in system:
            text = '```json\n{"question":"q","setup":"s","method":"m","findings":"f","validation":"未说明","limits":"l","reuse":"r"}\n```'
        elif "主题研究员" in system:
            text = "### 这段时间发生了什么\n研判内容"
        elif "横纵分析法" in system:
            text = "## 专题标题\n" + "正文" * 300
        elif "事件综述" in system:
            text = "综述"
        else:
            text = "## 测试日报\n导语\n### 学术前沿\n- 条目 [来源](https://example.com)"
        self._send({"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "prompt_tokens_details": {"cached_tokens": 400}}})

    def _send(self, resp):
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(store_mod, "ITEMS", t / "items.json"),
            mock.patch.object(store_mod, "SEEN", t / "seen.json"),
            mock.patch.object(store_mod, "DIGESTS", t / "digests.json"),
            mock.patch.object(store_mod, "RUNTIME", t / "runtime.json"),
            mock.patch.object(store_mod, "ENRICH", t / "enrichments.json"),
            mock.patch.object(build, "SITE_DATA_DIR", t / "site" / "data"),
            mock.patch.object(build, "SITE_DIR", t / "site"),
            mock.patch("sandboxhot.enrich.EMBED_CACHE", t / "embeddings.json"),
            mock.patch("sandboxhot.budget.SHARED_LEDGERS", (t / "cloud-usage.json",)),  # 和仓库里的真实云端账本隔离
        ]
        for p in self.patches:
            p.start()
        (t / "site").mkdir()
        self.cfg = settings()
        self.ledger = t / "usage.json"

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class TestCollect(unittest.TestCase):
    def test_rss_and_canonical(self):
        items = collect.parse_feed((FIX / "feed.xml").read_text(), SRC)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["url"], "https://example.com/a")
        self.assertNotIn("<p>", items[0]["text"])

    def test_arxiv(self):
        items = collect.parse_arxiv((FIX / "arxiv.xml").read_text(), ARX)
        self.assertEqual(items[0]["url"], "https://arxiv.org/abs/2611.01234")
        self.assertEqual(items[0]["kind"], "paper")
        self.assertEqual(items[0]["extra"]["pdf"], "https://arxiv.org/pdf/2611.01234")
        self.assertEqual(items[0]["authors"], ["A. Researcher", "B. Scholar"])
        self.assertEqual(collect.item_id("http://arxiv.org/pdf/2611.01234v1"), items[0]["id"])

    def test_openalex_abstract(self):
        self.assertEqual(collect._openalex_abstract({"world": [1], "hello": [0]}), "hello world")


class TestRelevance(unittest.TestCase):
    def test_prefilter(self):
        kw, cfg = keywords(), settings()
        a, b = collect.parse_feed((FIX / "feed.xml").read_text(), SRC)
        for it in (a, b):
            it.update(relevance.keyword_score(it, kw))
        self.assertTrue(relevance.passes_prefilter(a, cfg))
        self.assertFalse(relevance.passes_prefilter(b, cfg))

    def test_code_sandbox_is_penalized(self):
        kw = keywords()
        it = {"title": "Secure code sandbox for AI agents", "text": "sandboxed execution with firecracker", "focused": False}
        self.assertLess(relevance.keyword_score(it, kw)["kw_score"], settings()["pipeline"]["keyword_threshold"])

    def test_domain_guess(self):
        kw = keywords()
        self.assertEqual(relevance.guess_domain({"kind": "paper", "title": "x"}, kw), "academic")
        self.assertEqual(relevance.guess_domain({"kind": "news", "title": "AI NPC game simulation", "text": ""}, kw), "game")


class TestBudget(Base):
    def test_cost_formula(self):
        p = self.cfg["prices"]
        # 指南示例：DeepSeek-V4.1-Flash 输入 1000 + 输出 1000，无缓存 ≈ 0.1 积分
        self.assertAlmostEqual(credits_for(p, "DeepSeek-V4.1-Flash", 1000, 0, 1000), 0.1)
        self.assertAlmostEqual(credits_for(p, "Kimi-K3.1-Pro", 1000, 0, 1000), 1.62)

    def test_caps(self):
        b = Budget(self.cfg, path=self.ledger)
        b.data["entries"].append({"at": iso(now_utc()), "model": "x", "purpose": "t", "prompt": 0, "cached": 0,
                                  "completion": 0, "credits": b.weekly_cap - 0.01})
        with self.assertRaises(BudgetExceeded):
            b.check("DeepSeek-V4.1-Flash", 10000, 2000)
        b.data["entries"][0]["at"] = iso(now_utc() - timedelta(days=8))  # 滚出 7 天窗口
        b.check("DeepSeek-V4.1-Flash", 10000, 2000)

    def test_shared_cloud_ledger(self):
        """笔记本把云端账本算进滚动 7 天用量；云端把共享账本复制成自己的账本时不重复计算。"""
        import sandboxhot.budget as bm
        shared = Path(self.tmp.name) / "cloud-usage.json"
        e = {"at": iso(now_utc()), "model": "x", "purpose": "t", "prompt": 1, "cached": 0, "completion": 1, "credits": 10.0}
        shared.write_text(json.dumps({"entries": [e]}))
        with mock.patch.object(bm, "SHARED_LEDGERS", (shared,)):
            self.assertAlmostEqual(Budget(self.cfg, path=self.ledger).spent_7d(), 10.0)  # 笔记本：自己 0 + 云端 10
            self.ledger.write_text(json.dumps({"entries": [e]}))
            self.assertAlmostEqual(Budget(self.cfg, path=self.ledger).spent_7d(), 10.0)  # 云端：同一条不重复

    def test_parse_json(self):
        self.assertEqual(parse_json_block('好的：\n```json\n{"a": 1}\n```'), {"a": 1})
        self.assertIsNone(parse_json_block("no json"))


class TestPipeline(Base):
    def _server(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}/v1"

    def test_end_to_end_with_fake_llm(self):
        base = self._server()
        env = {"TONGJI_API_KEY": "sk-test", "TONGJI_BASE_URL": base, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
        raw = collect.parse_feed((FIX / "feed.xml").read_text(), SRC) + collect.parse_arxiv((FIX / "arxiv.xml").read_text(), ARX)
        for it in raw:
            it["published"] = iso(now_utc() - timedelta(hours=30))
            it["text"] = (it["text"] + " ") * 6
        with mock.patch.dict(os.environ, env), mock.patch.object(collect, "collect", return_value=raw), \
                mock.patch("sandboxhot.budget.LEDGER", self.ledger), mock.patch.object(Budget.__init__, "__defaults__", (self.ledger,)):
            FakeLLM.calls = []
            pipeline.update(log=lambda *a: None)
            st = store_mod.Store()
            sel = [i for i in st.items.values() if i["status"] == "selected"]
            self.assertEqual(len(sel), 2)  # GPU 新闻被本地预筛挡掉，不会发给模型
            self.assertTrue(all(i["llm"] and i["title_zh"] == "精读标题" for i in sel))  # 精读覆盖精选的标题
            paper = next(i for i in sel if i["kind"] == "paper")
            self.assertEqual(paper["domain"], "academic")
            self.assertEqual(paper["brief"]["question"], "q")
            triage_calls = [c for c in FakeLLM.calls if "逐条评估" in c["messages"][1]["content"]]
            self.assertEqual(len(triage_calls), 1)  # 两条合并在一个批次里
            self.assertEqual(triage_calls[0]["reasoning_effort"], "none")
            self.assertTrue(all(c["messages"][0]["content"] == triage_calls[0]["messages"][0]["content"] for c in triage_calls))
            ledger = json.loads(self.ledger.read_text())
            self.assertGreater(len(ledger["entries"]), 0)
            self.assertEqual(ledger["entries"][0]["cached"], 400)
            # 第二次运行：没有新内容就不会再次调用模型
            n = len(FakeLLM.calls)
            pipeline.update(log=lambda *a: None)
            self.assertEqual(len(FakeLLM.calls), n)
        site = json.loads((Path(self.tmp.name) / "site" / "data" / "items.json").read_text())
        self.assertEqual(len(site["items"]), 2)
        self.assertNotIn("sk-test", (Path(self.tmp.name) / "site" / "data" / "items.json").read_text())

    def test_cloud_rules_then_laptop_enrich(self):
        """云端纯规则采集 → 笔记本 enrich 只写 enrichments.json → 云端下次构建合并模型结果。"""
        base = self._server()
        raw = collect.parse_feed((FIX / "feed.xml").read_text(), SRC) + collect.parse_arxiv((FIX / "arxiv.xml").read_text(), ARX)
        for it in raw:
            it["published"] = iso(now_utc() - timedelta(hours=2))
            it["text"] = (it["text"] + " ") * 6
        t = Path(self.tmp.name)
        with mock.patch.object(collect, "collect", return_value=raw), mock.patch.object(Budget.__init__, "__defaults__", (self.ledger,)):
            pipeline.update(use_llm=False, log=lambda *a: None)  # 云端
            items_before = (t / "items.json").read_text()
            self.assertTrue(all(not i["llm"] for i in store_mod.Store().items.values()))
            env = {"TONGJI_API_KEY": "sk-test", "TONGJI_BASE_URL": base, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(LLM, "list_models", return_value=["DeepSeek-V4.1-Flash"]):
                self.assertEqual(pipeline.enrich_only(log=lambda *a: None), 0)  # 笔记本
            self.assertEqual((t / "items.json").read_text(), items_before)  # 笔记本不改云端文件
            enr = json.loads((t / "enrichments.json").read_text())
            self.assertEqual(len(enr["triage"]), 2)
            self.assertNotIn("sk-test", (t / "enrichments.json").read_text())
            pipeline.update(use_llm=False, fetch=False, log=lambda *a: None)  # 云端再次构建
        site = json.loads((t / "site" / "data" / "items.json").read_text())["items"]
        self.assertEqual(len(site), 2)
        self.assertTrue(all(i["ai"] and i["title_zh"] for i in site))

    def test_enrich_full_features(self):
        """精读、双评、资源防编造、embedding 相关推荐、主题研判、横纵专题、导出与云端合并、站点新文件。"""
        base = self._server()
        t = Path(self.tmp.name)
        raw = collect.parse_feed((FIX / "feed.xml").read_text(), SRC) + collect.parse_arxiv((FIX / "arxiv.xml").read_text(), ARX)
        for k in range(10):  # 再造 10 篇兵棋论文，凑够主题研判和专题报告的门槛
            it = dict(raw[-1]); it["url"] = f"https://arxiv.org/abs/2611.0{k:04d}"; it["id"] = collect.item_id(it["url"])
            it["title"] = f"LLM wargame simulation study {k}"
            raw.append(it)
        for it in raw:
            it["published"] = iso(now_utc() - timedelta(days=2))
            it["text"] = (it["text"] + " Code: https://github.com/org/wargame-sim. ") * 4
        cfg = settings()
        cfg["research"]["report_min_items"] = 5
        with mock.patch.object(collect, "collect", return_value=raw), mock.patch.object(Budget.__init__, "__defaults__", (self.ledger,)), \
                mock.patch("sandboxhot.pipeline.settings", return_value=cfg), mock.patch("sandboxhot.research.topics", wraps=__import__("sandboxhot.config", fromlist=["topics"]).topics):
            pipeline.update(use_llm=False, log=lambda *a: None)
            env = {"TONGJI_API_KEY": "sk-test", "TONGJI_BASE_URL": base, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
            with mock.patch.dict(os.environ, env), mock.patch.object(LLM, "list_models", return_value=["x"]):
                FakeLLM.calls = []
                self.assertEqual(pipeline.enrich_only(log=lambda *a: None), 0)
            enr = json.loads((t / "enrichments.json").read_text())
            pipeline.update(use_llm=False, fetch=False, log=lambda *a: None)  # 云端合并
        paths = [c.get("messages", [{}])[0].get("content", "")[:12] if "messages" in c else "embed" for c in FakeLLM.calls]
        self.assertIn("embed", paths)
        self.assertGreater(len(enr["reads"]), 5)
        read = next(iter(enr["reads"].values()))
        self.assertEqual(read["topics"], ["wargame"])
        self.assertTrue(all(r["url"] != "https://evil.example/fake" for r in read["resources"]))  # 材料里没有的链接被丢弃
        self.assertIn("https://github.com/org/wargame-sim", [r["url"] for r in read["resources"]])
        self.assertIn("wargame", enr["topic_analyses"])
        self.assertEqual(len(enr["research"]), 1)
        self.assertTrue(enr["related"])
        tri = next(iter(enr["triage"].values()))
        self.assertEqual(tri["topics"], ["wargame"])  # 非法主题 bogus 被过滤
        site = t / "site"
        items = json.loads((site / "data" / "items.json").read_text())["items"]
        self.assertTrue(all(i.get("read") and i["why"] == "值得看" for i in items))
        shard = json.loads((site / "data" / "details" / f"{items[0]['id'][0]}.json").read_text())
        self.assertEqual(shard[items[0]["id"]]["abstract_zh"], "中文全文梳理")
        topics_json = json.loads((site / "data" / "topics.json").read_text())["topics"]
        self.assertTrue(next(x for x in topics_json if x["slug"] == "wargame")["analysis"])
        self.assertEqual(len(json.loads((site / "data" / "research.json").read_text())["reports"]), 1)
        self.assertTrue(json.loads((site / "data" / "resources.json").read_text())["resources"])
        self.assertTrue(all("applied" in v for v in enr["triage"].values()))
        self.assertTrue((site / "llms.txt").exists() and (site / "api" / "latest.json").exists())
        # 云端保存的 items.json 不含精读大字段（只在 enrichments.json 里）
        self.assertNotIn("abstract_zh", (t / "items.json").read_text())

    def test_pacing(self):
        b = Budget(self.cfg, path=self.ledger)
        self.assertTrue(b.allow("backfill"))
        b.data["entries"].append({"at": iso(now_utc()), "model": "x", "purpose": "t", "prompt": 0, "cached": 0,
                                  "completion": 0, "credits": b.daily_target})  # 今天已花到目标
        self.assertTrue(b.allow("essential"))
        self.assertTrue(b.allow("normal"))
        self.assertFalse(b.allow("backfill"))
        b.data["entries"][0]["credits"] = b.daily_target * 1.3
        self.assertFalse(b.allow("normal"))
        with mock.patch.object(Budget, "time_left", return_value=-1):
            with self.assertRaises(BudgetExceeded):
                b.check("DeepSeek-V4.1-Flash", 10, 10)

    def test_arxiv_backfill(self):
        src = dict(ARX, query="all:x", max_results=60, backfill={"since": "2023-01-01", "page_size": 100, "pages_per_fetch": 2, "max_pages": 6})
        state = {}
        page = (FIX / "arxiv.xml").read_text()
        with mock.patch.object(collect.net, "get_text", side_effect=[page, page.replace("<entry>", "<x>").replace("</entry>", "</x>")]), \
                mock.patch.object(collect.time, "sleep"):
            out = collect.fetch_arxiv_backfill(src, state, log=lambda *a: None)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["backfill"])
        self.assertTrue(state["backfill"]["ax"]["done"])  # 第二页为空：回填结束

    def test_enrich_offline_exits(self):
        with mock.patch.dict(os.environ, {"TONGJI_API_KEY": "sk-test", "TONGJI_BASE_URL": "http://127.0.0.1:9/v1", "NO_PROXY": "127.0.0.1"}), \
                mock.patch.object(Budget.__init__, "__defaults__", (self.ledger,)):
            self.assertEqual(pipeline.enrich_only(log=lambda *a: None), 1)
        self.assertFalse((Path(self.tmp.name) / "enrichments.json").exists())

    def test_offline_rule_mode(self):
        raw = collect.parse_feed((FIX / "feed.xml").read_text(), SRC)
        raw[0]["published"] = iso(now_utc())
        with mock.patch.object(collect, "collect", return_value=raw), mock.patch.object(Budget.__init__, "__defaults__", (self.ledger,)):
            pipeline.update(use_llm=False, log=lambda *a: None)
        st = store_mod.Store()
        it = next(iter(st.items.values()))
        self.assertFalse(it["llm"])
        self.assertIn(it["status"], ("selected", "filtered"))

    def test_digest_rule_version(self):
        st = store_mod.Store()
        tz_yesterday = now_utc() - timedelta(days=1)
        for k in range(4):
            st.items[f"i{k}"] = {"id": f"i{k}", "url": f"https://e.com/{k}", "title": f"T{k}", "status": "selected", "score": 70,
                                 "domain": "academic", "source_name": "S", "source_id": "s", "added": iso(tz_yesterday.replace(hour=4)),
                                 "published": iso(tz_yesterday)}
        llm = LLM(self.cfg, Budget(self.cfg, path=self.ledger), enabled=False, log=lambda *a: None)
        run_digests(st, self.cfg, llm, log=lambda *a: None)
        self.assertTrue(any(not d["ai"] for d in st.digests["daily"]))


if __name__ == "__main__":
    unittest.main()
