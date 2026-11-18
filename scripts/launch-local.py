"""Start a Windows dev service without inheriting console handles."""
import os
import subprocess
import sys

cwd, out, err, *command = sys.argv[1:]
with open(out, 'wb') as output, open(err, 'wb') as errors:
    child = subprocess.Popen(command, cwd=cwd, env=dict(os.environ), stdin=subprocess.DEVNULL,
                             stdout=output, stderr=errors, creationflags=subprocess.CREATE_NO_WINDOW)
print(child.pid)
