"""The process installs the operating system's trust store before anything
binds ssl.SSLContext, so the AWS clients can open a TLS context.

Each case runs in a fresh interpreter: this test process has long since
imported urllib3, which is the order that used to break."""

import subprocess
import sys


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)


def test_the_entry_point_lets_botocore_open_a_tls_context() -> None:
    result = _run(
        "import tadas.workers.maintenance.main\n"
        "from botocore.httpsession import create_urllib3_context\n"
        "from tadas.infra.trust import install_trust_store\n"
        "install_trust_store()  # what boot does, after everything is imported\n"
        "create_urllib3_context()\n"
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_the_order_the_entry_point_guards_against_does_break() -> None:
    # The negative control: bind the old class first, then inject. If this
    # stopped failing, the test above would prove nothing.
    result = _run(
        "from botocore.httpsession import create_urllib3_context\n"
        "from tadas.infra.trust import install_trust_store\n"
        "install_trust_store()\n"
        "create_urllib3_context()\n"
    )
    assert result.returncode != 0
    assert "RecursionError" in result.stderr
