import copy
import csv
import io
import json
import math
import unittest
from autotune_core import TuneConfig,observe,parse_decision,model_context,csv_text,Progress


def rows(error=.1):
    return [{'time':i*.01,'target':1.0,'actual':1.0-error,'output':1.0} for i in range(301)]


def decision(parameters=None,action='apply'):
    return json.dumps({'action':action,'parameters':parameters or {'kp':2.1,'ki':1,'kd':.05},'reason':'降低偏差后复测','expected_effect':'比较下一轮误差','uncertainties':[]})


class AutoTuneTests(unittest.TestCase):
    def setUp(self):
        self.config=TuneConfig().validate();self.reference={'kp':2,'ki':1,'kd':.05}

    def test_metrics_have_observable_numeric_meaning(self):
        result=observe(rows(),3,self.config)
        self.assertAlmostEqual(result['metrics']['rms'],.1)
        self.assertAlmostEqual(result['metrics']['bias'],.1)
        self.assertEqual(result['metrics']['ripple'],0)
        self.assertEqual(result['metrics']['saturation'],0)
        self.assertEqual(result['metrics']['output_change'],0)
        self.assertFalse(result['reached'])

    def test_feedback_and_time_are_validated(self):
        for invalid in ['missing','nan','bound','reverse','short','many']:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                r=rows()
                if invalid=='missing':r[5].pop('output')
                elif invalid=='nan':r[5]['actual']=math.nan
                elif invalid=='bound':r[5]['actual']=1000
                elif invalid=='reverse':r[5]['time']=-1
                elif invalid=='short':r=r[:30]
                else:r=r*100
                observe(r,3,self.config)

    def test_target_switch_is_not_mixed_with_constant_test(self):
        r=rows();r[-1]['target']=2
        with self.assertRaises(ValueError):observe(r,3,self.config)

    def test_measured_step_overshoot_and_unsettled_are_explicit(self):
        self.config.step_test=True
        r=rows(0)
        for row in r[:20]:row['target']=0;row['actual']=0
        r[50]['actual']=1.1
        result=observe(r,3,self.config)
        self.assertAlmostEqual(result['metrics']['overshoot'],10)
        self.assertAlmostEqual(result['metrics']['settling'],.31)
        r[-1]['actual']=.8
        self.assertIsNone(observe(r,3,self.config)['metrics']['settling'])

    def test_step_metrics_require_an_actual_step(self):
        self.config.step_test=True
        with self.assertRaises(ValueError):observe(rows(),3,self.config)
        self.config.goals['settling']=3
        self.config.step_test=False
        with self.assertRaises(ValueError):self.config.validate()

    def test_valid_single_adjustment_is_not_clipped(self):
        value=parse_decision(decision(),self.config,self.reference)
        self.assertEqual(value['parameters']['kp'],2.1)

    def test_ranges_nonfinite_types_and_change_magnitude_are_rejected(self):
        for candidate in [{'kp':-1,'ki':1,'kd':.05},{'kp':2.5,'ki':1,'kd':.05},{'kp':True,'ki':1,'kd':.05},{'kp':math.nan,'ki':1,'kd':.05},{'kp':2.1},{'kp':2.1,'ki':1,'kd':.05,'target':1}]:
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):parse_decision(decision(candidate),self.config,self.reference)

    def test_multi_parameter_is_explicitly_opt_in(self):
        text=decision({'kp':2.1,'ki':1.05,'kd':.05})
        with self.assertRaises(ValueError):parse_decision(text,self.config,self.reference)
        self.config.multi_change=True
        self.assertEqual(parse_decision(text,self.config,self.reference)['action'],'apply')

    def test_malformed_duplicate_and_unknown_actions_are_rejected(self):
        for text in ['{}','[]','```json\n{}\n```','{"action":"apply","action":"stop"}',decision(action='execute_command')]:
            with self.subTest(text=text),self.assertRaises(ValueError):parse_decision(text,self.config,self.reference)

    def test_hold_cannot_hide_a_device_write(self):
        with self.assertRaises(ValueError):parse_decision(decision(action='hold'),self.config,self.reference)
        value=json.loads(decision());value['action']='hold';value['parameters']={}
        self.assertEqual(parse_decision(json.dumps(value),self.config,self.reference)['action'],'hold')

    def test_csv_has_full_data_and_actual_parameters(self):
        meta={'round':1,'kp':2,'ki':1,'kd':.05,'source':'simulation','loop':'line','revision':3,'time_basis':'simulated','reference_limit':3}
        out=list(csv.DictReader(io.StringIO(csv_text(rows(),meta))))
        self.assertEqual(len(out),301);self.assertEqual(out[-1]['kp'],'2');self.assertAlmostEqual(float(out[-1]['error']),.1)

    def test_model_csv_is_decimated_but_metrics_and_endpoints_are_full(self):
        r=rows();before=copy.deepcopy(r);meta={'kp':2,'ki':1,'kd':.05};result=observe(r,3,self.config)
        context=model_context(r,meta,result,[{'round':1,'parameters':meta,'observation':result,'curve':r}],self.config)
        sent=list(csv.DictReader(io.StringIO(context['csv_text'])))
        self.assertLessEqual(len(sent),256);self.assertEqual(float(sent[0]['time']),0);self.assertEqual(float(sent[-1]['time']),3)
        self.assertEqual(context['observation']['sample_count'],301);self.assertNotIn('curve',context['history'][0]);self.assertEqual(r,before)

    def test_convergence_requires_repeated_goals(self):
        p=Progress(self.config);item={'parameters':self.reference,'observation':observe(rows(0),3,self.config)}
        self.assertIsNone(p.record(item));self.assertEqual(p.record(item),'连续达到配置目标')

    def test_regression_preserves_best_record(self):
        p=Progress(self.config);p.record({'round':1,'parameters':self.reference,'observation':observe(rows(.1),3,self.config)})
        p.record({'round':2,'parameters':{'kp':2.1},'observation':observe(rows(.5),3,self.config)})
        self.assertEqual(p.best['round'],1);self.assertEqual(p.stalls,1)

    def test_patience_and_max_rounds_stop(self):
        self.config.patience=1;p=Progress(self.config);item={'parameters':self.reference,'observation':observe(rows(),3,self.config)}
        p.record(item);self.assertEqual(p.record(item),'连续多轮没有改善')
        self.config.maximum_rounds=1;p=Progress(self.config);self.assertEqual(p.record(item),'达到最大轮数')

    def test_invalid_configuration_does_not_start(self):
        for key,value in [('window',0),('maximum_rounds',True),('maximum_seconds',math.inf),('goals',{}),('steps',{'kp':5,'ki':0,'kd':0}),('bounds',{})]:
            with self.subTest(key=key),self.assertRaises((ValueError,KeyError)):
                c=copy.deepcopy(self.config);setattr(c,key,value);c.validate()

    def test_atomic_json_transient_windows_lock_preserves_then_recovers(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import integration
        path=Path(tempfile.mkdtemp(prefix='pid-auto-json-'))/'run.json'
        integration.atomic_json(path,{'state':'previous'})
        original=integration.os.replace
        counter=[0]
        def replace(src,dst):
            counter[0]+=1
            if counter[0]<3:
                error=PermissionError('temporary lock');error.winerror=5;raise error
            original(src,dst)
        with patch('integration.os.replace',side_effect=replace),patch('integration.time.sleep'):
            integration.atomic_json(path,{'state':'current'})
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'state':'current'})
        self.assertEqual(counter[0],3);self.assertEqual(list(path.parent.glob('*.tmp')),[])

    def test_atomic_json_permanent_failure_retains_previous_record(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import integration
        path=Path(tempfile.mkdtemp(prefix='pid-auto-json-'))/'run.json'
        integration.atomic_json(path,{'state':'previous'})
        error=PermissionError('permanent lock');error.winerror=5
        with patch('integration.os.replace',side_effect=error),patch('integration.time.sleep'),self.assertRaises(PermissionError):
            integration.atomic_json(path,{'state':'current'})
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'state':'previous'})
        self.assertEqual(list(path.parent.glob('*.tmp')),[])
