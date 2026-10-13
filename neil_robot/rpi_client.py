"""
Run Python on the Raspberry Pi over one persistent SSH connection.

Nothing needs to be deployed to the Pi: each call sends a script to the Pi's
system ``python3`` (which has buildhat and picamera2 from apt). The script
calls ``emit(obj)`` once with a JSON-serialisable result.

    with RPiClient() as pi:
        pi.run_python("from buildhat import Hat; emit(Hat().get_vin())")
"""
from __future__ import annotations

import json
import shlex
import textwrap
import threading

import paramiko

from neil_robot import config

_MARKER = "__NEIL_RESULT__"

# Prepended to every script. Results are tagged so stray prints from libraries
# (buildhat firmware messages, etc.) can't corrupt the output.
_PRELUDE = f"""\
import json as _json, sys as _sys, traceback as _tb
def emit(obj):
    print({_MARKER!r} + _json.dumps(obj), flush=True)
PARAMS = _json.loads(_sys.argv[1]) if len(_sys.argv) > 1 else {{}}
"""


class RPiError(RuntimeError):
    pass


class RPiClient:
    def __init__(
        self,
        host: str = config.RPI_HOST,
        user: str = config.RPI_USER,
        key_filename: str | None = config.RPI_SSH_KEY,
    ):
        self.host = host
        self.user = user
        self.key_filename = key_filename
        self._ssh: paramiko.SSHClient | None = None
        self._lock = threading.Lock()

    # ── connection ────────────────────────────────────────────────────────────

    def connect(self) -> paramiko.SSHClient:
        transport = self._ssh.get_transport() if self._ssh else None
        if transport is not None and transport.is_active():
            return self._ssh
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                self.host,
                username=self.user,
                key_filename=self.key_filename,
                timeout=config.SSH_CONNECT_TIMEOUT,
                look_for_keys=True,
                allow_agent=True,
            )
        except paramiko.AuthenticationException as exc:
            raise RPiError(
                f"SSH key login to {self.user}@{self.host} failed. "
                "Install your public key on the Pi first (see README)."
            ) from exc
        ssh.get_transport().set_keepalive(15)
        self._ssh = ssh
        return ssh

    def close(self) -> None:
        if self._ssh:
            self._ssh.close()
            self._ssh = None

    def __enter__(self) -> "RPiClient":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── execution ─────────────────────────────────────────────────────────────

    def run_shell(self, command: str, timeout: float = 30) -> tuple[int, str, str]:
        with self._lock:
            ssh = self.connect()
            _, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            return stdout.channel.recv_exit_status(), out, err

    def run_python(self, script: str, params: dict | None = None, timeout: float = 60):
        """Run *script* on the Pi and return the object it passed to emit().

        *params* is available to the script as the dict ``PARAMS``.
        Exceptions on the Pi are re-raised here as RPiError with the remote traceback.
        """
        body = textwrap.indent(textwrap.dedent(script).strip("\n"), "    ")
        full = (
            _PRELUDE
            + "try:\n" + body + "\n"
            + "except BaseException as _e:\n"
            + "    emit({'__error__': repr(_e), '__trace__': _tb.format_exc()})\n"
        )
        arg = shlex.quote(json.dumps(params or {}))
        with self._lock:
            ssh = self.connect()
            stdin, stdout, stderr = ssh.exec_command(f"python3 - {arg}", timeout=timeout)
            stdin.write(full.encode())
            stdin.channel.shutdown_write()
            try:
                out = stdout.read().decode(errors="replace")
            except TimeoutError as exc:
                raise RPiError(f"Pi script timed out after {timeout}s") from exc
            err = stderr.read().decode(errors="replace")

        results = [l[len(_MARKER):] for l in out.splitlines() if l.startswith(_MARKER)]
        if not results:
            raise RPiError(f"Pi script returned no result.\nstdout: {out[-2000:]}\nstderr: {err[-2000:]}")
        result = json.loads(results[-1])
        if isinstance(result, dict) and "__error__" in result:
            raise RPiError(f"Pi script raised {result['__error__']}\n{result['__trace__']}")
        return result


_client: RPiClient | None = None


def get_client() -> RPiClient:
    """Shared client, so repeated calls reuse one SSH connection."""
    global _client
    if _client is None:
        _client = RPiClient()
    return _client
