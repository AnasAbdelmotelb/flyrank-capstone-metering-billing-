"""Locally re-sign a genuine test event for reproducible localhost replay."""
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request

from app.payments import StripeGateway


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith('evt_'):
        raise SystemExit('Usage: python -m scripts.replay_stripe evt_EVENT_ID')
    gateway = StripeGateway()
    if not gateway.secret.startswith('whsec_'):
        raise SystemExit('Configure STRIPE_WEBHOOK_SECRET locally first')
    event = gateway.client().v1.events.retrieve(sys.argv[1]).to_dict()
    if event.get('livemode') is not False:
        raise SystemExit('Only test events can be replayed')
    body = json.dumps(event).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(gateway.secret.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request('http://127.0.0.1:8000/webhooks/stripe', data=body,
        headers={'Content-Type': 'application/json', 'Stripe-Signature': f't={stamp},v1={signature}'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            print(response.status, response.read().decode())
    except urllib.error.HTTPError as exc:
        print(exc.code, exc.read().decode())
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
