"""In-process analysis jobs; live work does not survive server restarts."""
import copy
import threading

_lock = threading.Lock()
_jobs = {}


def status(tender_id):
    with _lock:
        return copy.deepcopy(_jobs.get(tender_id, {'status': 'idle', 'percent': 0, 'message': 'Analiza še ni zagnana.'}))


def start(tender_id, worker):
    with _lock:
        existing = _jobs.get(tender_id)
        if existing and existing['status'] == 'running':
            return copy.deepcopy(existing)
        if sum(j['status']=='running' for j in _jobs.values()) >= 2:
            raise ValueError('Že potekata dve analizi. Počakajte, da se zaključita.')
        _jobs[tender_id] = {'status': 'running', 'percent': 0, 'message': 'Pripravljam analizo ...'}

    def progress(percent, message):
        with _lock:
            job = _jobs[tender_id]
            job.update(percent=max(job['percent'], min(99, int(percent))), message=message)

    def run():
        try:
            result = worker(tender_id, progress=progress)
            with _lock:
                _jobs[tender_id].update(status='done', percent=100, message='Analiza zaključena.', result=result)
        except Exception as ex:
            with _lock:
                _jobs[tender_id].update(status='failed', message='Analiza ni uspela.', error=str(ex))

    threading.Thread(target=run, daemon=True).start()
    return status(tender_id)
