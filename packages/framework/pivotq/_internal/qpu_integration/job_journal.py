"""Opt-in durable device-job journal. Never infer that an uncertain POST failed."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from functools import lru_cache
from uuid import uuid4


@lru_cache(maxsize=1)
def clock_domain():
    try:
        return 'linux-boot:' + Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return 'process:' + uuid4().hex


def clock_snapshot():
    return {'unix_seconds': time.time(), 'monotonic_seconds': time.monotonic(), 'domain': clock_domain()}


def clock_elapsed(start, end):
    if not start or not end or start['domain'] != end['domain']:
        return None
    duration = end['monotonic_seconds'] - start['monotonic_seconds']
    return duration if duration >= 0 else None


def atomic_write(path, writer, *, binary=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb' if binary else 'w', **({} if binary else {'encoding': 'utf-8'})) as handle:
            writer(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    atomic_write(path, lambda handle: json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False))


class JobJournalError(RuntimeError):
    pass


class JobJournal:
    """Caller must serialize access to the directory (the training run holds a lock)."""

    def __init__(self, directory):
        self.directory = Path(directory)
        if not self.directory.is_absolute():
            raise ValueError('QPU journal directory must be absolute')
        self.directory.mkdir(parents=True, exist_ok=True)

    def prepare(self, request_id, *, server_url, shots, circuits):
        key = hashlib.sha256(request_id.encode()).hexdigest()
        path = self.directory / f'{key}.json'
        request = {
            'request_id': request_id, 'server_url': server_url,
            'parameters': {'reps': shots, 'measure_base': 'Z'},
            'probability_source': 'expr_prob',
            'circuits': [{'circuit_id': c.circuit_id, 'filename': c.filename,
                          'measurement_basis': c.measurement_basis,
                          'sha256': hashlib.sha256(c.content.encode()).hexdigest(),
                          'qasm': c.content} for c in circuits],
        }
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
            if record['request'] != request:
                raise JobJournalError(f'Journal request changed; refusing reuse: {path}')
            response = record.get('response')
            if not isinstance(response, dict) or type(response.get('job_id')) not in (str, int) or not str(response['job_id']).strip():
                raise JobJournalError(f'Uncertain QPU submission; reconcile the device job before resuming: {path}')
            timing = record.setdefault('client_timing', {})
            counter = 'cached_result_reuses' if response.get('status') == 'succeeded' else 'pending_job_resumes'
            timing[counter] = timing.get(counter, 0) + 1
            write_json(path, record)
            return path, record, response
        record = {'version': 1, 'request': request, 'state': 'submit_intent', 'response': None}
        write_json(path, record)  # Must reach disk BEFORE POST.
        return path, record, None

    def receive(self, path, record, response):
        previous = record.get('response')
        # A malformed response must not destroy a previously known job ID.
        if isinstance(previous, dict) and previous.get('job_id') is not None and (
            not isinstance(response, dict) or response.get('job_id') != previous['job_id']
        ):
            record['invalid_response'] = response
            write_json(path, record)
            raise JobJournalError(f'Device job_id mismatch; last valid response retained: {path}')
        record['response'] = response
        record['state'] = response.get('status', 'unknown') if isinstance(response, dict) else 'unknown'
        timing = record.setdefault('client_timing', {})
        if record['state'] in {'succeeded', 'failed', 'interrupted'} and 'terminal_response_clock' not in timing:
            timing['terminal_response_clock'] = timing.get('last_http_response_clock', clock_snapshot())
            timing['submit_to_terminal_seconds'] = clock_elapsed(
                timing.get('submission_attempt_clock'), timing['terminal_response_clock'])
        write_json(path, record)

    def call_http(self, path, record, kind, call):
        """Time real HTTP only when journaling is enabled; cache reads never call this."""
        timing = record.setdefault('client_timing', {})
        if kind == 'submit':
            timing.setdefault('submission_attempt_clock', clock_snapshot())
            timing['submit_attempts'] = timing.get('submit_attempts', 0) + 1
            write_json(path, record)
        started = time.perf_counter()
        try:
            response = call()
        except BaseException:
            timing[kind + '_http_seconds'] = timing.get(kind + '_http_seconds', 0.0) + time.perf_counter() - started
            timing[kind + '_http_failures'] = timing.get(kind + '_http_failures', 0) + 1
            write_json(path, record)
            raise
        timing[kind + '_http_seconds'] = timing.get(kind + '_http_seconds', 0.0) + time.perf_counter() - started
        timing[kind + '_http_responses'] = timing.get(kind + '_http_responses', 0) + 1
        timing['last_http_response_clock'] = clock_snapshot()
        # read_http_response persists both the HTTP timing and raw JSON together.
        return response

    def read_http_response(self, path, record, response):
        """Archive malformed/error HTTP bodies without losing a known job ID."""
        if response.is_error:
            record['last_http_error'] = {'status_code': response.status_code, 'body': response.text}
            write_json(path, record)
            response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            record['last_http_error'] = {'status_code': response.status_code, 'body': response.text}
            write_json(path, record)
            raise
        self.receive(path, record, result)
        return result
