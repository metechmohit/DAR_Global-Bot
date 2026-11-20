import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.common import normalize, number, write_csv, read_csv, canonical_url
from app.extract import extract
from app.search import parse_question, search_records, retrieve, validate_filters, get_records
from app.chat import answer
from app.openrouter import completion, ModelError
from app.htmltools import parse_html
from app.crawl import allowed, useful
from app.config import DB


class ExtractionTests(unittest.TestCase):
    def test_setup_enables_model_without_touching_key(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('atlas_setup',Path(__file__).resolve().parents[1]/'scripts/setup_local.py')
        setup=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'.env').write_text('OPENROUTER_API_KEY=test-secret-value\nSEMANTIC_MODEL=\nPORT=8001\n')
            with patch.object(setup,'ROOT',root):setup.enable_semantic('intfloat/multilingual-e5-small')
            contents=(root/'.env').read_text()
            self.assertIn('OPENROUTER_API_KEY=test-secret-value',contents)
            self.assertIn('SEMANTIC_MODEL=intfloat/multilingual-e5-small',contents)
            self.assertIn('PORT=8001',contents)

    def test_rental_period_is_not_millions(self):
        self.assertEqual(number('2,500 monthly'), 2500)
        self.assertEqual(number('42,000 monthly'), 42000)
        self.assertEqual(number('1.24M'), 1240000)
        self.assertEqual(number('900K'), 900000)
        self.assertEqual(number('٢٥٠٠'), 2500)

    def test_price_parser_skips_room_counts(self):
        page = {'url':'https://wasalt.sa/en/property/sale/villa-123456', 'title':'Villa with 7 Bedrooms For Sale', 'status':'ok','method':'plain_text','content':'Villa with 7 Bedrooms\n7\n\nbedrooms\n6\n\nbathrooms\n210 SQM\nland area\n1,900,000\nProperty usage Residential\nRef no. 187313\nLast updated: 1 days ago\n'+'Public property description. '*5}
        r=extract(page)
        self.assertEqual(r['price'],1900000)
        self.assertEqual(r['bedrooms'],7)
        self.assertEqual(r['reference'],'187313')
        self.assertEqual(r['url_identifier'],'123456')
        self.assertEqual(r['property_type'],'villa')

    def test_summary_marks_its_limitations(self):
        page={'url':'https://wasalt.sa/en/property/rent/apartment-12345','title':'Apartment with 3 Bedrooms','status':'ok','method':'web_index_summary','content':'L0: 2,500 monthly Apartment with 3 Bedrooms\nL1: ###### Al Malqa, Riyadh\nL2: '+('Actual search card text. '*5)}
        r=extract(page)
        self.assertEqual(r['price'],2500)
        self.assertEqual(r['price_period'],'monthly')
        self.assertIn('summary_only',r['quality_flags'])

    def test_csv_roundtrip_unicode_multiline(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.csv'
            row={'title':'فيلا، الرياض','description':'A "quote", comma\nand another line'}
            write_csv(p,[row],list(row))
            self.assertEqual(read_csv(p),[row])

    def test_arabic_normalization(self):
        self.assertEqual(normalize('الرِّيَاض ١٢٣'),normalize('الرياض 123'))

    def test_empty_shell_not_a_property(self):
        self.assertIsNone(extract({'url':'https://darglobal.co.uk/missing','title':'Project','content':'L0: iframe\nL1: Image: ads','status':'ok','method':'web_retrieval'}))

    def test_html_script_is_data_not_text(self):
        p=parse_html('<title>Villa</title><h1>A home</h1><script>alert(1)</script><p>210 sqm</p><a href="/project/test">Test</a>','https://wasalt.sa/en')
        self.assertNotIn('alert',p.text)
        self.assertIn('210 sqm',p.text)
        self.assertEqual(p.links[0][0],'https://wasalt.sa/project/test')

    def test_url_scope(self):
        self.assertTrue(allowed('https://wasalt.sa/en'))
        self.assertFalse(allowed('https://wasalt.sa.evil.example/en'))
        self.assertFalse(allowed('http://127.0.0.1/'))
        self.assertFalse(allowed('https://user:secret@wasalt.sa/en'))
        self.assertFalse(useful('https://wasalt.sa/en/checkout'))
        self.assertEqual(canonical_url('https://www.wasalt.sa/en/?utm_source=x&page=2#x'),'https://wasalt.sa/en?page=2')


class QueryTests(unittest.TestCase):
    def test_budget_and_bedrooms(self):
        p=parse_question('Find 3-bedroom apartments for sale in Riyadh under SAR 1.5 million')
        self.assertEqual(p['filters']['price_max'],1500000)
        self.assertEqual(p['filters']['bedrooms'],3)
        self.assertEqual(p['filters']['city'],'Riyadh')
        self.assertFalse(p['clarification'])

    def test_rent_period_clarification(self):
        self.assertTrue(parse_question('Find apartments for rent in Jeddah under SAR 5000')['clarification'])
        p=parse_question('Find apartments for rent in Jeddah under SAR 5000 monthly')
        self.assertFalse(p['clarification'])
        self.assertEqual(p['filters']['price_max'],5000)
        self.assertEqual(p['filters']['price_period'],'monthly')

    def test_no_mixed_currency_sort(self):
        self.assertTrue(parse_question('Show the cheapest properties')['clarification'])
        with self.assertRaises(ValueError):search_records({'sort':'price_asc'})

    def test_amenity_constraint_is_not_ignored(self):
        p=parse_question('Show DarGlobal projects with a pool')
        self.assertEqual(p['filters']['amenities'],'pool')
        result=search_records(p['filters'])
        self.assertTrue(all('pool' in r['amenities'] for r in result['records']))

    def test_followup_and_reset(self):
        p=parse_question('Make it 4 bedrooms instead',{'city':'Riyadh','bedrooms':3,'price_max':1500000,'currency':'SAR'})
        self.assertEqual(p['filters']['bedrooms'],4)
        self.assertEqual(p['filters']['city'],'Riyadh')
        self.assertEqual(parse_question('clear filters',p['filters'])['filters'],{})

    def test_area_is_not_budget(self):
        p=parse_question('Find villas in Riyadh above 250 sqm')
        self.assertNotIn('price_min',p['filters'])
        self.assertEqual(p['filters']['area_min'],250)

    def test_filters_validate_untrusted_values(self):
        f=validate_filters({'source':'evil','price_max':float('nan'),'city':"x' OR 1=1 --",'arbitrary':'bad','bedrooms':-1})
        self.assertNotIn('source',f)
        self.assertNotIn('price_max',f)
        self.assertNotIn('bedrooms',f)
        self.assertNotIn('arbitrary',f)


@unittest.skipUnless(DB.exists(),'Run python3 -m app ingest first')
class CorpusTests(unittest.TestCase):
    def test_greeting_and_coverage_without_model_calls(self):
        with patch('app.openrouter.completion',side_effect=AssertionError('No model needed')):
            self.assertIn('Atlas',answer('hello')['answer'])
            self.assertIn('searchable records',answer('What is the data coverage?')['answer'])

    def test_real_filtered_results(self):
        f={'source':'wasalt','city':'Jeddah','property_type':'apartment','purpose':'sale','currency':'SAR','price_max':900000}
        result=search_records(f)
        self.assertGreater(result['total'],0)
        for r in result['records']:
            self.assertEqual(r['city'],'Jeddah')
            self.assertLessEqual(float(r['price']),900000)
            self.assertEqual(r['currency'],'SAR')
            self.assertIn('apartment',r['property_type'])

    def test_unknown_bedrooms_excluded(self):
        result=search_records({'bedrooms':3},50)
        self.assertTrue(all(r['bedrooms'] and float(r['bedrooms'])==3 for r in result['records']))

    def test_sql_injection_is_literal(self):
        result=search_records({'city':"x' OR 1=1 --"})
        self.assertEqual(result['total'],0)

    def test_knowledge_evidence(self):
        evidence=retrieve('AIDA Oman golf amenities',source='darglobal')
        self.assertTrue(evidence)
        self.assertTrue(all(e['url'].startswith('https://darglobal.co.uk/') for e in evidence))

    def test_arabic_question_has_sources(self):
        result=answer('ما هي مشاريع دار جلوبال في مسقط؟',use_ai=False)
        self.assertTrue(result['sources'])
        self.assertTrue(all(r['city']=='Muscat' for r in result['records']))

    def test_impossible_filter_does_not_relax(self):
        result=answer('Show 49 bedroom apartments for sale in Jeddah under SAR 10',use_ai=False)
        self.assertEqual(result['records'],[])
        self.assertIn('No matching properties',result['answer'])

    def test_compare_exact_records(self):
        records=search_records({'source':'darglobal','kind':'project'},2)['records']
        result=answer('Compare these properties',compare_ids=[r['id'] for r in records],use_ai=False)
        self.assertEqual({r['id'] for r in result['records']},{r['id'] for r in records})
        self.assertEqual(result['intent'],'compare')

    def test_paid_models_rejected_before_network(self):
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'test-not-real','OPENROUTER_MODEL':'paid/model'}):
            with self.assertRaises(ModelError):completion([{'role':'user','content':'Hi'}])

    def test_model_failure_keeps_grounded_results(self):
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'test-not-real'}), patch('app.openrouter.completion',side_effect=ModelError('Provider temporarily unavailable')):
            result=answer('Show apartments for sale in Jeddah under SAR 900000')
        self.assertEqual(result['mode'],'retrieval')
        self.assertTrue(result['records'])
        self.assertIn('Provider temporarily unavailable',result['notice'])

    def test_ai_planning_and_citation_validation(self):
        replies=[('{"intent":"search","filters":{"source":"wasalt","city":"Jeddah","purpose":"sale","property_type":"apartment","currency":"SAR","price_max":900000},"clarification":""}','test/free'),('Here are collected matches [S1]. Invalid citation [S999].','test/free')]
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'test-not-real'}),patch('app.openrouter.completion',side_effect=replies):
            result=answer('Find Jeddah apartments below SAR 900000')
        self.assertEqual(result['mode'],'ai')
        self.assertTrue(result['records'])
        self.assertNotIn('[S999]',result['answer'])



@unittest.skipUnless(DB.exists(),'Run python3 -m app ingest first')
class HTTPTests(unittest.TestCase):
    def request(self,method,path,body=None,origin=None):
        from app.server import application
        from urllib.parse import urlsplit
        from wsgiref.util import setup_testing_defaults
        from wsgiref.validate import validator
        payload=json.dumps(body).encode() if body is not None else b''
        env={};setup_testing_defaults(env)
        parsed=urlsplit(path)
        env.update(REQUEST_METHOD=method,PATH_INFO=parsed.path,QUERY_STRING=parsed.query,
                   HTTP_HOST='localhost:8000',CONTENT_TYPE='application/json',
                   CONTENT_LENGTH=str(len(payload)),REMOTE_ADDR='127.0.0.1')
        env['wsgi.input']=io.BytesIO(payload)
        if origin:env['HTTP_ORIGIN']=origin
        captured={}
        def start_response(status,headers,exc_info=None):captured.update(status=status,headers=headers)
        result=validator(application)(env,start_response)
        try:data=b''.join(result)
        finally:result.close()
        headers='\r\n'.join(k+': '+v for k,v in captured['headers']).encode()
        return int(captured['status'].split()[0]),data,headers

    def test_health_and_head(self):
        code,data,_=self.request('GET','/healthz')
        self.assertEqual(code,200)
        self.assertEqual(json.loads(data),{'status':'ok'})
        code,data,_=self.request('HEAD','/')
        self.assertEqual(code,200)
        self.assertEqual(data,b'')

    def test_production_requires_runtime_key(self):
        from app.server import serve
        with patch.dict(os.environ,{'REQUIRE_API_KEY':'1','OPENROUTER_API_KEY':''}):
            with self.assertRaises(SystemExit):serve(production=True)

    def test_status_does_not_expose_key(self):
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'secret-value-test'}):
            code,data,_=self.request('GET','/api/status')
            self.assertEqual(code,200)
            self.assertNotIn(b'secret-value-test',data)
            self.assertNotIn('ai_configured',json.loads(data))
            self.assertNotIn('model',json.loads(data))

    def test_ui_and_assets(self):
        for path in ('/','/app.js','/history.js','/style.css','/favicon.svg'):
            code,data,_=self.request('GET',path)
            self.assertEqual(code,200)
            self.assertTrue(data)

    def test_chat_without_model(self):
        code,data,_=self.request('POST','/api/chat',{'message':'Tell me about AIDA golf amenities','use_ai':False})
        self.assertEqual(code,200)
        self.assertTrue(json.loads(data)['sources'])

    def test_cross_origin_rejected(self):
        code,_,_=self.request('POST','/api/chat',{'message':'Hi'},origin='https://evil.example')
        self.assertEqual(code,403)

    def test_invalid_request(self):
        code,_,_=self.request('POST','/api/chat',{'message': ['wrong type']})
        self.assertEqual(code,400)

    def test_export_and_traversal(self):
        code,_,_=self.request('GET','/api/export/records.csv')
        self.assertEqual(code,404)
        with patch.dict(os.environ,{'ATLAS_DEV_TOOLS':'1'}):
            code,data,headers=self.request('GET','/api/export/records.csv')
        self.assertEqual(code,200)
        self.assertIn(b'text/csv',headers)
        self.assertIn(b'url',data)
        code,_,_=self.request('GET','/../../.env')
        self.assertEqual(code,404)


if __name__=='__main__':unittest.main()
