# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Housekeeping single-flight: with gunicorn --workers N every worker starts its
# own housekeeping thread on its first request, and without coordination N
# threads run the billing claim, the outbox drain and the cap resync at the
# same minute on one SQLite file. The losers pile onto the write lock
# (busy_timeout) while draft and map reads queue behind them — the whole site
# stalls for seconds on every tick. This lock lets exactly one worker run the
# tick while the rest skip it.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _housekeeping_lock_path():
    """Lock file next to this process's database.

    Staging and production share one host account with different DB files, so
    keying the lock off DB_PATH keeps their ticks independent of each other.
    """
    try:
        db_path = str(db.DB_PATH or '')
    except Exception:
        db_path = ''
    if db_path and '://' not in db_path and not db_path.startswith((':', 'file:')):
        return db_path + '.housekeeping.lock'
    import tempfile as _tempfile
    return os.path.join(_tempfile.gettempdir(), 'landloom-housekeeping.lock')


def _housekeeping_tick_interval_seconds():
    """Same floor as the loop itself so the stale-lock window always matches."""
    return max(60, int(os.environ.get('HOUSEKEEPING_INTERVAL_SECONDS') or 300))


def _housekeeping_tick_singleflight():
    """Yield True for the one worker that may run this tick, False for the rest.

    The claim uses O_EXCL so two workers racing the same tick cannot both win.
    A lock older than two intervals is a crashed worker's leftover and is
    reclaimed. Never raises: when the lock cannot be used the tick runs, which
    is exactly today's behavior.
    """
    import contextlib as _contextlib

    @_contextlib.contextmanager
    def _guard():
        lock_path = _housekeeping_lock_path()
        interval = _housekeeping_tick_interval_seconds()
        try:
            age = time.time() - os.stat(lock_path).st_mtime
        except OSError:
            pass
        else:
            if age > 2 * interval:
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            yield False
            return
        except OSError:
            yield True
            return
        try:
            with os.fdopen(fd, 'w') as handle:
                handle.write(str(os.getpid()))
            yield True
        finally:
            try:
                os.unlink(lock_path)
            except OSError:
                pass

    return _guard()
