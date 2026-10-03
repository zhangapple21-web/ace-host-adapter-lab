"""Isolated bridge fixtures; never production ACE memory."""
import json
import tempfile
import unittest
from pathlib import Path
from ace_host_adapter import handle, PROTOCOL, _read_json, _read_lineage

class QueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ace-query-nonproduction-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
    def put(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data), encoding='utf-8-sig')
        return target
    def query(self, text, kind='auto', **extra):
        request = dict(protocol=PROTOCOL, request_id='test', host_id='fixture', action='query', query=text, query_type=kind)
        request.update(extra)
        return handle(request, self.root)
    def test_tasks_all_statuses_and_no_body(self):
        self.put('task_pool/active/RQ-one.json', {'task_id':'RQ-one','status':'active','body':'private'})
        result = self.query('task', 'tasks')['cognition']
        self.assertEqual(result['result'], [{'task_id':'RQ-one','status':'active'}])
    def test_missing_fa_not_claimed(self):
        result = self.query('FA', 'map')['cognition']
        self.assertEqual(result['epistemic_status'], 'UNKNOWN')
        self.assertEqual(result['result'], [])
    def test_false_fa_substring(self):
        self.assertEqual(self.query('failure')['cognition']['result'], [])
    def test_path_and_mutation_refusal(self):
        for text in ('C:/Windows/system.ini', '../secret.json', 'execute FA', '删除自由区'):
            self.assertEqual(self.query(text)['cognition']['errors'][0], 'arbitrary_path_or_mutation_query_refused', text)
    def test_invalid_args(self):
        for extra in ({'limit':True}, {'limit':1.5}, {'limit':101}, {'query_type':'bad'}, {'path':'secret'}):
            response = self.query('status', **extra)
            self.assertTrue(response['status'] == 'REFUSED' or response['cognition']['epistemic_status'] == 'UNKNOWN')
    def test_bom_snapshot_and_unknown_liveness(self):
        self.put('06_RUNTIME/ace/data/memory/daemon_state.json', {'run_status':'fixture','api_key':'hidden'})
        result = self.query('status', 'status')['cognition']['result'][0]
        self.assertEqual(result['run_status'], 'fixture')
        self.assertEqual(result['liveness'], 'UNKNOWN')
        self.assertNotIn('api_key', result)
        self.assertIn('freshness', result)
    def test_lineage_bound_and_malformed(self):
        path = self.root/'06_RUNTIME/ace/data/local_archaeologist_state.lineage.jsonl'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'x' * (1024 * 1024 + 1))
        result = _read_lineage(self.root, 2)
        self.assertFalse(result['available'])
        self.assertEqual(result['reason'], 'snapshot_too_large')
    def test_read_json_size_and_escape(self):
        path = self.root/'large.json'
        path.write_bytes(b'x'*(1024*1024+1))
        with self.assertRaises(ValueError): _read_json(path,self.root)
        with self.assertRaises(ValueError): _read_json(self.root.parent/'outside.json',self.root)

if __name__ == '__main__': unittest.main()
