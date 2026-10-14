"""Slowing down and stopping password guessing.

Failed attempts are counted in the master database (the business is not known yet when someone types a login) under
keyed hashes, so no email, phone or address is stored in the clear. Three counters apply to a sign-in:

- one login from one address (a person mistyping, or someone guessing at that account from one machine): strict;
- one login from anywhere (guessing spread over many addresses): looser, so an attacker cannot lock a real person
  out from a single address, but cannot try forever either;
- one address for any login (guessing many accounts): loosest.

When a counter reaches its limit inside the window the key is locked for a while and `guard` refuses with 429 and
how long to wait. A good sign-in clears the login counters (not the address one). The same mechanism protects
password reset requests and second-factor codes.
"""

import hashlib
import hmac
from dataclasses import dataclass

from sqlalchemy import text

from ziira.kernel import directory
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import TooManyRequests


@dataclass(frozen=True)
class Counter:
    """One thing being counted: its key, and how many failures within the window lock it."""

    key: str
    max_failures: int


def _hash(kind: str, value: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def sign_in_counters(login: str, ip_address: str | None) -> list[Counter]:
    """The counters for a sign-in with this login from this address."""
    s = get_settings()
    out = [Counter("login:" + directory.hash_login(login), s.throttle_login_failures)]
    if ip_address:
        out.append(Counter("pair:" + _hash("pair", f"{directory.hash_login(login)}|{ip_address}"),
                           s.throttle_login_ip_failures))
        out.append(Counter("ip:" + _hash("ip", ip_address), s.throttle_ip_failures))
    return out


def action_counters(action: str, subject: str, ip_address: str | None, per_subject: int = 5,
                    per_ip: int = 30) -> list[Counter]:
    """Counters for another guessable action (a second-factor code, a password reset request) by subject and address."""
    out = [Counter(f"{action}:" + _hash(action, subject), per_subject)]
    if ip_address:
        out.append(Counter(f"{action}-ip:" + _hash(action + "-ip", ip_address), per_ip))
    return out


def guard(counters: list[Counter]) -> None:
    """Refuse (429, with how many seconds to wait) if any of the counters is locked."""
    if not counters:
        return
    with master_session() as s:
        wait = s.execute(text(
            "select coalesce(max(extract(epoch from locked_until - now())), 0) from master.auth_throttle "
            "where key = any(:k) and locked_until > now()"), {"k": [c.key for c in counters]}).scalar_one()
    if wait and wait > 0:
        seconds = int(wait) + 1
        raise TooManyRequests("Too many attempts. Wait a few minutes and try again.", {"retry_after": seconds})


def failed(counters: list[Counter]) -> None:
    """Count one failure on each counter, locking those that reach their limit."""
    settings = get_settings()
    window, lock = settings.throttle_window_minutes * 60, settings.throttle_lock_minutes * 60
    with master_session() as s:
        for c in counters:
            s.execute(text(
                "insert into master.auth_throttle (key, failures, window_started, updated_at) "
                "values (:k, 1, now(), now()) "
                "on conflict (key) do update set "
                "failures = case when master.auth_throttle.window_started < now() - make_interval(secs => :w) "
                "                then 1 else master.auth_throttle.failures + 1 end, "
                "window_started = case when master.auth_throttle.window_started < now() - make_interval(secs => :w) "
                "                      then now() else master.auth_throttle.window_started end, "
                "locked_until = case when (case when master.auth_throttle.window_started < now() - "
                "                                make_interval(secs => :w) then 1 "
                "                                else master.auth_throttle.failures + 1 end) >= :m "
                "                    then now() + make_interval(secs => :l) "
                "                    else master.auth_throttle.locked_until end, updated_at = now()"),
                {"k": c.key, "w": window, "m": c.max_failures, "l": lock})


def succeeded(counters: list[Counter]) -> None:
    """A good attempt clears the counters given (pass the login ones, not the address one)."""
    if not counters:
        return
    with master_session() as s:
        s.execute(text("delete from master.auth_throttle where key = any(:k)"), {"k": [c.key for c in counters]})


def purge(days: int = 2) -> int:
    """Forget counters that have not been touched for a while (the worker calls this)."""
    with master_session() as s:
        return len(s.execute(text(
            "delete from master.auth_throttle where updated_at < now() - make_interval(days => :d) "
            "and (locked_until is null or locked_until < now()) returning key"), {"d": days}).all())
