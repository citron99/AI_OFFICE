from datetime import date

from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.services.legal_change_radar import compare_chunks


def _source(source_id: str, version: str) -> KnowledgeSourceRecord:
    return KnowledgeSourceRecord(
        id=source_id,
        artifact_id=f"art_{source_id}",
        company_id="comp_demo",
        owner_id="usr_demo_owner",
        title="Synthetic regulation",
        jurisdiction="LV",
        document_type="regulation",
        authority="Synthetic authority",
        version=version,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        status="ACTIVE",
        classification="INTERNAL",
        language="en",
        sha256="a" * 64,
        embedding_model="mock",
        embedding_dimensions=128,
        chunk_count=1,
    )


def test_change_diff_preserves_both_exact_citations_and_flags_attention():
    baseline = _source("src_old", "v1")
    current = _source("src_new", "v2")
    before = KnowledgeChunkRecord(
        id="chk_old",
        source_id=baseline.id,
        ordinal=0,
        text="The report is submitted monthly.",
        locator="article 4",
        page=1,
        article="4",
        embedding=[0.0] * 128,
    )
    after = KnowledgeChunkRecord(
        id="chk_new",
        source_id=current.id,
        ordinal=0,
        text="The report must be submitted weekly; a penalty applies.",
        locator="article 4",
        page=1,
        article="4",
        embedding=[0.0] * 128,
    )

    changes = compare_chunks(baseline, current, [before], [after])

    assert len(changes) == 1
    assert changes[0]["change_type"] == "modified"
    assert changes[0]["impact_signal"] == "high_attention"
    assert changes[0]["before"]["quote"] == before.text
    assert changes[0]["after"]["quote"] == after.text
