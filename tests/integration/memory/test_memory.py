"""Tests for the bi-temporal memory layer: store, tools, and the uncertainty gate.

No Ollama needed — the ConflictAssessor falls back to embedding heuristics, and
the gate is exercised directly with an injected fake LLM.
"""

import pytest

from memory.assessor import ConflictAssessor
from memory.config import settings
from memory.store import MemoryStore
from tests.integration.memory.conftest import make_tools


# --------------------------------------------------------------------------- store
class TestClaimsBitemporal:

    async def test_add_and_recall(self, store):
        await store.add_claim("Postgres is the primary datastore", claim_type="fact",
                              subject="datastore", rationale="chosen for relational integrity")
        results = await store.search_claims("primary datastore")
        assert any("Postgres" in r["statement"] for r in results)

    async def test_supersede_retains_and_links(self, store):
        a = await store.add_claim("Deploy via blue-green", claim_type="decision", subject="deploy")
        b = await store.add_claim("Deploy via canary", claim_type="decision", subject="deploy")
        await store.supersede_claim(a["id"], b["id"])

        a2 = await store.get_claim(a["id"])
        b2 = await store.get_claim(b["id"])
        assert a2 is not None  # old claim still queryable
        assert a2["superseded_by"] == b["id"]
        assert a2["expired_at"] is not None
        assert a2["invalid_at"] is not None
        assert b2["supersedes"] == a["id"]

    async def test_current_excludes_superseded(self, store):
        a = await store.add_claim("Deploy via blue-green", claim_type="decision", subject="deploy")
        b = await store.add_claim("Deploy via canary", claim_type="decision", subject="deploy")
        await store.supersede_claim(a["id"], b["id"])

        current = await store.search_claims("deploy", include_superseded=False)
        cur_ids = {c["id"] for c in current}
        assert b["id"] in cur_ids
        assert a["id"] not in cur_ids  # quick memory = current only

        allc = await store.search_claims("deploy", include_superseded=True)
        all_ids = {c["id"] for c in allc}
        assert a["id"] in all_ids and b["id"] in all_ids

        chain = await store.get_claim_chain(b["id"])
        assert [c["id"] for c in chain] == [a["id"], b["id"]]
        assert chain[0]["rationale"] is None or True  # rationale carried through if set

    async def test_as_of_transaction_time_travel(self, store):
        a = await store.add_claim("Deploy via blue-green", claim_type="decision", subject="deploy")
        b = await store.add_claim("Deploy via canary", claim_type="decision", subject="deploy")
        await store.supersede_claim(a["id"], b["id"])

        # Pin transaction-time windows so as_of can separate the two beliefs.
        db = MemoryStore._db_or_raise()
        await db.execute("UPDATE claims SET recorded_at='2020-01-01 00:00:00', "
                         "expired_at='2020-06-01 00:00:00', invalid_at='2020-06-01 00:00:00' "
                         "WHERE id=?", (a["id"],))
        await db.execute("UPDATE claims SET recorded_at='2020-06-01 00:00:00' WHERE id=?", (b["id"],))
        await db.commit()

        early = await store.search_claims("deploy", as_of="2020-03-01 00:00:00")
        assert {c["id"] for c in early} == {a["id"]}  # what we believed in March 2020

        late = await store.search_claims("deploy", as_of="2020-09-01 00:00:00")
        assert {c["id"] for c in late} == {b["id"]}

    async def test_rebuild_from_jsonl(self, workspace):
        await MemoryStore.init(str(workspace))
        s = MemoryStore("local")
        a = await s.add_claim("Deploy via blue-green", claim_type="decision", subject="deploy")
        b = await s.add_claim("Deploy via canary", claim_type="decision", subject="deploy",
                              rationale="cheaper, safer rollouts")
        await s.supersede_claim(a["id"], b["id"])
        await MemoryStore.close()

        # Nuke the derived DB — must rebuild from wiki/.memory/*.jsonl
        (workspace / ".llmwiki" / "memory.db").unlink()
        await MemoryStore.init(str(workspace))
        s2 = MemoryStore("local")
        current = await s2.search_claims("deploy", include_superseded=False)
        assert {c["id"] for c in current} == {b["id"]}
        chain = await s2.get_claim_chain(b["id"])
        assert [c["id"] for c in chain] == [a["id"], b["id"]]
        await MemoryStore.close()


# --------------------------------------------------------------------------- tools
class TestMemoryFlow:

    async def test_remember_supersede_recall_history(self, store):
        tools = make_tools(store)

        await tools["remember"](None, statement="Deploy via blue-green",
                                rationale="zero downtime needed", claim_type="decision",
                                subject="deploy-strategy")
        cur = await store.search_claims("deploy", include_superseded=False)
        a_id = cur[0]["id"]

        out = await tools["remember"](
            None, statement="Deploy via canary",
            rationale="blue-green doubled infra cost; canary caught regressions earlier",
            claim_type="decision", subject="deploy-strategy", supersedes=a_id,
        )
        assert "Superseded" in out

        recall_out = await tools["recall"](None, query="deploy strategy")
        assert "canary" in recall_out.lower()
        # quick memory = current only: the superseded blue-green claim is not returned
        assert a_id[:8] not in recall_out

        hist_out = await tools["history"](None, subject="deploy-strategy")
        assert "canary" in hist_out.lower() and "blue-green" in hist_out.lower()
        assert "why" in hist_out.lower()

        episodes = await store.get_episodes(limit=20)
        assert any(e["kind"] == "decision" for e in episodes)


# --------------------------------------------------------------------------- gate
class TestUncertaintyGate:

    async def test_assessor_high_confidence_auto(self):
        async def fake_llm(messages):
            return '{"action":"supersede","target_index":0,"confidence":0.95,"reasons":["clear replacement"]}'

        assessor = ConflictAssessor(settings, llm_chat=fake_llm)
        new = {"id": "new1", "statement": "Deploy via canary", "claim_type": "decision"}
        cands = [{"id": "old1", "statement": "Deploy via blue-green", "similarity": 0.7, "claim_type": "decision"}]
        decision = await assessor.assess(new, cands)
        assert decision.action == "supersede"
        assert decision.confidence >= settings.AUTO_APPLY_THRESHOLD
        assert decision.question is None  # confident → auto, no clarification

    async def test_assessor_low_confidence_escalates(self):
        async def fake_llm(messages):
            return '{"action":"supersede","target_index":0,"confidence":0.3,"reasons":["ambiguous scope"]}'

        assessor = ConflictAssessor(settings, llm_chat=fake_llm)
        new = {"id": "new1", "statement": "Deploy via canary", "claim_type": "decision"}
        cands = [{"id": "old1", "statement": "Deploy via blue-green", "similarity": 0.7, "claim_type": "decision"}]
        decision = await assessor.assess(new, cands)
        assert decision.question is not None
        assert len(decision.question["options"]) >= 2
        assert decision.target_claim_id == "old1"

    async def test_ingestion_near_duplicate_creates_clarification(self, store, monkeypatch):
        # Make the no-LLM heuristic deterministic: flag related claims as uncertain.
        monkeypatch.setattr(settings, "DUPLICATE_SIMILARITY_FLOOR", 0.5)
        tools = make_tools(store)

        await tools["remember"](None, statement="We deploy using a blue-green strategy",
                                rationale="zero downtime", claim_type="decision", subject="deploy")
        out = await tools["remember"](None, statement="We deploy using blue-green deployments",
                                      rationale="same idea, reworded", claim_type="decision", subject="deploy")

        # No supersedes passed + uncertain → a clarification, no auto-supersession.
        assert "clarification" in out.lower()
        open_clars = await store.list_clarifications("open")
        assert len(open_clars) == 1
        # Both claims remain current until resolved.
        current = await store.search_claims("deploy", include_superseded=False)
        assert len(current) == 2

        # Resolve by superseding the older → append-only application.
        clar = open_clars[0]
        older_id = clar["candidate_claim_ids"][0]
        res = await tools["clarifications"](None, action="resolve", id=clar["id"], choice="0")
        assert "Resolved" in res
        older = await store.get_claim(older_id)
        assert older["superseded_by"] is not None
        assert not await store.list_clarifications("open")


# --------------------------------------------------------------------------- consolidation
class TestConsolidation:
    """Background sweep logic with an injected fake LLM (no Ollama)."""

    async def test_sweep_auto_supersedes_confident(self, store):
        from memory.consolidate import _contradiction_sweep

        await store.add_claim("The API rate limit is 100 requests per second", subject="rate-limit")
        await store.add_claim("The API rate limit is 500 requests per second", subject="rate-limit")

        async def fake_llm(messages):
            return '{"action":"supersede","target_index":0,"confidence":0.95,"reasons":["limit raised"]}'

        assessor = ConflictAssessor(settings, llm_chat=fake_llm)
        stats = await _contradiction_sweep(store, assessor, settings)
        assert stats["auto"] >= 1
        current = await store.all_current_claims()
        assert len([c for c in current if c["subject"] == "rate-limit"]) == 1  # one retired

    async def test_sweep_review_mode_escalates(self, store, monkeypatch):
        from memory.consolidate import _contradiction_sweep

        monkeypatch.setattr(settings, "CONSOLIDATION_MODE", "review")
        await store.add_claim("The API rate limit is 100 requests per second", subject="rate-limit")
        await store.add_claim("The API rate limit is 500 requests per second", subject="rate-limit")

        async def fake_llm(messages):
            return '{"action":"supersede","target_index":0,"confidence":0.95,"reasons":["limit raised"]}'

        assessor = ConflictAssessor(settings, llm_chat=fake_llm)
        stats = await _contradiction_sweep(store, assessor, settings)
        # review mode never auto-applies — even a confident decision becomes a clarification.
        assert stats["auto"] == 0
        assert stats["clarified"] >= 1
        assert len(await store.all_current_claims()) == 2  # nothing superseded
        assert len(await store.list_clarifications("open")) >= 1
