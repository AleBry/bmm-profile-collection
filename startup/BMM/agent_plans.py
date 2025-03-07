from typing import Sequence

import bluesky.preprocessors as bpp
import redis
from bluesky import plan_stubs as bps
from BMM.edge import change_edge
from BMM.user_ns.instruments import slits3
from BMM.user_ns.motors import xafs_det

__all__ = ["agent_driven_nap", "agent_move_and_measure"]


@bpp.run_decorator()
def agent_driven_nap(delay: float, *, delay_kwarg: float = 0, md=None):
    """Ensuring we can auto add 'agent_' plans and use args/kwargs"""
    if delay_kwarg:
        yield from bps.sleep(delay_kwarg)
    else:
        yield from bps.sleep(delay)


def agent_measure_single_edge(motor_x, x_position, motor_y, y_position, *, md=None, **kwargs):
    """
    A complete XAFS measurement for a single edge.
    The element edge must have its own calibrated motor positioning and detector distance.
    The sample is moved into position, and spectra taken. The edge is assumed to be set.

    Parameters
    ----------
    motor_x : str
        Positional motor for sample in x.
    x_position : float
        Absolute x motor position for sample measurement (This is the real independent variable)
    motor_y : str
        Positional motor for sample in y.
    y_position : float
        Absolute y motor position for sample measurement
    md : Optional[dict]
        Metadata
    kwargs :
        All keyword arguments for the xafs plan. Must include  'filename'. Eg below:
            >>> {'filename': 'Cu_PdCuCr_112421_001',
            >>> 'nscans': 1,
            >>> 'start': 'next',
            >>> 'mode': 'fluorescence',
            >>> 'element': 'Cu',
            >>> 'edge': 'K',
            >>> 'sample': 'PdCuCr',
            >>> 'preparation': 'film deposited on something',
            >>> 'comment': 'index = 1, position (x,y) = (-9.04, -31.64), center at (236.98807533, 80.98291381)',
            >>> 'bounds': '-200 -30 -10 25 12k',
            >>> 'steps': '10 2 0.3 0.05k',
            >>> 'times': '0.5 0.5 0.5 0.5'}
    """
    rkvs = redis.Redis(host="xf06bm-ioc2", port=6379, db=0)
    element = rkvs.get("BMM:pds:element").decode("utf-8")
    edge = rkvs.get("BMM:pds:edge").decode("utf-8")
    yield from bps.mv(motor_x, x_position)
    _md = dict(x_position=motor_x.position, redis_element=element, redis_edge=edge)
    yield from bps.mv(motor_y, y_position)
    _md["det_position"] = xafs_det.position
    _md.update(md or {})
    yield from xafs(comment=str(_md), **kwargs)


def agent_move_and_measure(
    motor_x,
    elem1_x_position,
    elem2_x_position,
    motor_y,
    elem1_y_position,
    elem2_y_position,
    elem1_det_position,
    elem2_det_position,
    *,
    elements: Sequence[str],
    edges: Sequence[str],
    md=None,
    **kwargs,
):
    """
    A complete XAFS measurement for a two element sample.
    Each element edge must have it's own calibrated motor positioning and detector distance.
    The sample is moved into position, edge changed and spectra taken.
    Parameters
    ----------
    motor_x :
        Positional motor for sample in x.
    elem1_x_position : float
        Absolute motor position for element 1 measurement (This is the real independent variable)
    elem2_x_position : float
        Absolute motor position for element 2 measurement
    motor_y :
        Positional motor for sample in y.
    elem1_y_position : float
        Absolute motor position for element 1 measurement
    elem2_y_position : float
        Absolute motor position for element 2 measurement
    elem1_det_position : float
        Absolute motor position for the xafs detector for the element 1 measurement.
    elem2_det_position : float
        Absolute motor position for the xafs detector for the element 2 measurement.
    elements : Sequence[str]
        List of element symbols
    edges: Sequence[str]
        List of edges corresponding to elements

    md : Optional[dict]
        Metadata
    kwargs :
        All keyword arguments for the xafs plan. Must include  'filename'. Eg below:
            >>> {'filename': 'Cu_PdCuCr_112421_001',
            >>> 'nscans': 1,
            >>> 'start': 'next',
            >>> 'mode': 'fluorescence',
            >>> 'element': 'Cu',
            >>> 'edge': 'K',
            >>> 'sample': 'PdCuCr',
            >>> 'preparation': 'film deposited on something',
            >>> 'comment': 'index = 1, position (x,y) = (-9.04, -31.64), center at (236.98807533, 80.98291381)',
            >>> 'bounds': '-200 -30 -10 25 12k',
            >>> 'steps': '10 2 0.3 0.05k',
            >>> 'times': '0.5 0.5 0.5 0.5'}
    """
    fname = kwargs['filename']

    def elem1_plan():
        kwargs['filename'] = f"{elements[0]}_{fname}"
        yield from bps.mv(motor_x, elem1_x_position)
        _md = {f"{elements[0]}_position": motor_x.position}
        yield from bps.mv(motor_y, elem1_y_position)
        yield from bps.mv(xafs_det, elem1_det_position)
        _md[f"{elements[0]}_det_position"] = xafs_det.position
        _md.update(md or {})
        #yield from bps.mv(slits3.vsize, 0.1)
        if rkvs.get("BMM:pds:element").decode("utf-8") != elements[0]:
            yield from change_edge(elements[0], focus=True) #, slits=False)  # slits=False uses special knowledge 12/12/23
        # xafs doesn't take md, so stuff it into a comment string to be ast.literal_eval()
        yield from xafs(element=elements[0], edge=edges[0], comment=str(_md), **kwargs)

    def elem2_plan():
        kwargs['filename'] = f"{elements[1]}_{fname}"
        yield from bps.mv(motor_x, elem2_x_position)
        _md = {f"{elements[1]}_position": motor_x.position}
        yield from bps.mv(motor_y, elem2_y_position)
        yield from bps.mv(xafs_det, elem2_det_position)
        _md[f"{elements[1]}_det_position"] = xafs_det.position
        _md.update(md or {})
        #yield from bps.mv(slits3.vsize, 0.3)
        if rkvs.get("BMM:pds:element").decode("utf-8") != elements[1]:
            yield from change_edge(elements[1], focus=True) #, slits=False)  # slits=False uses special knowledge 12/12/23
        yield from xafs(element=elements[1], edge=edges[1], comment=str(_md), **kwargs)

    rkvs = redis.Redis(host="xf06bm-ioc2", port=6379, db=0)
    element = rkvs.get("BMM:pds:element").decode("utf-8")
    # edge = rkvs.get('BMM:pds:edge').decode('utf-8')
    if element == elements[1]:
        yield from elem2_plan()
        yield from elem1_plan()
    else:
        yield from elem1_plan()
        yield from elem2_plan()


def agent_move_motor(motor_x, Cu_x_position, *args, **kwargs):
    yield from bps.mv(motor_x, Cu_x_position)


def agent_change_edge(element):
    yield from change_edge(element, focus=True)





######################################################################
## This section involves functionality for an experiment involving
## CMS and Karen Chen-Wiegart's group.  Experiments driven by AI at
## CMS will occassionally push a measurement to BMM's queueserver.
## The following implements BMM's response for that experiment.
######################################################################

from bluesky.plan_stubs import sleep, mv, mvr, null
from bluesky.preprocessors import finalize_wrapper

import json, os, pprint
from BMM.functions      import now
from BMM.logging        import report
from BMM.periodictable  import Z_number, element_symbol
from BMM.resting_state  import resting_state_plan
from BMM.user_ns.motors import xafs_x

from BMM import user_ns as user_ns_module
user_ns = vars(user_ns_module)

try:
    from bluesky_queueserver import is_re_worker_active
except ImportError:
    # TODO: delete this when 'bluesky_queueserver' is distributed as part of collection environment
    def is_re_worker_active():
        return False


    
def CMS_driven_measurement(composition=None, distance=None, time=None, scantype='xanes'):
    '''The purpose of this plan is to convert the experimental "coordinates" 
    from CMS into physical coordinates on a set of samples at BMM.

    parameters
    ==========
    composition (type)
      meaning

    distance (float)
      distance from measured zero position on the selected sample

    time (float)
      The time that the corresponding sample at CMS has been subjected to heat.  
      This value is used to select the appropriate sample from the list below.

    scantype (str)
      xanes (during the CMS AE experiment) or exafs (overnight revisiting the points)

    configuration
    =============

    Detector distances for the edges and nominal
    xafs_x/xafs_pitch/xafs_y positions of each sample are stored in a
    JSON file called `cms.json` in the users Workspace folder.  Can
    also configure whether mesages specific to this plan are echoed to
    Slack.


    notes
    =====

    From Cheng-Chu:

      We will have 6 samples (top: 40 mm x 10 mm; bottom: 45 mm x 10 mm)
      with different heating durations:

      T1: 300 s
      T2: 600 s
      T3: 1200 s
      T4: 1800 s
      T5: 3600 s
      T6: 5400 s

    There are three edges to be measured at each position on each samples:
    Sc, V, Mn

    Once the 6 samples are mounted on the sample holder at BMM, each
    will be aligned in the beam with xafs_x and xafs_pitch positions
    for the aligned sample recorded.  Also recorded will the xafs_y
    value of the zero position on each sample.

    From that tuple of (xafs_x, xafs_pitch, xafs_y) positions, the
    value of distance will be used to compute the measurement position.

    So, the game plan is:
    1. Rotate xafs_garot to the correct sample computed from time
    2. Compute the xafs_y position from distance
    3. Move to (xafs_x, xafs_pitch, xafs_y)
    4. Measure XAS at (Sc, V, Mn) or (Mn, V, Sc) as appropriate

    '''

    def main_plan(composition, distance, time, scantype):
        if composition is None:
            composition = config['composition']
        report(f"*CMS:* Received instructions: {composition = }, {distance = }, {time = }, {scantype = }", slack=config['slack'])
        distance = float(distance)
        time = int(time)
        
        if str(scantype) == 'xanes':
            with open('/nsls2/data3/bmm/legacy/overnight.txt', 'a', encoding='utf-8') as f:
                f.write(f"{now()}  {composition}  {distance} {time}\n")

        ga.spin = False
        ga.orientation = 'perpendicular'
        durations = list((config['origins'][x]['duration'] for x in config['origins'].keys()))
        this_time = min(durations, key=lambda x:abs(x-time))  # find sample duration closest to requested time
        sample = None
        for i,k in enumerate(config['origins'].keys()):
            if this_time == config['origins'][k]['duration']:
                sample = k
                position = i+1
                report(f'*CMS:* Rotating to sample {sample} at position {position}', slack=config['slack'])
                yield from ga.to(position)

        xpos  = config['origins'][sample]['xafs_x']
        pitch = config['origins'][sample]['xafs_pitch']
        roll  = config['origins'][sample]['xafs_roll']
        ypos  = config['origins'][sample]['xafs_y'] - float(distance) - 0.2
        report(f'*CMS:* Moving to {distance = }  (X={xpos:.3f}, pitch={pitch:.3f}, roll={roll:.3f}, Y={ypos:.3f})', slack=config['slack'])
        yield from mv(xafs_x, xpos, xafs_pitch, pitch, xafs_y, ypos, xafs_roll, roll)
        yield from sleep(1)


        ## put edges in ascending order by Z number
        znums = list(Z_number(x) for x in config['detector_distances'].keys())
        elements = list(element_symbol(x) for x in sorted(znums))
        ## if mono is currently at the highest energy edge, reverse the element list
        if BMMuser.element == elements[-1]:
            elements.reverse()


        for i, el in enumerate(elements):
            report(f'*CMS:* {scantype} measurement: {el} edge of sample {composition = }, {sample = }, {distance = }, {time = }', slack=config['slack'])
            yield from mv(xafs_det, config['detector_distances'][el])
            if i > 0:
                if config['dryrun'] is False:
                    yield from change_edge(el, focus=True)
                else:
                    print(f"change_edge('{el}', focus=True)")
                    yield from sleep(3)

            ## also need reference XANES measurement

            if scantype == 'xanes':
                filename = f"{el}_{composition}_{distance:.3f}_{time}"
            else:
                filename = f"{el}_{composition}_{distance:.3f}_{time}_exafs"
            comment = f"sample = {sample}, distance = {distance:.3f}, {time = }"
            prep = f"{composition}, film deposited on glass, heated for {this_time} seconds"
            if scantype == 'xanes':
                kwargs = config['xanes']
            else:
                reference_kwargs = config['reference']
                kwargs = config['exafs']
                
            if config['dryrun'] is False:
                if scantype == 'exafs':
                    yield from mvr(xafs_x, -10)
                    yield from xafs(filename="Tifoil_"+filename, sample=composition, prep=prep, comment=comment, **reference_kwargs)
                    yield from mvr(xafs_x, 10)
                yield from xafs(filename=filename, sample=composition, prep=prep, comment=comment, **kwargs)
            else:
                print(f"xafs('/nsls2/data3/bmm/legacy/{el}_{scantype}', {filename=}, sample='{composition} {sample}', {prep =}, {comment=}, {kwargs})")
                yield from sleep(3)


    def cleanup_plan():
        report(f'== Finished a CMS driven measurement', level='bold', slack=config['slack'])
        yield from resting_state_plan()
        if not is_re_worker_active():
            BMMuser.prompt = True
        
        
    BMMuser = user_ns['BMMuser']
    ga = user_ns['ga']
    xafs = user_ns['xafs']
    xafs_x, xafs_y, xafs_pitch, xafs_roll = user_ns['xafs_x'], user_ns['xafs_y'], user_ns['xafs_pitch'], user_ns['xafs_roll']
    xafs_detx = user_ns['xafs_detx']
    BMMuser.prompt = False
    with open('/nsls2/data3/bmm/legacy/cms.json') as f:
        config = json.load(f)
    # pprint.pprint(config)
    # print('\n')

    if scantype is not None:
        scantype = str(scantype)
        if 'xanes' in scantype:
            scantype = 'xanes'

    
    yield from finalize_wrapper(main_plan(composition, distance, time, scantype), cleanup_plan())


from bluesky_queueserver_api.http import REManagerAPI
from bluesky_queueserver_api import BPlan

def populate_overnight_CMS_driven_experiments():
    '''Parse the hokey file written by CMS_driven_measurement containing a
    list of positions and times.  For each line, generate the
    corresponding BPLan and submit it to the queue.

    '''
    with open('/nsls2/data3/bmm/legacy/overnight.txt', 'r') as f:
        instructions = f.readlines()

    beamline_tla  = "bmm"
    qs = REManagerAPI(http_server_uri=f"https://qserver.nsls2.bnl.gov/{beamline_tla}")
    qs.set_authorization_key(api_key="dbb8b2a3060cc02cfjg9029ncls2983sx7jd7CMSBeamtime20250303")
    for inst in instructions:
        dt, composition, position, time = inst.split()
        position = float(position)
        time = int(time)
        plan = BPlan('CMS_driven_measurement', composition, position, time, 'exafs')
        qs.item_add(plan)
