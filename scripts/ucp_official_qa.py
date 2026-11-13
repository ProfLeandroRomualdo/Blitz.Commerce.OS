"""Capture live Blitz REST examples and run the official `ucp-schema` CLI.

Exit 0: all selected response contracts passed; exit 1: mismatches;
exit 2: infrastructure/schema/CLI problem. No silent skips.
This is a *selected operation* gate, not UCP certification.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from scripts.github_ucp_contracts import OUT, verify

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ('catalog_search', 'POST', '/ucp/v1/catalog/search', {'query': 'oleo', 'pagination': {'limit': 10}}, 'schemas/shopping/catalog_search.json', 'search'),
    ('catalog_lookup', 'POST', '/ucp/v1/catalog/lookup', {'ids': ['OLEO-001']}, 'schemas/shopping/catalog_lookup.json', 'lookup'),
    ('catalog_product', 'POST', '/ucp/v1/catalog/product', {'id': 'OLEO-001'}, 'schemas/shopping/catalog_lookup.json', 'get_product'),
    ('cart_create', 'POST', '/ucp/v1/carts', {'line_items': [{'item': {'id': 'OLEO-001'}, 'quantity': 1}]}, 'schemas/shopping/cart.json', 'create'),
]


def record_and_check(validator='ucp-schema', report_dir=None, cases=CASES):
    verify()
    schemas = OUT / 'source' / 'schemas'
    if not schemas.is_dir():
        raise RuntimeError('No official schemas/ in the pinned GitHub tree')
    report_dir = Path(report_dir or ROOT / 'reports' / 'ucp')
    report_dir.mkdir(parents=True, exist_ok=True)
    # sqlite isolated from normal data; imports read settings at module import time.
    os.environ['DEMO_MODE'] = 'true'
    os.environ['STRICT_UCP'] = 'false'
    os.environ['DATABASE_PATH'] = str(report_dir / 'qa-temporary.db')
    os.environ['DEMO_API_KEY'] = 'contract-testing-local-only-key'
    os.environ.pop('DATABASE_URL', None)
    from app import main
    from fastapi.testclient import TestClient
    entries=[]
    with TestClient(main.app) as client:
        for name, method, endpoint, payload, schema_rel, operation in cases:
            response=client.request(method,endpoint,headers={'X-API-Key':main.SEED_KEY},json=payload)
            entry={'case':name,'endpoint':endpoint,'http_status':response.status_code,'operation':operation,
                   'schema':schema_rel,'official_validator_exit_code':None}
            if response.status_code >= 400:
                entry['stderr']=response.text[:1200]
                entries.append(entry)
                continue
            output=report_dir / (name + '.json')
            output.write_text(json.dumps(response.json(),indent=2,ensure_ascii=False)+'\n')
            cmd=[validator,'validate',str(output),'--schema',str(schemas/schema_rel),
                 '--response','--op',operation,'--schema-local-base',str(OUT/'source'),
                 '--schema-remote-base','https://ucp.dev/2026-08-25','--json']
            completed=subprocess.run(cmd,text=True,capture_output=True,timeout=75,check=False)
            entry['official_validator_exit_code']=completed.returncode
            entry['stdout']=completed.stdout[:8000]
            entry['stderr']=completed.stderr[:4000]
            entries.append(entry)
    passed=all(e['http_status']<400 and e['official_validator_exit_code']==0 for e in entries) and bool(entries)
    report={'contract_version':'2026-08-25','upstream_commit':verify()['commit'],
            'result':'PASS_SELECTED_CASES' if passed else 'FAIL', 'tested_cases':len(entries),'cases':entries,
            'limitations':['checkout with PSP not covered','HTTP signatures interoperability not covered',
                           'MCP/A2A not covered','merchant discovery external connectivity not covered']}
    (report_dir/'official-qa.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--validator',default='ucp-schema')
    parser.add_argument('--report-dir',type=Path)
    args=parser.parse_args()
    try:
        report=record_and_check(args.validator,args.report_dir)
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired,FileNotFoundError) as exc:
        print('OFFICIAL UCP CHECK NOT EXECUTED: '+str(exc),file=sys.stderr)
        return 2
    print(json.dumps({'result':report['result'],'cases':[(e['case'],e['official_validator_exit_code']) for e in report['cases']]},indent=2))
    return 0 if report['result']=='PASS_SELECTED_CASES' else 1

if __name__=='__main__':
    sys.exit(main())
