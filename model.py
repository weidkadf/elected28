#!/usr/bin/env python3
"""Frame-only 2028 district scenario engine v0.2.3; NOT a calibrated forecast."""
from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
import numpy as np

REQUIRED = {'district_id','region','district_name','party','candidate','votes','valid_votes','source_url','election_date'}
WARNING = [
    'experimental_scenario_not_calibrated_forecast',
    '2024_boundaries_and_candidate_party_field_held_fixed',
    'party_support_inputs_completely_excluded',
    'government_frame_change_is_a_conditional_proxy_not_direct_vote_share',
    'government_opposition_roles_reverse_between_2024_and_2026',
    'new_candidates_party_realignments_and_boundary_changes_not_identified',
    'uncertainty_scales_are_assumptions_not_empirically_validated_intervals',
]

def read_baseline(path):
    """Candidate rows; missing losing candidates invalidate a district, not silently impute it."""
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError('Missing baseline columns: ' + ', '.join(sorted(missing)))
        rows = list(reader)
    districts = {}
    for row in rows:
        key = row['district_id'].strip()
        if not key:
            raise ValueError('Empty district_id')
        d = districts.setdefault(key, {'district_id':key, 'region':row['region'],
            'district_name':row['district_name'], 'candidates':[], 'errors':[]})
        if d['region'] != row['region'] or d['district_name'] != row['district_name']:
            d['errors'].append('inconsistent_district_metadata')
        try:
            votes, valid = int(row['votes']), int(row['valid_votes'])
            if votes < 0 or valid <= 0 or votes > valid:
                raise ValueError()
            date.fromisoformat(row['election_date'])
        except (ValueError, TypeError):
            d['errors'].append('invalid_votes_or_election_date')
            continue
        if not all(row[x].strip() for x in ['party','candidate','source_url']):
            d['errors'].append('missing_party_candidate_or_source')
        d['candidates'].append({**row, 'votes':votes, 'valid_votes':valid})
    for d in districts.values():
        candidates = d['candidates']
        if len(candidates) < 2:
            d['errors'].append('candidate_field_incomplete')
        if len({c['valid_votes'] for c in candidates}) != 1:
            d['errors'].append('inconsistent_valid_votes')
        elif sum(c['votes'] for c in candidates) != candidates[0]['valid_votes']:
            d['errors'].append('candidate_votes_do_not_sum_to_valid_votes')
        if len({(c['party'],c['candidate']) for c in candidates}) != len(candidates):
            d['errors'].append('duplicate_candidate')
        if any(c['election_date'] != '2024-04-10' for c in candidates):
            d['errors'].append('not_22nd_general_election')
        d['errors'] = sorted(set(d['errors']))
    return list(districts.values())

def baseline_summary(d):
    out = {k:d[k] for k in ['district_id','region','district_name']}
    out['forecast_status'] = 'not_estimable'
    out['validation_errors'] = d['errors']
    if not d['errors']:
        cs = sorted(d['candidates'], key=lambda c:c['votes'], reverse=True)
        out['baseline_2024'] = {'winner':cs[0]['candidate'], 'winner_party':cs[0]['party'],
            'margin_pp':round(100*(cs[0]['votes']-cs[1]['votes'])/cs[0]['valid_votes'],3),
            'candidates':[{k:c[k] for k in ['candidate','party','votes','valid_votes','source_url']} for c in cs]}
    return out

VERSION = '0.2.3'
DEM = '더불어민주당'
CON = '국민의힘'
REGIONAL_SCOPE_MEMBERS = {
    '서울': {'서울특별시'},
    '인천/경기': {'인천광역시', '경기도'},
    '강원': {'강원특별자치도'},
    '대전/세종/충청': {'대전광역시', '세종특별자치시', '충청북도', '충청남도'},
    '광주/전라': {'광주광역시', '전라남도', '전북특별자치도'},
    '대구/경북': {'대구광역시', '경상북도'},
    '부산/울산/경남': {'부산광역시', '울산광역시', '경상남도'},
    '제주': {'제주특별자치도'},
}


def validate_baseline_information(districts, poll_data, comparison):
    """Fail closed on result availability; never infer publication from election day.

    Current production uses the date this project actually retrieved the source,
    not an invented historical publication date. Earlier as-of runs require a
    separately evidenced availability date and cannot reuse this snapshot.
    """
    if not districts or not comparison:
        return None
    info = comparison.get('baseline_information')
    if not isinstance(info, dict):
        raise ValueError('baseline_information required for dated result-based scenarios')
    if not poll_data.get('as_of'):
        raise ValueError('Baseline scenarios require an explicit as_of')
    try:
        cutoff = date.fromisoformat(poll_data['as_of'])
        election = date.fromisoformat(info['election_date'])
        available = date.fromisoformat(info['available_on'])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError('Baseline election_date and available_on dates required') from exc
    if not info.get('source_url') or not info.get('availability_basis'):
        raise ValueError('Baseline availability source_url and availability_basis required')
    if available <= election:
        raise ValueError('Baseline date-only availability must be after election day')
    for district in districts:
        for candidate in district['candidates']:
            try:
                candidate_election = date.fromisoformat(candidate['election_date'])
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError('Baseline candidate election_date required and valid') from exc
            if candidate_election != election:
                raise ValueError('Baseline candidate election_date conflicts with information metadata')
    if cutoff <= election:
        raise ValueError('Baseline election result unavailable on or before election day as_of')
    if cutoff < available:
        raise ValueError('Baseline result availability after as_of; historical availability not evidenced')
    return {k: info[k] for k in ['election_date', 'available_on', 'source_url', 'availability_basis']}


def validate_polls(data):
    """Party support is ignored before validation, metadata, and output construction."""
    polls = [p for p in data.get('polls', []) if p.get('question_type') == 'government_frame']
    if polls and not data.get('as_of'):
        raise ValueError('Frame observations require an explicit as_of information date')
    cutoff = date.fromisoformat(data['as_of']) if data.get('as_of') else None
    seen = set()
    for p in polls:
        if not p.get('poll_id') or p['poll_id'] in seen:
            raise ValueError('Frame poll IDs must be nonempty and unique')
        seen.add(p['poll_id'])
        if not (p.get('source_url') or (p.get('source_file') and p.get('library_file_id'))) or not p.get('fieldwork_end'):
            raise ValueError('Frame source and fieldwork_end required')
        fieldwork_end = date.fromisoformat(p['fieldwork_end'])
        if not p.get('published_at'):
            raise ValueError('Frame published_at required; fieldwork_end is not an availability date')
        published = date.fromisoformat(p['published_at'])
        if published < fieldwork_end:
            raise ValueError('Frame publication predates completed fieldwork')
        if cutoff and fieldwork_end > cutoff:
            raise ValueError('Frame poll after as_of')
        if cutoff and published > cutoff:
            raise ValueError('Frame publication after as_of')
        shares = p.get('shares', {})
        if any(not isinstance(v,(int,float)) or not np.isfinite(v) or not 0 <= v <= 1 for v in shares.values()):
            raise ValueError('Frame shares must be finite fractions from 0 to 1')
        if sum(shares.values()) > 1.015:
            raise ValueError('Frame shares exceed rounding tolerance')
    return polls


def matched_support_scenarios(*args, **kwargs):
    raise ValueError('v0.2.0 blocks party-support linkage. Use frame_comparison only.')


def logit(p):
    if not np.isfinite(p) or not 0 < p < 1:
        raise ValueError('Interior probability required for frame logit; do not impute zero/infinite support')
    return float(np.log(p/(1-p)))


def sigmoid(x):
    return 1/(1+np.exp(-np.clip(x,-40,40)))


def democratic_frame_proxy(poll, governing_party, opposition_party):
    """Two-party orientation proxy, conditional on expressing support or opposition."""
    if set([governing_party,opposition_party]) != {DEM,CON}:
        raise ValueError('Explicit democratic/conservative governing-opposition roles required')
    if poll.get('governing_party') and poll['governing_party'] != governing_party:
        raise ValueError('Configured governing party conflicts with observation metadata')
    if poll.get('main_opposition_party') and poll['main_opposition_party'] != opposition_party:
        raise ValueError('Configured opposition party conflicts with observation metadata')
    if poll.get('suppressed'):
        raise ValueError('Suppressed frame observation')
    shares = poll.get('shares',{})
    support, oppose = shares.get('정부지원'), shares.get('정부견제')
    if support is None or oppose is None or support+oppose <= 0:
        raise ValueError('Government support/opposition shares missing')
    q = (support if governing_party==DEM else oppose)/(support+oppose)
    logit(q)
    return float(q)


def matched_frame_scenarios(data, comparison):
    """Build explicit role-aware frame changes; no party-support data are accessed."""
    if not comparison:
        return [], ['frame_comparison_missing']
    polls = {p['poll_id']:p for p in validate_polls(data)}
    try:
        base, current = polls[comparison['baseline_poll_id']], polls[comparison['current_poll_id']]
    except KeyError:
        return [], ['frame_comparison_poll_missing']
    for key in ['pollster','series_id','scope']:
        if not base.get(key) or base.get(key) != current.get(key):
            return [], ['frame_comparison_incompatible_' + key]
    if base['scope'] != 'national':
        return [], ['national_frame_anchor_required']
    if not ('2024-03-01' <= base['fieldwork_end'] < '2024-04-10'):
        return [], ['baseline_frame_not_pre_election_2024']
    if base['published_at'] >= '2024-04-10':
        return [], ['baseline_frame_published_on_or_after_election']
    if current['fieldwork_end'] <= base['fieldwork_end']:
        return [], ['current_frame_not_newer']
    try:
        roles = comparison['roles']
        qb = democratic_frame_proxy(base,**roles['baseline'])
        qc = democratic_frame_proxy(current,**roles['current'])
        shrink_k = float(comparison['regional_shrinkage_k'])
        if not np.isfinite(shrink_k) or shrink_k <= 0:
            raise ValueError('positive regional_shrinkage_k required')
    except (ValueError,KeyError,TypeError) as exc:
        return [], ['frame_comparison_invalid: '+str(exc)]
    national_change = logit(qc)-logit(qb)
    region_changes, region_details = {}, {}
    # A national anchor plus shrunken deviations: the same respondents are never
    # added as an independent national and regional likelihood or sample count.
    for label, spec in comparison.get('regions',{}).items():
        members = spec.get('baseline_regions') if isinstance(spec, dict) else None
        if (label not in REGIONAL_SCOPE_MEMBERS or not isinstance(members, list)
                or any(not isinstance(x, str) for x in members)
                or len(members) != len(set(members))
                or set(members) != REGIONAL_SCOPE_MEMBERS.get(label)):
            return [], ['invalid_regional_frame_'+label+': regional scope/member mapping mismatch']
        residuals, details = {}, {}
        for period, qn, anchor in [('baseline',qb,base),('current',qc,current)]:
            p = polls.get(spec.get(period+'_poll_id'))
            # A present but mislabelled/suppressed record is a configuration
            # error, not missing information to silently replace nationally.
            if p is not None and p.get('scope') != label:
                return [], ['invalid_regional_frame_'+label+': observation scope mismatch']
            missing = p is None or p.get('suppressed') or not p.get('shares')
            if missing:
                residuals[period] = 0.0
                details[period] = {'status':'national_fallback_regional_observation_unavailable','weight':0.0,
                                   'poll_id':spec.get(period+'_poll_id')}
                continue
            try:
                if p.get('pollster') != anchor['pollster'] or p.get('fieldwork_end') != anchor['fieldwork_end'] or p.get('series_id') != anchor['series_id']:
                    raise ValueError('Regional observation must belong to the selected national survey')
                if period == 'baseline' and p['published_at'] >= '2024-04-10':
                    raise ValueError('Baseline regional frame was not public before election')
                n = float(p['sample_size'])
                if not np.isfinite(n) or n <= 0:
                    raise ValueError('Positive regional sample_size required')
                qr = democratic_frame_proxy(p,**roles[period])
                weight = n/(n+shrink_k)
                residuals[period] = weight*(logit(qr)-logit(qn))
                details[period] = {'status':'observed_shrunken','poll_id':p['poll_id'],
                    'sample_size':n,'democratic_frame_proxy':qr,'weight':weight,
                    'weighted_logit_deviation':residuals[period]}
            except (KeyError,ValueError,TypeError) as exc:
                return [], ['invalid_regional_frame_'+label+': '+str(exc)]
        change = national_change + residuals['current']-residuals['baseline']
        for region in spec['baseline_regions']:
            if region in region_changes:
                return [], ['duplicate_region_mapping_'+region]
            region_changes[region] = change
            region_details[region] = {'frame_scope':label,'baseline':details['baseline'],
                                     'current':details['current'],'logit_change':change}
    alphas = comparison.get('transfer_coefficients',[0,0.5,1])
    if not alphas or any(not isinstance(a,(int,float)) or not np.isfinite(a) or not 0<=a<=2 for a in alphas):
        return [], ['invalid_frame_transfer_coefficients']
    scenarios = []
    for alpha in alphas:
        scenarios.append({'name':f'government_frame_delta_alpha_{alpha:g}',
            'calibration_status':'uncalibrated','assume_2024_candidates_and_boundaries':True,
            'source_poll_ids':[base['poll_id'],current['poll_id']],
            'roles':roles,'transfer_coefficient':alpha,
            'national_democratic_frame_proxy':{'baseline':qb,'current':qc},
            'national_frame_logit_change':national_change,
            'regional_frame_logit_change':region_changes,
            'regional_observation_details':region_details,
            'regional_shrinkage_k':shrink_k,
            'uncertainty_logit':comparison.get('uncertainty_logit',{}),
            'third_party_policy':'hold_2024_candidate_shares_fixed_conditionally',
            'missing_major_party_policy':'not_estimable',
            'observation_uncertainty_policy':'no_independent_double_count_of_national_and_regions; latent_error_scales_are_unvalidated_assumptions'})
    return scenarios, []


def eligibility(d):
    if d['errors']:
        return False, 'invalid_2024_baseline'
    parties = [c['party'] for c in d['candidates']]
    if DEM not in parties or CON not in parties:
        return False, 'missing_2024_major_party_candidate_no_automatic_alliance_mapping'
    if parties.count(DEM)!=1 or parties.count(CON)!=1:
        return False, 'ambiguous_multiple_major_party_candidates'
    return True, None


def run_scenario(districts, scenario, *, draws=5000, seed=20261016):
    if scenario.get('calibration_status')!='uncalibrated' or scenario.get('assume_2024_candidates_and_boundaries') is not True:
        raise ValueError('Explicit uncalibrated and frozen candidate/boundary assumptions required')
    if 'party_swing_pp' in scenario or 'national_frame_logit_change' not in scenario:
        raise ValueError('Only government-frame-derived scenarios are allowed in v0.2.0')
    if not 100 <= draws <= 100000:
        raise ValueError('draws must be 100..100000')
    uncertainty = scenario.get('uncertainty_logit',{})
    for k in ['national','region','district']:
        v=uncertainty.get(k)
        if not isinstance(v,(int,float)) or not np.isfinite(v) or not 0<=v<=2:
            raise ValueError('Explicit uncertainty_logit national/region/district in 0..2 required')
    alpha = scenario['transfer_coefficient']
    eligible = [d for d in districts if eligibility(d)[0]]
    pending = [d for d in districts if not eligibility(d)[0]]
    parties = sorted({c['party'] for d in districts for c in d['candidates']})
    regions = sorted({d['region'] for d in districts})
    frame_scopes = sorted(set(scenario.get('regional_observation_details',{}).get(r,{}).get('frame_scope',r) for r in regions))
    pi={p:i for i,p in enumerate(parties)}
    rng=np.random.default_rng(seed)
    # These are latent scenario errors, NOT independent observations of overlapping surveys.
    national_noise=rng.normal(0,uncertainty['national'],draws)
    region_noise={r:rng.normal(0,uncertainty['region'],draws) for r in frame_scopes}
    counts=np.zeros((draws,len(parties)),dtype=int)
    regional_counts={r:np.zeros_like(counts) for r in regions}
    district_outputs=[]
    for d in sorted(districts,key=lambda d:d['district_id']):
        out={k:d[k] for k in ['district_id','district_name','region']}
        allowed,reason=eligibility(d)
        if not allowed:
            district_outputs.append({**out,'status':'not_estimable','reason':reason,
                'simulated_party_win_fraction':None,'candidate_scenarios':None})
            continue
        cs=sorted(d['candidates'],key=lambda c:(c['party'],c['candidate']))
        b=np.array([c['votes']/c['valid_votes'] for c in cs])
        di=next(i for i,c in enumerate(cs) if c['party']==DEM)
        ci=next(i for i,c in enumerate(cs) if c['party']==CON)
        total=b[di]+b[ci]
        p0=b[di]/total
        region_change=scenario.get('regional_frame_logit_change',{}).get(d['region'],scenario['national_frame_logit_change'])
        scope=scenario.get('regional_observation_details',{}).get(d['region'],{}).get('frame_scope',d['region'])
        change=alpha*region_change+national_noise+region_noise[scope]+rng.normal(0,uncertainty['district'],draws)
        # Zero baseline endpoints are preserved, avoiding an arbitrary pseudo-vote/logit infinity.
        if p0==0 or p0==1:
            p=np.full(draws,p0)
        else:
            p=sigmoid(logit(p0)+change)
        shares=np.tile(b,(draws,1))
        shares[:,di]=total*p
        shares[:,ci]=total*(1-p)
        if not np.allclose(shares.sum(axis=1),1) or np.any(shares<0):
            raise RuntimeError('Invalid scenario vote shares')
        winners=np.argmax(shares+rng.uniform(0,1e-12,shares.shape),axis=1)
        ids=np.array([pi[c['party']] for c in cs])
        win_parties=ids[winners]
        counts[np.arange(draws),win_parties]+=1
        regional_counts[d['region']][np.arange(draws),win_parties]+=1
        fractions={p:float(np.mean(win_parties==pi[p])) for p in sorted({c['party'] for c in cs})}
        candidates=[]
        for i,c in enumerate(cs):
            quant=np.quantile(shares[:,i]*100,[.1,.5,.9])
            candidates.append({'baseline_candidate':c['candidate'],'party':c['party'],
                'share_policy':'frame_swing_with_fixed_two_party_total' if i in [di,ci] else 'conditional_fixed_2024_share_not_predicted',
                'scenario_vote_share_pp_p10_p50_p90':[round(float(v),3) for v in quant]})
        district_outputs.append({**out,'status':'experimental_conditional_frame_scenario',
            'frame_scope':scope,'applied_mean_logit_change':alpha*region_change,
            'has_third_party_candidates':len(cs)>2,
            'third_party_policy':scenario['third_party_policy'] if len(cs)>2 else 'not_applicable',
            'two_party_share_fixed':total,'simulated_party_win_fraction':fractions,
            'candidate_scenarios':candidates})
    def summarize(matrix):
        return {p:{'mean_seats':round(float(matrix[:,i].mean()),4),
            'scenario_seats_p10_p50_p90':[int(v) for v in np.quantile(matrix[:,i],[.1,.5,.9],method='nearest')]}
            for p,i in pi.items()}
    pending_by_region={r:sum(d['region']==r for d in pending) for r in regions}
    return {'name':scenario['name'],'status':'experimental_conditional_frame_scenario' if eligible else 'not_estimable',
        'assumptions':scenario,'warnings':WARNING,'draws':draws,'seed':seed,
        'covered_districts':len(districts),'simulated_districts':len(eligible),'not_estimable_districts':len(pending),
        'seat_total_each_draw':len(eligible),'seat_total_including_unestimated':len(districts),
        'national_district_seats':summarize(counts),
        'regional_district_seats':{r:summarize(v) for r,v in regional_counts.items()},
        'regional_not_estimable_seats':pending_by_region,
        'districts':district_outputs,
        'checks':{'all_simulated_draw_seat_totals_correct':bool(np.all(counts.sum(axis=1)==len(eligible))),
                  'simulated_plus_pending_equals_coverage':len(eligible)+len(pending)==len(districts),
                  'two_party_totals_and_third_party_shares_preserved':True}}


def build_report(districts, poll_data=None, comparison=None, *, draws=5000, seed=20261016, expected_districts=254):
    poll_data=poll_data or {'polls':[]}
    # Do not copy arbitrary top-level metadata: it could leak party-support linkage into outputs.
    observations=validate_polls(poll_data)
    if poll_data.get('support_comparison'):
        raise ValueError('Legacy support_comparison is disabled; remove party-support linkage')
    selected_comparison=comparison or poll_data.get('frame_comparison')
    baseline_information=validate_baseline_information(districts,poll_data,selected_comparison)
    scenarios,blocked=matched_frame_scenarios(poll_data,selected_comparison)
    reports,failures=[],[]
    for scenario in scenarios:
        try:
            reports.append(run_scenario(districts,scenario,draws=draws,seed=seed))
        except ValueError as exc:
            failures.append({'name':scenario['name'],'reason':str(exc),'status':'not_estimable'})
    valid=sum(not d['errors'] for d in districts)
    return {'schema_version':VERSION,'as_of':poll_data.get('as_of'),
        'baseline_information':baseline_information,
        'linkage':'government_support_opposition_frame_only',
        'forecast_status':'not_estimable',
        'model_status':'experimental_frame_scenarios_available' if any(r['simulated_districts'] for r in reports) else 'baseline_or_input_validation_only',
        'coverage':{'expected_districts':expected_districts,'observed_districts':len(districts),'valid_districts':valid,
            'scenario_eligible_districts':sum(eligibility(d)[0] for d in districts),
            'complete':len(districts)==valid==expected_districts},
        'warnings':WARNING,'poll_observations':observations,'frame_comparison_blockers':blocked,
        'baseline':[baseline_summary(d) for d in sorted(districts,key=lambda d:d['district_id'])],
        'scenarios':reports,'scenario_failures':failures,
        'excluded_inputs':['party_support','vote_intention'],
        'not_modeled':['proportional_representation','candidate_nomination','party_mergers','boundary_redistricting',
                       'turnout_change','calibrated_frame_to_vote_transfer','future_frame_trend','new_or_absent_party_candidates']}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline',required=True)
    ap.add_argument('--polls')
    ap.add_argument('--frame-comparison',help='JSON object selecting government-frame polls and role assumptions')
    ap.add_argument('--comparison',help='Alias for --frame-comparison; only government_frame config accepted')
    ap.add_argument('--scenarios',help='Legacy party-swing option, blocked in v0.2.0')
    ap.add_argument('--output',required=True)
    ap.add_argument('--draws',type=int,default=5000)
    ap.add_argument('--seed',type=int,default=20261016)
    ap.add_argument('--expected-districts',type=int,default=254)
    args=ap.parse_args()
    if args.scenarios or (args.comparison and args.frame_comparison):
        ap.error('Only one frame comparison configuration is permitted; direct-party-swing scenarios are disabled')
    load=lambda p:json.loads(Path(p).read_text(encoding='utf-8')) if p else None
    comparison=load(args.frame_comparison or args.comparison)
    if comparison and comparison.get('comparison_type') != 'government_frame':
        ap.error('Comparison config must explicitly declare comparison_type=government_frame; legacy party-support config blocked')
    result=build_report(read_baseline(args.baseline),load(args.polls),comparison,draws=args.draws,
        seed=args.seed,expected_districts=args.expected_districts)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':args.output,'model_status':result['model_status'],'coverage':result['coverage']},ensure_ascii=False))

if __name__=='__main__':main()
