"""Submit one real scan to Astra and replace it after the client starts waiting for response headers."""
import json
import os
from pathlib import Path
from threading import Event
from time import perf_counter_ns

import httpx2
from openai import OpenAI

from case_revision import Experiment, PLAN, REVISED, SCAN, check_ready, current, require, temporary_database, upload, work


def main():
    if (os.getenv('OPENAI_OCR_MODEL') or 'gpt-6.2-astra') != 'gpt-6.2-astra':
        raise SystemExit('Expected gpt-6.2-astra for this fixture benchmark')
    times = {}
    waiting = Event()
    request_count = 0

    def record(name):
        times[name] = perf_counter_ns()

    def instrument(request):
        nonlocal request_count
        require(request.method == 'POST' and request.url.path.endswith('/responses'), 'unexpected HTTP request')
        request_count += 1
        require(request_count == 1, 'benchmark permits one Responses request')
        active_post = False

        def trace(name, info):
            nonlocal active_post
            if name == 'http11.send_request_body.started':
                # A proxy CONNECT handshake can use the same trace extension.
                active_post = info['request'].method == b'POST'
            elif active_post and name == 'http11.send_request_body.complete':
                record('v1_request_body_write_complete')
            elif active_post and name == 'http11.receive_response_headers.started':
                require('v1_request_body_write_complete' in times, 'header read before completed body write')
                record('v1_response_header_read_started')
                waiting.set()
            elif active_post and name == 'http11.receive_response_headers.complete':
                record('v1_response_headers_received')

        request.extensions['trace'] = trace

    with temporary_database() as dsn:
        exp = Experiment(dsn)
        try:
            exp.db.execute(Path(__file__).with_name('case_revision.sql').read_text())
            exp.new('overlap')
            transport = httpx2.Client(http1=True, http2=False, event_hooks={'request': [instrument]})
            with OpenAI(http_client=transport, max_retries=0, timeout=45) as client:
                upload(exp.db, 'overlap', 'first', 0, PLAN, SCAN)

                def old_worker(db):
                    result, _ = work(db, 'overlap', 1, client=client)
                    record('v1_worker_returned_after_db_commit')
                    return result

                old = exp.thread(old_worker)
                if not waiting.wait(15):
                    if old.done():
                        old.result()
                    raise RuntimeError('No completed POST-body write and response-header wait were observed')
                record('v2_upload_started')
                upload(exp.db, 'overlap', 'replacement', 1, PLAN, REVISED)
                record('v2_upload_committed')
                on_upload = current(exp.db, 'overlap')
                require(on_upload == (2, 'queued', None), 'replacement did not clear the active decision')
                action, cached = work(exp.db, 'overlap', 2)
                record('v2_result_committed')
                require(action == 'current' and cached, 'revision 2 failed or did not reuse unchanged plan')
                check_ready(exp.db, 'overlap', 2)
                old_action = old.result()
                check_ready(exp.db, 'overlap', 2)
                history = exp.db.execute(
                    "SELECT result FROM revisions WHERE case_id='overlap' AND rev=1").fetchone()[0]
                require(history['estimate'] == SCAN and history['extraction'] == 'ocr' and
                        history['outcome'] == 'missing_evidence' and history['total'] == 82000 and
                        history['itemized'] is False, 'late scan returned unexpected evidence')
                require(request_count == 1 and 'v1_response_headers_received' in times, 'missing response trace')
                origin = times['v1_request_body_write_complete']
                result = {
                    'http_requests': request_count,
                    'ms_since_v1_post_body_written': {
                        k: round((v - origin)/1_000_000, 3) for k, v in sorted(times.items(), key=lambda t: t[1])
                    },
                    'v2_upload_committed_before_response_headers':
                        times['v2_upload_committed'] < times['v1_response_headers_received'],
                    'v2_result_committed_before_response_headers':
                        times['v2_result_committed'] < times['v1_response_headers_received'],
                    'current_revision_on_upload': on_upload,
                    'current_revision_after_late_worker': current(exp.db, 'overlap')[:2],
                    'current_outcome_after_late_worker': current(exp.db, 'overlap')[2]['outcome'],
                    'old_worker_disposition': old_action,
                    'original_outcome': history['outcome'],
                }
                print(json.dumps(result, indent=2))
        finally:
            exp.close()


if __name__ == '__main__':
    main()
