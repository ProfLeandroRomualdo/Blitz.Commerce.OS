"""Unit tests for the fail-closed official GitHub checkout/QA pipeline.

These tests do not themselves validate UCP compatibility.
"""
from pathlib import Path
import json
import subprocess
import pytest

from scripts import github_ucp_contracts as g
from scripts import ucp_official_qa as qa


def test_release_is_immutable_full_sha():
    assert len(g.COMMIT)==40
    assert g.TAG=='v2026-08-25'
    assert qa.CASES and len({c[0] for c in qa.CASES})==len(qa.CASES)


def test_checkout_rejects_wrong_commit(tmp_path, monkeypatch):
    (tmp_path/'source'/'schemas').mkdir(parents=True)
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**kw:'0'*40+'\n')
    with pytest.raises(ValueError,match='Incorrect upstream revision'):
        g.snapshot(tmp_path)


def test_snapshot_and_tamper_detection(tmp_path,monkeypatch):
    checkout=tmp_path/'checkout'
    schema=checkout/'source'/'schemas'/'shopping'/'sample.json'
    schema.parent.mkdir(parents=True)
    schema.write_text('{"type":"object"}')
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**kw:g.COMMIT+'\n')
    monkeypatch.setattr(g,'OUT',tmp_path/'out')
    manifest=g.snapshot(checkout)
    assert manifest['commit']==g.COMMIT
    assert len(g.verify()['files'])==1
    (g.OUT/'source'/'schemas'/'shopping'/'sample.json').write_text('{}')
    with pytest.raises(ValueError,match='changed'):
        g.verify()


def test_snapshot_rejects_missing_source(tmp_path,monkeypatch):
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**kw:g.COMMIT+'\n')
    with pytest.raises(ValueError,match='missing source'):
        g.snapshot(tmp_path)


def test_cli_cases_use_official_contract_paths():
    assert all(case[4].startswith('schemas/shopping/') and case[5] for case in qa.CASES)
    assert all(case[2].startswith('/ucp/v1/') for case in qa.CASES)


def test_no_official_source_cannot_report_pass(tmp_path,monkeypatch):
    monkeypatch.setattr(g,'OUT',tmp_path/'absent')
    with pytest.raises(FileNotFoundError):
        g.verify()
