"""API regression tests; all writes go to a temporary report store."""

import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import web_app


class ReportVerificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.temp.name) / 'items.json'
        self.data_file.write_text('[]')
        self.data_patch = patch.object(web_app, 'DATA_FILE', str(self.data_file))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.addCleanup(self.temp.cleanup)

    async def request(self, method, path, body=None):
        """Exercise the actual ASGI app without an extra HTTP test dependency."""
        path, _, query = path.partition('?')
        messages = []
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                await asyncio.Event().wait()
            delivered = True
            return {'type': 'http.request', 'body': json.dumps(body).encode() if body is not None else b'', 'more_body': False}

        async def send(message):
            messages.append(message)

        await web_app.app({
            'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
            'query_string': query.encode(), 'headers': [(b'content-type', b'application/json')],
            'server': ('test', 80), 'client': ('127.0.0.1', 1234), 'root_path': '',
        }, receive, send)
        start = next(m for m in messages if m['type'] == 'http.response.start')
        raw = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
        return start['status'], json.loads(raw), dict(start['headers'])

    async def create(self, report_type='LOST'):
        status, report, _ = await self.request('POST', '/api/items', {
            'report_type': report_type, 'title': 'Tumbler hitam', 'category': 'Botol / Tumbler',
            'location': 'Kantin', 'description': 'Dengan stiker kecil', 'contact': 'kontak-uji',
        })
        self.assertEqual(status, 200)
        return report

    def resolution(self, reason='RETURNED'):
        return {'reason': reason, 'confirmed': True}


    async def test_board_matches_both_directions_and_excludes_closed_reports(self):
        lost = await self.create()
        found = await self.create('FOUND')
        same_type = await self.create()
        status, reports, _ = await self.request('GET', '/api/items?include_matches=true')
        self.assertEqual(status, 200)
        matches = {report['id']: report.get('matches', []) for report in reports}
        self.assertEqual([match['id'] for match in matches[lost['id']]], [found['id']])
        self.assertEqual({match['id'] for match in matches[found['id']]}, {lost['id'], same_type['id']})
        self.assertEqual(matches[lost['id']][0]['match_basis'], 'text')
        status, _, _ = await self.request('PATCH', f"/api/items/{found['id']}/resolve", self.resolution())
        self.assertEqual(status, 200)
        _, reports, _ = await self.request('GET', '/api/items?include_matches=true')
        self.assertTrue(all(not report['matches'] for report in reports))

    async def test_visual_match_ranks_first_even_with_different_titles(self):
        lost = await self.create()
        text_match = await self.create('FOUND')
        photo_match = await self.create('FOUND')
        items = json.loads(self.data_file.read_text())
        items[0]['photo_embedding'] = [1.0, 0.0]
        items[2].update(title='Botol minum', description='Polos', photo_embedding=[1.0, 0.0])
        self.data_file.write_text(json.dumps(items))
        _, matches, _ = await self.request('GET', f"/api/items/{lost['id']}/matches")
        self.assertEqual([match['id'] for match in matches], [photo_match['id'], text_match['id']])
        self.assertEqual(matches[0]['match_basis'], 'photo')
        self.assertNotIn('photo_embedding', matches[0])

    async def test_pin_and_credential_fields_are_absent_from_lists_and_matches(self):
        lost = await self.create()
        await self.create('FOUND')
        private = {'pin', 'management_pin', 'pin_hash', 'pin_salt', 'pin_failed_attempts', 'pin_locked_until'}
        stored = json.loads(self.data_file.read_text())
        self.assertFalse(any(private.intersection(report) for report in stored))
        stored[1].update(pin_hash='legacy-hash', pin_salt='legacy-salt')
        self.data_file.write_text(json.dumps(stored))
        for path in ['/api/items', f"/api/items/{lost['id']}/matches"]:
            status, reports, _ = await self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertTrue(reports)
            for report in reports:
                self.assertFalse(private.intersection(report))

    async def test_resolution_requires_body_and_confirmation(self):
        report = await self.create()
        status, _, _ = await self.request('PATCH', f"/api/items/{report['id']}/resolve")
        self.assertEqual(status, 422)
        payload = self.resolution()
        payload['confirmed'] = False
        status, _, _ = await self.request('PATCH', f"/api/items/{report['id']}/resolve", payload)
        self.assertEqual(status, 422)
        self.assertFalse(json.loads(self.data_file.read_text())[0]['is_resolved'])

    async def test_resolution_records_reason_time_and_preserves_history(self):
        report = await self.create()
        path = f"/api/items/{report['id']}/resolve"
        status, resolved, _ = await self.request('PATCH', path, self.resolution())
        self.assertEqual(status, 200)
        self.assertTrue(resolved['is_resolved'])
        self.assertEqual(resolved.get('resolution_reason'), 'RETURNED')
        self.assertIsNotNone(datetime.fromisoformat(resolved['resolved_at']).tzinfo)
        self.assertNotIn('pin_hash', resolved)
        first_state = self.data_file.read_text()
        status, _, _ = await self.request('PATCH', path, self.resolution('CANCELLED'))
        self.assertEqual(status, 409)
        self.assertEqual(self.data_file.read_text(), first_state)

    async def test_supported_reasons_remain_distinct(self):
        for reason in ['RETURNED', 'FOUND_SELF', 'CANCELLED']:
            report = await self.create()
            status, result, _ = await self.request('PATCH', f"/api/items/{report['id']}/resolve", self.resolution(reason))
            self.assertEqual(status, 200)
            self.assertEqual(result.get('resolution_reason'), reason)

    async def test_invalid_reason_or_found_self_for_found_report_is_rejected(self):
        report = await self.create('FOUND')
        for reason in ['ANYTHING', 'FOUND_SELF']:
            status, _, _ = await self.request('PATCH', f"/api/items/{report['id']}/resolve", self.resolution(reason))
            self.assertEqual(status, 422)
        self.assertFalse(json.loads(self.data_file.read_text())[0]['is_resolved'])


    async def test_legacy_cli_reports_keep_identity_and_can_be_closed(self):
        legacy = {'item_id': 'legacy-123', 'title': 'Kunci', 'report_type': 'LOST',
                  'category': 'Lainnya', 'location': 'Kantin', 'description': 'Kunci kecil',
                  'contact': 'kontak-uji', 'status': 'OPEN', 'created_at': '2026-11-18 12:00'}
        self.data_file.write_text(json.dumps([legacy]))
        status, reports, _ = await self.request('GET', '/api/items')
        self.assertEqual(status, 200)
        self.assertEqual(reports[0].get('id'), 'legacy-123')
        self.assertFalse(reports[0]['is_resolved'])
        status, _, _ = await self.request('PATCH', '/api/items/legacy-123/resolve', self.resolution())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(self.data_file.read_text())[0]['status'], 'RESOLVED')


    async def test_satpam_handoff_keeps_report_active_and_matchable(self):
        lost = await self.create()
        found = await self.create('FOUND')
        self.assertNotIn('management_pin', found)
        path = f"/api/items/{found['id']}/custody"
        status, _, _ = await self.request('PATCH', path, {'location': '   ', 'confirmed': True})
        self.assertEqual(status, 422)
        payload = {'location': 'Pos Satpam Gerbang Utama', 'confirmed': True}
        status, _, _ = await self.request('PATCH', path, {**payload, 'confirmed': False})
        self.assertEqual(status, 422)
        status, deposited, _ = await self.request('PATCH', path, payload)
        self.assertEqual(status, 200)
        self.assertEqual(deposited['custody_location'], payload['location'])
        self.assertFalse(deposited['is_resolved'])
        self.assertIsNotNone(datetime.fromisoformat(deposited['custody_at']).tzinfo)
        _, matches, _ = await self.request('GET', f"/api/items/{lost['id']}/matches")
        self.assertEqual(matches[0]['custody_location'], payload['location'])
        _, repeated, _ = await self.request('PATCH', path, payload)
        self.assertEqual(repeated['custody_at'], deposited['custody_at'])
        status, closed, _ = await self.request('PATCH', f"/api/items/{found['id']}/resolve", self.resolution())
        self.assertEqual(status, 200)
        self.assertTrue(closed['is_resolved'])
        status, _, _ = await self.request('PATCH', path, payload)
        self.assertEqual(status, 409)

    async def test_legacy_resolved_status_is_preserved(self):
        self.data_file.write_text(json.dumps([{'item_id': 'old', 'status': 'RESOLVED', 'title': 'Kunci'}]))
        status, reports, _ = await self.request('GET', '/api/items')
        self.assertEqual(status, 200)
        self.assertTrue(reports[0].get('is_resolved'))
        self.assertIsNone(reports[0].get('resolution_reason'))

    async def test_missing_report_returns_404(self):
        status, _, _ = await self.request('PATCH', '/api/items/missing/resolve', self.resolution())
        self.assertEqual(status, 404)

    async def test_invalid_creation_is_rejected_without_writing_data(self):
        status, _, _ = await self.request('POST', '/api/items', {
            'report_type': 'INVALID', 'title': '   ', 'category': 'Lainnya',
            'location': 'Kantin', 'description': 'Barang', 'contact': 'kontak',
        })
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(self.data_file.read_text()), [])


if __name__ == '__main__':
    unittest.main()
