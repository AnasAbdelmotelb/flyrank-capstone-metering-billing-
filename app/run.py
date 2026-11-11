"""One local command for the HTTP server and durable worker."""
import subprocess
import sys

import uvicorn


def main():
    worker = subprocess.Popen([sys.executable, '-m', 'app.worker'])
    try:
        uvicorn.run('app.main:app', host='127.0.0.1', port=8000)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()


if __name__ == '__main__':
    main()
