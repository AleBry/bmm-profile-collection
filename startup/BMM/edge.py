try:
    from bluesky_queueserver import is_re_worker_active
except ImportError:
    # TODO: delete this when 'bluesky_queueserver' is distributed as part of collection environment
    def is_re_worker_active():
        return False

import time, json, os

from bluesky.plan_stubs import null, sleep, mv, mvr
from bluesky.preprocessors import finalize_wrapper

from BMM.exceptions    import FailedDCMParaException, ArrivedInModeException
from BMM.logging       import BMM_log_info, BMM_msg_hook, report
from BMM.periodictable import edge_energy, Z_number, element_symbol
from BMM.functions     import boxedtext, countdown, approximate_pitch, PROMPT
from BMM.suspenders    import BMM_suspenders, BMM_clear_to_start, BMM_clear_suspenders
from BMM.functions     import error_msg, warning_msg, go_msg, url_msg, bold_msg, verbosebold_msg, list_msg, disconnected_msg, info_msg, whisper
from BMM.kafka         import kafka_message
from BMM.wheel         import show_reference_wheel
from BMM.modes         import change_mode, get_mode, pds_motors_ready, MODEDATA
from BMM.linescans     import rocking_curve, slit_height
from BMM.derivedplot   import close_all_plots, close_last_plot
from BMM.resting_state import resting_state_plan
from BMM.workspace     import rkvs

from BMM import user_ns as user_ns_module
user_ns = vars(user_ns_module)

from BMM.user_ns.bmm         import BMMuser, rois
from BMM.user_ns.dcm         import *
from BMM.user_ns.detectors   import xs, xs1, with_xspress3
from BMM.user_ns.instruments import * #kill_mirror_jacks, m3_ydi, m3_ydo, m3_yu, m3_xd, m3_xu, ks, m2_ydi, m2_ydo, m2_yu
from BMM.user_ns.motors      import *

def show_edges():
    if with_xspress3 is True:
        text = show_reference_wheel() + '\n' + xs.show_rois()
    else:
        text = show_reference_wheel() + '\n' + rois.show()
    boxedtext('Foils and ROIs configuration', text[:-1], 'brown', width=85)


def all_connected(with_m2=False):
    motors = [dm3_bct,
              xafs_yu, xafs_ydo, xafs_ydi,
              m3_yu, m3_ydo, m3_ydi, m3_xu, m3_xd,]
    if with_m2 is True:
        motors.extend([m2_yu, m2_ydo, m2_ydi])
    ok = True
    for m in motors:
        if m.connected is False:
            print(disconnected_msg(f'{m.name} is not connected'))
            for walk in m.walk_signals(include_lazy=False):
                if walk.item.connected is False:
                    print(disconnected_msg(f'      {walk.item.name} is a disconnected PV'))
            print(whisper(f'try: {m.name} = {m.__class__}("{m.prefix}", name={m.name})'))
            ok = False
    return ok

def wiggle_mirrors():
    motors3 = [m3_yu, m3_ydo, m3_ydi, m3_xu, m3_xd]
    motors2 = [m2_yu, m2_ydo, m2_ydi, m2_bender]

    trouble = False
    for m in motors2:
        if "bender" in m.name:
            yield from mvr(m, -10)
        else:
            yield from mvr(m, 0.01)
        if m.amfe.get() or m.amfae.get():
            trouble = True
    if trouble is True:
        user_ns['ks'].cycle('m2')
    trouble = False
    
    for m in motors3:
        yield from mvr(m, 0.01)
        if m.amfe.get() or m.amfae.get():
            trouble = True
    if trouble is True:
        user_ns['ks'].cycle('m3')
        
            
def arrived_in_mode(mode=None):
    motors = [dm3_bct,
              xafs_yu, xafs_ydo, xafs_ydi,
              m2_yu, m2_ydo, m2_ydi, #m2_xu, m2_xd,
              m3_yu, m3_ydo, m3_ydi, m3_xu, m3_xd,]
    ok = True
    for m in motors:
        target = float(MODEDATA[m.name][mode])
        achieved = m.position
        diff = abs(target - achieved)
        if diff > 0.5:
            print(f'{m} is out of position, target={target}, current position={achieved}')
            ok = False
    return ok

def m2_lateral_position(energy=None):
    '''In an attempt to deliver the beam to a more constant position at
    the XAFS end station, we adjust the M2 lateral position to deflect
    the beam sideways.

    These parameters were obtained from looking at the focused beam on
    the direct beam camera and adjusting m2.lateral to bring the beam
    to the same horizontal position (within uncertainty from the bleed
    on the sensor).  These positions were recorded as a function of
    energy for every second element from Ti to Mo, then regressed
    above and below 8 keV (i.e. in Modes A and C).  (See .org and .png
    files in ~/Data/Staff/Bruce Ravel/2023-05-02 for details.)

    '''
    if energy is None:
        print('Usage: m2_lateral_position(energy)')
        return None
    if user_ns['dcm']._crystal == '311':
        print('Have not yet calibrated M2 lateral for the 311 mono.')
        print('Not computing position.')
        return None
    if energy > 7999:
        slope = 5.44903781e-06
        intercept = -9.96931312e-01
    else:
        slope = 9.31465746e-05
        intercept = -1.33792232e+00

    target = energy * slope + intercept
    return target


    
def change_edge(el, focus=False, edge='K', energy=None, slits=True, tune=True, target=300.,
                xrd=False, bender=True, insist=False):
    '''Change edge energy by:
    1. Moving the DCM above the edge energy
    2. Moving the photon delivery system to the correct mode
    3. Running a rocking curve scan
    4. Running a slits_height scan

    Parameters
    ----------
    el : str
        one- or two-letter symbol
    focus : bool, optional
        T=focused or F=unfocused beam [False, unfocused]
    edge : str, optional
        edge symbol ['K']
    energy : float, optional
        e0 value [None, determined from el/edge]
    tune : bool, optional
        perform rocking_curve() scan [True]
    slits : bool, optional
        perform slit_height() scan [True]
    target : float, optional
        energy where rocking curve is measured [300]
    xrd : boolean, optional
        force photon delivery system to XRD [False]
    insist : boolean
        override the check for whether to move M2, when True always move M2 [False]

    Examples
    --------
    Normal use, unfocused beam:
       
    >>> RE(change_edge('Fe'))

    Normal use, focused beam:
       
    >>> RE(change_edge('Fe', focus=True))

    L2 or L1 edge:
       
    >>> RE(change_edge('Re', edge='L2'))

    Measure rocking curve at edge energy:
      
    >>> RE(change_edge('Fe', target=0))

    XRD, new energy:
       
    >>> RE(change_edge('Fe', xrd=True, energy=8600))
        
    note that you must specify an element, but it doesn't matter which
    one the energy will be moved to the specified energy xrd=True
    implies focus=True and target=0

    '''

    def main_plan(el, focus, edge, energy, slits, tune, target, xrd, bender, insist):
        el = el.capitalize()
        ######################################################################
        # this is a tool for verifying a macro.  this replaces an xafsmod scan  #
        # with a sleep, allowing the user to easily map out motor motions in #
        # a macro                                                            #
        if BMMuser.macro_dryrun:
            print(info_msg('\nBMMuser.macro_dryrun is True.  Sleeping for %.1f seconds rather than changing to the %s edge.\n' %
                           (BMMuser.macro_sleep, el)))
            countdown(BMMuser.macro_sleep)
            yield from null()
            return
        ######################################################################

        ## try to trigger an amplifier failure before getting into the meat of the edge change
        #yield from wiggle_mirrors()
        
        ready_count = 0
        while pds_motors_ready() is False:
            print(whisper('Pausing 5 seconds before trying kill switches.'))
            yield from mv(user_ns['busy'], 5)
            ready_count += 1
            report('\nOne or more motors are showing amplifier faults. Attempting to correct the problem.', level='error', slack=True)
            problem_is_m2 = False
            for m in (m2.xu, m2.xd, m2.yu, m2.ydo, m2.ydi, m2_bender):
                if m.amfe.get() or m.amfae.get():
                    problem_is_m2 = True
            if problem_is_m2 is True:
                user_ns['ks'].cycle('m2')

            problem_is_m3 = False
            for m in (m3.xu, m3.xd, m3.yu, m3.ydo, m3.ydi):
                if m.amfe.get() or m.amfae.get():
                    problem_is_m3 = True
            if problem_is_m3 is True:
                user_ns['ks'].cycle('m3')

            problem_is_dcm = False
            for m in (dcm_pitch, dcm_roll, dcm_perp, dcm_roll, dcm_bragg):
                if m.amfe.get() or m.amfae.get():
                    problem_is_dcm = True
            if problem_is_dcm is True:
                user_ns['ks'].cycle('dcm')

            problem_is_dm3 = False
            if dm3_bct.amfe.get() or dm3_bct.amfae.get():
                problem_is_dm3 = True
            if problem_is_dm3 is True:
                user_ns['ks'].cycle('dm3')

            if ready_count > 5:
                report('Failed to fix an amplifier fault.')
                yield from null()
                return


        (ok, text) = BMM_clear_to_start()
        if ok is False:
            print(error_msg('\n'+text) + bold_msg('Quitting change_edge() macro....\n'))
            yield from null()
            return

        if energy is None:
            energy = edge_energy(el,edge)

        if energy is None:
            print(error_msg('\nEither %s or %s is not a valid symbol\n' % (el, edge)))
            yield from null()
            return
        if energy > 23500:
            edge = 'L3'
            energy = edge_energy(el,'L3')

        if energy < 4000:
            print(warning_msg('The %s edge energy is below 4950 eV' % el))
            print(warning_msg('You have to change energy by hand.'))
            yield from null()
            return

        if energy > 23500:
            print(warning_msg('The %s edge energy is outside the range of this beamline!' % el))
            yield from null()
            return

        BMM_suspenders()

        if energy > 8000:
            mode = 'A' if focus else 'D'
        elif energy < 6000:
            #mode = 'B' if focus else 'F'   ## mode B currently is inaccessible :(
            mode = 'C' if focus else 'F'
        else:
            mode = 'C' if focus else 'E'
        if xrd:
            mode   = 'XRD'
            focus  = True
            target = 0.0
        current_mode = get_mode()
        if mode in ('D', 'E', 'F') and current_mode in ('D', 'E', 'F'):
            with_m2 = False
        elif mode in ('A', 'B', 'C') and current_mode in ('A', 'B', 'C'): # no need to move M2
            with_m2 = False
        else:
            with_m2 = True
        if insist is True:
            with_m2 = True
        if all_connected(with_m2) is False:
            print(warning_msg('Ophyd connection failure' % el))
            yield from null()
            return

        ## trouble with MC06
        #slits = False

        
        ################################
        # confirm configuration change #
        ################################
        print(bold_msg('\nEnergy change:'))
        print('   %s: %s %s' % (list_msg('edge'),                    el.capitalize(), edge.capitalize()))
        print('   %s: %.1f'  % (list_msg('edge energy'),             energy))
        print('   %s: %.1f'  % (list_msg('target energy'),           energy+target))
        print('   %s: %s'    % (list_msg('focus'),                   str(focus)))
        print('   %s: %s'    % (list_msg('photon delivery mode'),    mode))
        print('   %s: %s'    % (list_msg('optimizing slits height'), str(slits)))

        ## prepare for the possibility of dcm_para stalling while moving to new energy
        if energy+target > dcm.energy.position:
            parity = -1
        else:
            parity = 1

        ## NEVER prompt when using queue server
        if is_re_worker_active() is True:
            BMMuser.prompt = False
        if BMMuser.prompt:
            action = input("\nBegin energy change? " + PROMPT)
            if action != '':
                if action[0].lower() == 'n' or action[0].lower() == 'q':
                    return(yield from null())
            if mode == 'C' and energy < 6000:
                print(warning_msg('\nMoving to mode C for focused beam and an edge energy below 6 keV.'))
                print(warning_msg("You will not get optimal harmonic rejection."))
                print(whisper("This message is informational, not indicative of a problem with your experiment."))
                #action = input("You will not get optimal harmonic rejection.  Continue anyway? " + PROMPT)
                #if action != '':
                #    if action[0].lower() == 'n' or action[0].lower() == 'q':
                #        return(yield from null())
        else:
            if el == rkvs.get('BMM:user:element').decode('utf-8') and edge == rkvs.get('BMM:user:edge').decode('utf-8'):
                print(warning_msg(f'You are already at the {el} {edge} edge.'))
                if insist is True:
                    print(warning_msg('But changing edge anyway.'))                
                else:
                    yield from null()
                    return

        # make sure edge is set sensibly in redis when XRD mode is entered
        if mode == 'XRD':
            if edge_energy(el,edge) > 23500:
                edge = 'L3'
        BMMuser.edge        = edge
        BMMuser.element     = el
        BMMuser.edge_energy = energy
        rkvs.set('BMM:pds:edge',        edge)
        rkvs.set('BMM:pds:element',     el)
        rkvs.set('BMM:pds:edge_energy', energy)


        start = time.time()
        if mode == 'XRD':
            report(f'Configuring beamline for XRD at {energy} eV', level='bold', slack=True)
        else:
            report(f'Configuring beamline for {el.capitalize()} {edge.capitalize()} edge', level='bold', slack=True, rid=True)
        yield from dcm.kill_plan()

        ################################################
        # change to the correct photon delivery mode   #
        #      + move mono to correct energy           #
        #      + move reference holder to correct slot #
        ################################################
        # if not calibrating and mode != current_mode:
        #     print('Moving to photon delivery mode %s...' % mode)
        if mode == 'XRD':
            yield from mv(slits3.hsize, 2)
        yield from mv(dcm_bragg.acceleration, BMMuser.acc_slow)
        yield from change_mode(mode=mode, prompt=False, edge=energy+target, reference=el, bender=bender, insist=insist)
        yield from mv(dcm_bragg.acceleration, BMMuser.acc_fast)

        ## verify that dcm_para has arrived in place.  if not, presume
        ## that it has stalled.  back off and try again to move
        dcm_axes = (user_ns["dcm_pitch"], user_ns["dcm_roll"], user_ns["dcm_perp"], user_ns["dcm_roll"], user_ns["dcm_bragg"])
        (bragg, para, perp) = dcm.motor_positions(energy+target, quiet=True)
        count = 0
        while abs(dcm_para.position - para) > 0.1:
            count = count+1
            report(':bangbang: dcm_para failed to arrive in position.  Attempting to resolve this problem. :bangbang: ', level='warning', slack=True)
            faulted_axes = False
            for m in dcm_axes:
                if m.amfe.get() or m.amfae.get():
                    #print(error_msg("%-12s : %s / %s" % (m.name, m.amfe.enum_strs[m.amfe.get()], m.amfae.enum_strs[m.amfae.get()])))
                    faulted_axes = True
            if faulted_axes is True:
                user_ns['ks'].cycle('dcm')
            yield from mvr(dcm_para, parity*5)
            yield from mv(dcm.energy, energy+target)
            if count > 5:
                report(':boom: dcm_para failed to arrive in position.  Unable to resolve this problem. :boom:', level='error', slack=True)
                raise FailedDCMParaException('dcm_para failed to arrive in position.  Unable to resolve this problem. (in BMM/edge.py)')
        if count > 0:
            report('Able to successfully resolve the stalling of dcm_para.  :sparkler:', slack=True)

        if arrived_in_mode(mode=mode) is False:
            print('\n')
            report(f'Failed to arrive in Mode {mode}', level='error', slack=True)
            print('Fixing this is often as simple as re-running the change_mode() command.')
            #print('Or try dm3_bct.kill_cmd() then dm3_bct.enable_cmd() then re-run the change_mode() command.')
            print('If that doesn\'t work, call for help')
            raise ArrivedInModeException(f'Failed to arrive in mode {mode}. (in BMM/edge.py)')
            #yield from null()
            #return

        yield from kill_mirror_jacks()
        yield from sleep(1)
        if BMMuser.motor_fault is not None:
            print('\n')
            report(f'\nSome motors are reporting amplifier faults: {BMMuser.motor_fault}', level='error', slack=True)
            print('Clear the faults and try running the same change_edge() command again.')
            print('Troubleshooting: ' + url_msg('https://nsls-ii-bmm.github.io/BeamlineManual/trouble.html#amplifier-fault'))
            BMMuser.motor_fault = None
            raise ArrivedInModeException(f'Failed to arrive in mode {mode} due to amplifier faults. (in BMM/edge.py)')
            #yield from null()
            #return
        BMMuser.motor_fault = None

        # if mode in ('A', 'C'):
        #     latpos = m2_lateral_position(energy+target)
        #     print(f'Moving M2 lateral to {latpos:.3f}')
        #     yield from mv(m2.lateral, latpos)

        ############################
        # run a rocking curve scan #
        ############################
        if tune:
            print('Optimizing rocking curve...')
            yield from mv(dcm_pitch.kill_cmd, 1)
            yield from mv(dcm_pitch, approximate_pitch(energy+target))
            yield from sleep(1)
            yield from mv(dcm_pitch.kill_cmd, 1)
            yield from sleep(1)
            yield from rocking_curve()
            close_last_plot()
            kafka_message({'close': 'last'})

        ##########################
        # run a slit height scan #
        ##########################
        if slits:
            print('Optimizing slits height...')
            if dm3_bct.amfe.get() or dm3_bct.amfae.get():
                user_ns['ks'].cycle('dm3')
            yield from slit_height(move=True)
            close_last_plot()
            kafka_message({'close': 'last'})
            ## redo rocking curve?

        ##################################
        # set reference and roi channels #
        ##################################
        #if not xrd:
        ## reference channel
        print('Moving reference foil...')
        yield from rois.select_plan(el)
        ## Xspress3
        if with_xspress3:
            BMMuser.verify_roi(xs, el, edge)
            BMMuser.verify_roi(xs1, el, edge)
        ## feedback
        show_edges()

        if mode == 'XRD':
            yield from mv(slits3.hsize, 7)
            report('Finished configuring for XRD', level='bold', slack=True)
        else:
            report(f'Finished configuring for {el.capitalize()} {edge.capitalize()} edge, now in photon delivery mode {get_mode()}', level='bold', slack=True)
        if slits is False:
            print('  * You may need to verify the slit position:  RE(slit_height())')

    def cleanup_plan():
        BMM_clear_suspenders()
        #yield from dcm.kill_plan()
        yield from mv(m2_bender.kill_cmd, 1)
        BMMuser.state_to_redis(filename=os.path.join(BMMuser.DATA, '.BMMuser'), prefix='')
        yield from resting_state_plan()
        end = time.time()
        print(f'\n\nThat took {(end-start)/60:.1f} min')

    
    user_ns['RE'].msg_hook = None
    start = time.time()
    m3, m2, m2_bender, dm3_bct = user_ns['m3'], user_ns['m2'], user_ns['m2_bender'], user_ns['dm3_bct']
    dcm_pitch, dcm_perp = user_ns["dcm_pitch"], user_ns["dcm_perp"]
    dcm_roll, dcm_bragg = user_ns["dcm_roll"], user_ns["dcm_bragg"]
    dm3_bct, slits3 = user_ns['dm3_bct'], user_ns['slits3']
    yield from finalize_wrapper(main_plan(el, focus, edge, energy, slits, tune, target, xrd, bender, insist),
                                cleanup_plan())
    user_ns['RE'].msg_hook = BMM_msg_hook
