"""Run after starting the server in a separate normal terminal."""
import argparse
import json
import urllib.request


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--ai',action='store_true',help='Also exercise the configured OpenRouter model')
    args=parser.parse_args()
    base=args.url.rstrip('/')
    for path in ('/','/app.js','/history.js','/style.css','/healthz','/api/status','/api/search?city=Jeddah&purpose=sale&property_type=apartment&currency=SAR&price_max=900000'):
        with urllib.request.urlopen(base+path,timeout=10) as response:
            assert response.status==200
            print('OK',path)
    payload=json.dumps({'message':'Tell me about AIDA and its golf amenities','use_ai':args.ai}).encode()
    req=urllib.request.Request(base+'/api/chat',data=payload,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=150) as response:
        data=json.load(response)
    assert data.get('answer') and data.get('sources'),data
    print('Chat mode:',data['mode'])
    print('Sources:',len(data['sources']))
    if args.ai:
        assert data['mode']=='ai',data.get('notice','AI response not received')
        print('OpenRouter answer verified.')
    print('Smoke test passed.')


if __name__=='__main__':main()
