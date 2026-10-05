import copy
import time
import unittest
from core import Experiment, Parameters
from integration import api_context, analysis_identity, proposal_current, LocalBridge


def data():
    exp=Experiment()
    for i in range(101):
        exp.append({'time':i*.1,'target':1 if i < 50 else 2,'actual':.9,'output':1})
    exp.parameter_event(Parameters(kp=3))
    exp.events[-1]['time']=6
    return exp


class AnalysisTests(unittest.TestCase):
    def test_context_matches_rule_window(self):
        ctx=api_context(data(),'模拟设备')
        self.assertEqual(ctx['rule_analysis']['analysis_window']['start_time'],6)
        self.assertEqual(ctx['analyzed_sample_count'],41)
        self.assertEqual(ctx['retained_sample_count'],101)
        self.assertTrue(all(row['time'] >= 6 for row in ctx['samples_decimated_for_model']))

    def test_context_is_independent_of_later_mutation(self):
        exp=data();ctx=api_context(exp,exp.source)
        before=copy.deepcopy(ctx)
        exp.params['kp']=4;exp.samples[-1]['actual']=10;exp.events[-1]['parameters']['kp']=4
        self.assertEqual(ctx,before)

    def test_insufficient_context_has_no_mixed_waveform(self):
        exp=data();exp.events[-1]['time']=9
        ctx=api_context(exp,exp.source)
        self.assertFalse(ctx['rule_analysis']['ready'])
        self.assertEqual(ctx['samples_decimated_for_model'],[])

    def test_identity_ignores_new_samples_but_detects_changed_target(self):
        exp=data();before=analysis_identity(exp)
        exp.append({'time':11,'target':2,'actual':1,'output':1})
        self.assertEqual(analysis_identity(exp),before)
        exp.samples[-1]['target']=3
        self.assertNotEqual(analysis_identity(exp),before)

    def test_proposal_rechecked_against_current_experiment(self):
        exp=data();exp._bridge_id='exp';bridge=LocalBridge()
        proposal={'created_at':time.time(),'session_id':bridge.session_id,'experiment_id':'exp','reference_parameters':copy.deepcopy(exp.params),'reference_source':exp.source,'reference_scenario':exp.scenario}
        self.assertTrue(proposal_current(proposal,bridge,exp))
        for key,value in [('created_at',time.time()-301),('session_id','other'),('experiment_id','other'),('reference_parameters',{}),('reference_source','串口'),('reference_scenario','other')]:
            with self.subTest(key=key):
                changed=dict(proposal);changed[key]=value
                self.assertFalse(proposal_current(changed,bridge,exp))
        self.assertFalse(proposal_current({},bridge,exp))
