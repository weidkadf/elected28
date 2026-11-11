import copy
import unittest
import numpy as np
from model import (DEM,CON,build_report,run_scenario,matched_frame_scenarios,
                   democratic_frame_proxy,matched_support_scenarios)


def district(key='01',region='서울특별시',third=False,missing_dem=False):
    shares=[(DEM,55),(CON,45)]
    if third:shares=[(DEM,44),(CON,36),('제3당',20)]
    if missing_dem:shares=[('제3당',55),(CON,45)]
    return {'district_id':key,'region':region,'district_name':'예시'+key,'errors':[],
        'candidates':[{'party':p,'candidate':p+'후보','votes':v,'valid_votes':100,'election_date':'2024-04-10','source_url':'https://example.test/source'} for p,v in shares]}


def fixture():
    base={'poll_id':'old','pollster':'X','series_id':'government_frame','scope':'national',
        'question_type':'government_frame','fieldwork_end':'2024-03-28','published_at':'2024-03-29','sample_size':1001,
        'source_url':'https://example.test/old','shares':{'정부지원':.4,'정부견제':.5,'유보':.1}}
    current={**base,'poll_id':'new','fieldwork_end':'2026-10-15','published_at':'2026-10-16','source_url':'https://example.test/new'}
    data={'as_of':'2026-10-16','polls':[base,current]}
    config={'comparison_type':'government_frame','baseline_poll_id':'old','current_poll_id':'new',
        'baseline_information':{'election_date':'2024-04-10','available_on':'2024-04-11',
                                'source_url':'https://example.test/synthetic-result',
                                'availability_basis':'synthetic_test_fixture_not_real_publication'},
        'roles':{'baseline':{'governing_party':CON,'opposition_party':DEM},
                 'current':{'governing_party':DEM,'opposition_party':CON}},
        'regional_shrinkage_k':400,'transfer_coefficients':[0,0.5,1],
        'uncertainty_logit':{'national':.12,'region':.1,'district':.18}}
    return data,config


class FrameModelTests(unittest.TestCase):
    def test_future_release_is_blocked_even_if_fieldwork_has_finished(self):
        data,cfg=fixture();data['polls'][1]['published_at']='2026-10-17'
        with self.assertRaisesRegex(ValueError,'publication after as_of'):
            build_report([district()],data,cfg,draws=100)

    def test_missing_release_date_is_not_assumed_available(self):
        data,cfg=fixture();del data['polls'][1]['published_at']
        with self.assertRaisesRegex(ValueError,'published_at required'):
            build_report([district()],data,cfg,draws=100)

    def test_postelection_baseline_release_is_rejected(self):
        data,cfg=fixture();data['polls'][0]['published_at']='2024-04-11'
        scenarios,reasons=matched_frame_scenarios(data,cfg)
        self.assertFalse(scenarios)
        self.assertIn('baseline_frame_published_on_or_after_election',reasons)

    def test_postelection_regional_release_cannot_leak_through_national_anchor(self):
        data,cfg=fixture()
        data['polls'].append({**data['polls'][0],'poll_id':'late_region','scope':'서울',
                              'published_at':'2024-04-11'})
        cfg['regions']={'서울':{'baseline_poll_id':'late_region','current_poll_id':'missing',
                               'baseline_regions':['서울특별시']}}
        scenarios,reasons=matched_frame_scenarios(data,cfg)
        self.assertFalse(scenarios)
        self.assertIn('not public before election',reasons[0])

    def test_party_support_changes_do_not_change_any_output(self):
        data,cfg=fixture()
        a=build_report([district()],data,cfg,draws=300)
        # Even malformed party support has no route to validation or output.
        data['polls'].append({'question_type':'party_support','shares':{DEM:999,CON:-900},'poll_id':'new'})
        b=build_report([district()],data,cfg,draws=300)
        self.assertEqual(a,b)
        data['polls'][-1]['shares']={DEM:.01,CON:.99}
        self.assertEqual(a,build_report([district()],data,cfg,draws=300))

    def test_roles_reverse_sign(self):
        data,cfg=fixture()
        old,new=data['polls']
        self.assertAlmostEqual(democratic_frame_proxy(old,CON,DEM),5/9)
        self.assertAlmostEqual(democratic_frame_proxy(new,DEM,CON),4/9)
        scenarios,errors=matched_frame_scenarios(data,cfg)
        self.assertFalse(errors)
        self.assertLess(scenarios[-1]['national_frame_logit_change'],0)

    def test_same_democratic_orientation_means_zero_change(self):
        data,cfg=fixture()
        data['polls'][1]['shares']={'정부지원':.5,'정부견제':.4,'유보':.1}
        scenarios,errors=matched_frame_scenarios(data,cfg)
        self.assertFalse(errors)
        self.assertAlmostEqual(scenarios[-1]['national_frame_logit_change'],0)

    def test_more_current_government_support_increases_democratic_share(self):
        data,cfg=fixture();cfg['uncertainty_logit']={k:0 for k in ['national','region','district']}
        a=build_report([district()],data,cfg,draws=100)['scenarios'][-1]
        data['polls'][1]['shares']={'정부지원':.6,'정부견제':.3,'유보':.1}
        b=build_report([district()],data,cfg,draws=100)['scenarios'][-1]
        def median(r):
            return next(x['scenario_vote_share_pp_p10_p50_p90'][1] for x in r['districts'][0]['candidate_scenarios'] if x['party']==DEM)
        self.assertGreater(median(b),median(a))

    def test_third_party_fixed_and_missing_major_party_pending(self):
        data,cfg=fixture()
        r=build_report([district(third=True),district('02',missing_dem=True)],data,cfg,draws=300)['scenarios'][-1]
        self.assertEqual(r['simulated_districts'],1)
        self.assertEqual(r['not_estimable_districts'],1)
        self.assertEqual(r['districts'][1]['status'],'not_estimable')
        self.assertIsNone(r['districts'][1]['simulated_party_win_fraction'])
        third=next(x for x in r['districts'][0]['candidate_scenarios'] if x['party']=='제3당')
        self.assertEqual(third['scenario_vote_share_pp_p10_p50_p90'],[20,20,20])
        self.assertAlmostEqual(r['districts'][0]['two_party_share_fixed'],.8)

    def test_reproducibility_and_all_seats_accounted(self):
        data,cfg=fixture();ds=[district(),district('02',third=True),district('03',missing_dem=True)]
        a=build_report(ds,data,cfg,draws=400,seed=17,expected_districts=3)
        b=build_report(ds,data,cfg,draws=400,seed=17,expected_districts=3)
        self.assertEqual(a,b)
        for s in a['scenarios']:
            self.assertTrue(all(s['checks'].values()))
            self.assertAlmostEqual(sum(x['mean_seats'] for x in s['national_district_seats'].values())+s['not_estimable_districts'],3,places=3)

    def test_no_inputs_and_legacy_linkage_blocked(self):
        r=build_report([])
        self.assertEqual(r['forecast_status'],'not_estimable')
        self.assertFalse(r['scenarios'])
        with self.assertRaises(ValueError):matched_support_scenarios({})
        data,cfg=fixture();data['support_comparison']={'current_poll_id':'anything'}
        with self.assertRaises(ValueError):build_report([],data,cfg)

    def test_zero_change_and_zero_error_recovers_baseline(self):
        data,cfg=fixture();cfg['transfer_coefficients']=[0]
        cfg['uncertainty_logit']={k:0 for k in ['national','region','district']}
        s=build_report([district(third=True)],data,cfg,draws=100)['scenarios'][0]
        vals={c['party']:c['scenario_vote_share_pp_p10_p50_p90'] for c in s['districts'][0]['candidate_scenarios']}
        self.assertEqual(vals[DEM],[44,44,44]);self.assertEqual(vals[CON],[36,36,36])

    def test_suppressed_region_uses_national_change_with_explicit_flag(self):
        data,cfg=fixture()
        cfg['regions']={'서울':{'baseline_poll_id':'missing','current_poll_id':'missing', 'baseline_regions':['서울특별시']}}
        scenarios,errors=matched_frame_scenarios(data,cfg)
        s=scenarios[-1]
        self.assertAlmostEqual(s['regional_frame_logit_change']['서울특별시'],s['national_frame_logit_change'])
        self.assertEqual(s['regional_observation_details']['서울특별시']['current']['weight'],0)

if __name__=='__main__':unittest.main()
