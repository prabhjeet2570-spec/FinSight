from app.contracts import Filing
from app.import_jobs import ImportWorker
from app.store import Store


def test_persistent_import_queue_deduplicates_and_resumes(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    filing = Filing(
        id="fixture",
        ticker="DEMO",
        company="Fixture",
        cik="0000000001",
        form="10-K",
        fiscal_year=2024,
        period_end="2024-12-31",
        accession="0000000001-24-000001",
        source_url="https://www.sec.gov/Archives/edgar/data/1/000000000124000001/test.html",
    )
    content = b"<html><p>Fixture filing narrative with enough meaningful text to produce a sourced chunk.</p></html>"
    worker = ImportWorker(store)
    job = worker.submit(filing, content)
    assert worker.submit(filing, content)["id"] == job["id"]
    with store.connect() as db:
        db.execute("UPDATE jobs SET status='processing' WHERE id=?", (job["id"],))
    monkeypatch.setattr("app.import_jobs.build_index", lambda _: None)
    worker2 = ImportWorker(Store(store.path))
    worker2.start()
    import time

    for _ in range(30):
        if worker2.get(job["id"])["status"] == "ready":
            break
        time.sleep(0.05)
    worker2.close()
    assert worker2.get(job["id"])["status"] == "ready"
    assert len(store.list_filings()) == 1


def test_failed_import_has_no_partial_filing_and_can_retry(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    w = ImportWorker(store)
    f = Filing(
        id="empty",
        ticker="DEMO",
        company="Fixture",
        cik="0000000001",
        form="10-K",
        fiscal_year=2024,
        period_end="2024-12-31",
        accession="0000000001-24-000001",
        source_url="https://www.sec.gov/Archives/edgar/data/1/000000000124000001/test.html",
    )
    job = w.submit(f, b"<html></html>")
    w.process_one()
    assert w.get(job["id"])["status"] == "failed"
    assert not store.list_filings()
    assert w.retry(job["id"])["status"] == "pending"
