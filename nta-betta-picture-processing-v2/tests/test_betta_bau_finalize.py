"""Offline post-archive audit and cleanup tests."""
import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import betta_bau_finalize as final
import betta_telemetry as telemetry

class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name).resolve()
        self.intake=self.root/'intake';self.intake.mkdir()
        self.batch=self.intake/'batches'/'betta-unit';(self.batch/'state').mkdir(parents=True)
        (self.batch/'manifest').mkdir()
        self.original=self.intake/'original.png';self.original.write_bytes(b'fish')
        self.archived=self.root/'archive'/'2026-10-11';self.archived.mkdir(parents=True)
        self.manifest=self.batch/'manifest/shopify-production.json';self.manifest.write_text('{}')
        self.config={'paths':{'archive':str(self.root/'archive'),'intake':str(self.intake),'telemetry':str(self.root/'telemetry.sqlite3')}}
        copied=self.archived/'original.png';copied.write_bytes(self.original.read_bytes())
        manifest_copy=self.archived/'production.json';manifest_copy.write_bytes(self.manifest.read_bytes())
        records=[{'role':'original','tank_id':'2BT12','source_path':str(self.batch/'intake/original.png'),'source_sha256':final.sha(copied),'destination_path':str(copied),'destination_sha256':final.sha(copied)},
                 {'role':'audit','source_path':str(self.manifest),'source_sha256':final.sha(manifest_copy),'destination_path':str(manifest_copy),'destination_sha256':final.sha(manifest_copy)}]
        self.archive_manifest=self.archived/'betta-unit-archive-manifest.json'
        self.archive_manifest.write_text(json.dumps({'batch_id':'betta-unit','batch_status':'COMPLETE','created_at':'2026-10-11T15:00:00+11:00','files':records}))
        state={'batch_id':'betta-unit','stage':'ARCHIVED','status':'COMPLETE','manifest_path':str(self.manifest),'manifest_sha256':final.sha(self.manifest),'executed':['fish'],'fish':{'fish':{'tank_id':'2BT12','source_sha256':final.sha(self.original)}},'archive_receipt':{'status':'ARCHIVED','batch_status':'COMPLETE','manifest':str(self.archive_manifest),'manifest_sha256':final.sha(self.archive_manifest)}}
        (self.batch/'state/process.json').write_text(json.dumps(state))
        (self.batch/'state/sources.json').write_text(json.dumps({'dispatcher_owned':True,'batch_id':'betta-unit','selected_sources':[{'path':str(self.original),'sha256':final.sha(self.original)}]}))
        con=telemetry.connect(Path(self.config['paths']['telemetry']))
        telemetry.upsert(con,{'batch_id':'betta-unit','tank_number':'2BT12','date_entered':'2026-10-11T14:00:00+11:00','shopify_verified_at':'2026-10-11T14:30:00+11:00'})
        con.close()
        self.summary={'batch_id':'betta-unit','status':'COMPLETE','published':1}
    def tearDown(self): self.tmp.cleanup()
    def test_final_csv_timing_outcome_cleanup_and_inert_retry(self):
        result=final.finalize(self.config,self.batch,self.summary)
        self.assertEqual(result['status'],'FINALIZED')
        self.assertFalse(self.original.exists())
        receipt=Path(result['receipt_path']);data=json.loads(receipt.read_text())
        csv_path=next(Path(r['destination']) for r in data['files'] if r['destination'].endswith('.csv'))
        with csv_path.open() as handle: row=next(csv.DictReader(handle))
        self.assertEqual(float(row['end_to_archive_seconds']),3600)
        self.assertEqual(float(row['onboarding_seconds']),1800)
        self.assertTrue(row['archive_completed_at'])
        self.assertEqual(result,final.finalize(self.config,self.batch,self.summary))
    def test_changed_asset_blocks_and_retains_intake(self):
        (self.archived/'original.png').write_bytes(b'changed')
        with self.assertRaises(final.FinalizationError): final.finalize(self.config,self.batch,self.summary)
        self.assertTrue(self.original.exists())
    def test_changed_intake_is_retained_as_new_content(self):
        self.original.write_bytes(b'new fish')
        result=final.finalize(self.config,self.batch,self.summary)
        self.assertTrue(self.original.exists())
        cleanup=json.loads((Path(result['archive_receipt_path']).parent/'intake-cleanup.json').read_text())
        self.assertEqual(cleanup['sources'][0]['status'],'RETAINED_CHANGED_SOURCE')
    def test_replaced_final_csv_blocks_resume(self):
        result=final.finalize(self.config,self.batch,self.summary)
        p=Path(result['archive_receipt_path']).parent/'final-betta-telemetry.csv';p.chmod(0o600);p.write_text('replaced')
        with self.assertRaises(final.FinalizationError): final.finalize(self.config,self.batch,self.summary)
