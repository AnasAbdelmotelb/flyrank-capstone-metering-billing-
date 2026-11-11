"""Check candidate repository files and history filenames without printing secrets."""
import re
import subprocess
from pathlib import Path


def main():
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
    history = subprocess.check_output(['git', 'log', '--all', '--format=', '--name-only']).decode().splitlines()
    key_pattern = re.compile(rb'(?:sk|rk)_(?:test|live)_[A-Za-z0-9]{24,}|whsec_[A-Za-z0-9]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
    problems = []
    for name in set(names + history):
        if not name:
            continue
        path = Path(name)
        if (path.name.startswith('.env') and path.name != '.env.example') or re.search(r'\.(?:db|sqlite|sqlite3)(?:-|$)', name):
            problems.append(f'Private file tracked or in history: {name}')
        if path.is_file() and key_pattern.search(path.read_bytes()):
            problems.append(f'Possible credential in candidate file: {name}')
    if problems:
        raise SystemExit('\n'.join(problems))
    print('Repository check passed: env/database files excluded; no matching Stripe/private-key credentials in candidate files.')
    print('This pattern check is a safeguard, not proof that every possible secret format is absent.')


if __name__ == '__main__':
    main()
