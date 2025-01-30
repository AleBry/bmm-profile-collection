import os, time, datetime, psutil, glob
import inflection, textwrap, ansiwrap, termcolor
from numpy import pi, sin, cos, arcsin, sqrt

from BMM import user_ns as user_ns_module
user_ns = vars(user_ns_module)

import redis
from redis_json_dict import RedisJSONDict


## trying "most".  It's a pager, like less, but has helpful hints in
## the bottom gutter.  Let's see how it goes....
os.environ['PAGER'] = 'most'


## some global parameters
BMM_STAFF  = ('Bruce Ravel', 'Jean Jordan-Sweet', 'Joe Woicik', 'Vesna Stanic')
HBARC      = 1973.27053324
LUSTRE_XAS = os.path.join('/nsls2', 'data3', 'bmm', 'XAS')

LUSTRE_DATA_ROOT = os.path.join('/nsls2', 'data3', 'bmm', 'proposals')

PROMPT = f"[{termcolor.colored('yes', attrs=['underline'])}: y then Enter (or just Enter) ● {termcolor.colored('no', attrs=['underline'])}: n then Enter] "
PROMPTNC = "[YES: y then Enter (or just Enter) ● NO: n then Enter] "

try:
    from bluesky_queueserver import is_re_worker_active
except ImportError:
    # TODO: delete this when 'bluesky_queueserver' is distributed as part of collection environment
    def is_re_worker_active():
        return False


try:
    from terminaltexteffects.effects.effect_wipe import Wipe
    def animated_prompt(prompt_text: str) -> str:
        #if is_re_worker_active is False:
        effect = Wipe(prompt_text)
        with effect.terminal_output(end_symbol=" ") as terminal:
            for frame in effect:
                terminal.print(frame)
        return input()
        #else:
        #    ans = input(prompt_text).strip()
        #    return ans
except:
    ## fallback if terminaltexteffects is not installed
    def animated_prompt(prompt_text: str) -> str:
        ans = input(prompt_text).strip()
        return ans
    
def example_prompt(text='This is an example prompt.  Type something > '):
    foo = animated_prompt(text)
    print(f"You answered {foo}")
    

DEFAULT_INI = '/nsls2/data3/bmm/shared/config/xafs/scan.ini'

# Black, Blue, Brown, Cyan, DarkGray, Green, NoColor, Normal, Purple,
# Red, White, Yellow,

# LightBlue, LightCyan, LightGray, LightGreen, LightPurple, LightRed,

# BlinkBlack, BlinkBlue, BlinkCyan, BlinkGreen, BlinkLightGray,
# BlinkPurple, BlinkRed, BlinkYellow,

try:
    from bluesky_queueserver import is_re_worker_active
except ImportError:
    # TODO: delete this when 'bluesky_queueserver' is distributed as part of collection environment
    def is_re_worker_active():
        return False

def colored(text, tint='white', attrs=[]):
    '''
    A simple wrapper around IPython's interface to TermColors
    '''
    if not is_re_worker_active():
        from IPython.utils.coloransi import TermColors as color
        tint = tint.lower()
        if 'dark' in tint:
            tint = 'Dark' + tint[4:].capitalize()
        elif 'light' in tint:
            tint = 'Light' + tint[5:].capitalize()
        elif 'blink' in tint:
            tint = 'Blink' + tint[5:].capitalize()
        elif 'no' in tint:
            tint = 'Normal'
        else:
            tint = tint.capitalize()
        return '{0}{1}{2}'.format(getattr(color, tint), text, color.Normal)
    else:
        return(text)
        
def run_report(thisfile, text=None):
    '''
    Noisily proclaim to be importing a file of python code.
    '''
    add = '...'
    prepend = ''
    if text is not None:
        add = f'({text})'
        prepend = 'BMM/user_ns/'
    importing = 'Importing'
    if thisfile[0] == '\t':
        importing = '\t'
    print(colored(f'{importing} {prepend}{thisfile.split("/")[-1]} {add}', 'lightcyan'), flush=True)


def error_msg(text):
    '''Red text'''
    return colored(text, 'lightred')
def warning_msg(text):
    '''Yellow text'''
    return colored(text, 'yellow')
def go_msg(text):
    '''Green text'''
    return colored(text, 'lightgreen')
def url_msg(text):
    '''Undecorated text, intended for URL decoration...'''
    return colored(text, 'normal')
def bold_msg(text):
    '''Bright white text'''
    return colored(text, 'white')
def verbosebold_msg(text):
    '''Bright cyan text'''
    return colored(text, 'lightcyan')
def list_msg(text):
    '''Cyan text'''
    return colored(text, 'cyan')
def disconnected_msg(text):
    '''Purple text'''
    return colored(text, 'lightpurple')
def info_msg(text):
    '''Brown text'''
    return colored(text, 'brown')
def cold_msg(text):
    '''Light blue text'''
    return colored(text, 'lightblue')
def whisper(text):
    '''Light gray text'''
    return colored(text, 'darkgray')

##BMM_logfile = '/home/bravel/BMM_master.log'

KTOE = 3.8099819442818976
def etok(ee):
    '''convert relative energy to wavenumber'''
    return sqrt(ee/KTOE)
def ktoe(k):
    '''convert wavenumber to relative energy'''
    return k*k*KTOE

def e2l(val):
    """Convert absolute photon energy to photon wavelength"""
    return 2*pi*HBARC/val
l2e = e2l



## see calibrate_pitch in BMM/mono_calibration.py
def approximate_pitch(energy):
    '''Updated 12 September 2024
    '''
    if user_ns['dcm']._crystal == '111':
        m = -4.3490e-06
        b = 4.47073688
        return(m*energy + b)
    else:
        m = -3.0517e-06
        b = 2.38068447
        return(m*energy + b)
        

def isfloat(value):
    try:
        float(value)
        return True
    except ValueError:
        return False

def now(fmt="%Y-%m-%dT%H-%M-%S"):
    return datetime.datetime.now().strftime(fmt)

def inflect(word, number):
    if abs(number) == 1:
        return('%d %s' % (number, inflection.singularize(word)))
    else:
        return('%d %s' % (number, inflection.pluralize(word)))

def boxedtext(title, text, tint, width=75):
    '''
    Put text in a lovely unicode block element box.  The top
    of the box will contain a title.  The box elements will
    be colored.
    '''
    remainder = width - 2 - len(title)
    ul        = u'\u2554' # u'\u250C'
    ur        = u'\u2557' # u'\u2510'
    ll        = u'\u255A' # u'\u2514'
    lr        = u'\u255D' # u'\u2518'
    bar       = u'\u2550' # u'\u2500'
    strut     = u'\u2551' # u'\u2502'
    template  = '%-' + str(width) + 's'

    print('')
    print(colored(''.join([ul, bar*3, ' ', title, ' ', bar*remainder, ur]), tint))
    for line in text.split('\n'):
        lne = line.rstrip()
        add = ' '*(width-ansiwrap.ansilen(lne))
        print(' '.join([colored(strut, tint), lne, add, colored(strut, tint)]))
    print(colored(''.join([ll, bar*(width+3), lr]), tint))


def clear_dashboard():
    '''Clean up in a way that helps the cadashboard utility'''
    #from BMM.workspace import rkvs
    rkvs = user_ns['rkvs']
    rkvs.set('BMM:scan:type',      '')
    rkvs.set('BMM:scan:starttime', '')
    rkvs.set('BMM:scan:estimated', '')
    

def countdown(t):
    transition = max(int(t/10), 2)
    while t:
        mins, secs = divmod(t, 60)
        if t > transition:
            timeformat = bold_msg('{:02d}:{:02d}'.format(mins, secs))
        else:
            timeformat = warning_msg('{:02d}:{:02d}'.format(mins, secs))
        print(timeformat, end='\r')
        time.sleep(1)
        t -= 1
    print('Done!', end='\r')


def elapsed_time(start, slack=None):
    end = time.time()
    hours, rest = divmod(end-start, 3600)
    minutes, seconds = divmod(rest, 60)
    print(f'\n\nThat took {hours} hours, {minutes} minutes, {seconds:.0f} seconds')
    return(hours, minutes, seconds)
        

def present_options(suffix='xlsx'):
    options = [x for x in os.listdir(user_ns['BMMuser'].workspace) if x.endswith(suffix)]
    options = sorted(options)
    print(bold_msg(f'Looking in {user_ns["BMMuser"].workspace}\n'))
    
    print(f'Select your {suffix} file:\n')
    for i,x in enumerate(options):
        print(f' {i+1:2}: {x}')

    print('\n  r: return')
    choice = input("\nSelect a file > ")
    try:
        if int(choice) > 0 and int(choice) <= len(options):
            return options[int(choice)-1]
        else:
            return None
    except:
        return None

def plotting_mode(mode):
    '''Try to parse strings explaining the measurement mode.  Return one of:
         transmission
         fluorescence
         yield
         pilatus
         dante
         reference
         test
    
    '''
    mode = mode.lower()
    if 'yield' in mode: # ('fluo+yield', 'yield', 'eyield'):
        return 'yield'

    elif mode == 'iy':
        return 'yield'        

    elif 'pil' in mode: # ('fluo+pilatus', 'pilatus'):
        return 'pilatus'
    
    elif mode == 'dante':
        return 'dante'

    #elif user_ns['with_xspress3'] and any(x in mode for x in ('xs', 'fluo', 'flou', 'both')):
    elif any(x in mode for x in ('xs', 'fluo', 'flou', 'both')):
        return 'fluorescence'

    elif 'ref' in mode:
        return 'reference'

    elif mode == 'test':
        return 'test'

    else:
        return 'transmission'

    # deprecated textual distinction between various SDDs
    #elif user_ns['with_xspress3'] and mode == 'xs1':
    #    return 'xs1'
    
    # deprecated analog readout system
    #elif not user_ns['with_xspress3'] and any(x in mode for x in ('fluo', 'flou', 'both')):
    #    return 'fluo'
    
    #deprecated ion chamber testing
    #elif mode == 'icit':
    #    return 'icit'
    #elif mode == 'ici0':
    #    return 'ici0'


def examine_fmbo_motor_group(motor_group, TAB='\t\t\t\t'):
    CHECK = '\u2714'
    for m in motor_group:
        if 'SynAxis' in f'{m}':
            print(disconnected_msg(f'{TAB}{m.name} is not connected.'))
        elif m.name in ('dcm_y', 'm2_bender'):
            print(whisper(f'{TAB}{m.name} is normally run unhomed {CHECK}'))
        elif m.hocpl.get() == 1:
            print(f'{TAB}{m.name} {CHECK}')
        elif any(x in m.name for x in ('filter', 'fs', 'bpm', 'foils')):
            print(whisper(f'{TAB}{m.name} is not homed, but that\'s probably OK.'))
        else:
            print(error_msg(f'{TAB}{m.name} is not homed.'))

def examine_xafs_motor_group(motor_group, TAB='\t\t\t\t'):
    CHECK = '\u2714'
    for m in motor_group:
        if 'SynAxis' in f'{m}':
            print(disconnected_msg(f'{TAB}{m.name} is not connected.'))
        else:
            print(f'{TAB}{m.name} {CHECK}')


def not_at_edge(element, edge):
    '''Check to see if the beamline is currently configured for a
    specified element and edge, using Redis as the authority.

    This is a bit confusing, so an explanation:

    Return True if element & edge are /not/ the same as the values in
    Redis.  I.e. a change-edge command /is/ needed.

    Return False if element & edge are the same as the values in
    Redis.  I.e. a change_edge is /not/ needed.

    '''
    rkvs = user_ns['rkvs']
    if element != rkvs.get('BMM:user:element').decode('utf-8') or edge != rkvs.get('BMM:user:edge').decode('utf-8'):
        return True
    else:
        return False


def clean_img():
    '''Kill any outstanding "display" processes (i.e. ImageMagick's
    display).  Then remove any .PNG files PIL has left lying
    around in /tmp.  Finally, explicitly close the previous
    filehandle.

    This takes no care to verify neither that PIL launched the
    display process nor that PIL wrote the .PNG file in /tmp.

    Note that this will kill any other "display" processes
    running.  At NSLS-II, the centrally managed screen locker is
    configured to use feh to show a transparent png when the
    screen is locked.  Thus, display was chosen as the viewer
    rather than feh (although ownership would likely preclude
    terminating the screenlocker process).

    '''
    for proc in psutil.process_iter():
        if proc.name() == "display":
            proc.kill()
    for f in glob.glob('/tmp/tmp*.PNG'):
        try:
            os.remove(f)
        except:
            print(whisper(f'unable to delete {f} while cleaning up /tmp'))
    try:
        if BMMuser.display_img is not None:
            BMMuser.display_img.close()
    except:
        pass


def facility_md():
    redis_client = redis.Redis(host="info.bmm.nsls2.bnl.gov")
    the_dict = RedisJSONDict(redis_client=redis_client, prefix='xas-')
    return the_dict


def proposal_base():
    base = os.path.join('/nsls2', 'data3', 'bmm', 'proposals', user_ns['RE'].md['cycle'], user_ns['RE'].md['data_session'])
    return base

def slurp(folder, fname):
    'Slurp a text file into a string.'
    with open(os.path.join(folder,fname), 'r') as myfile:
        text=myfile.read()
    return text

def find_hdf5_files(folder=None):
    '''Crude search through XDI files for UIDs then through Tiled for HDF5 resources
    '''
    for fl in sorted(os.listdir(folder)):
        if re.search('\.\d+$', fl):
            text   = slurp(folder, fl)
            a      = re.search(r'uid: ([0-9a-f-]+)', text)
            uid    = a.group(1)
            hdf5file = file_resource(uid)
            print(f'{fl:35} ---> {os.path.basename(hdf5file)}')

# f = open(os.path.join(folder, 'mapping.txt'), "w")
# f.write(f'{fl:35} ---> {os.path.basename(hdf5file)}\n')
# f.close()

def bounds(base=0.5, coef=0.25, end='14k', edge=0.3):
    '''Generate strings that can be used in an XAS automation spreadsheet
    for k-weighted dwell times which are approximately continuous in
    dwell time at the transition into the k-weighted region.

    example
    =======
    > bounds(1/2,1/4)

    bounds = -200   -30   -2    15.2    25    14k
    steps  =     10    2     0.30  0.30   0.05k
    times  =     0.50  0.50  0.50  0.25k  0.25k


    arguments of the calculation
    ============================
    base (float) [0.5]
      The base integration time in seconds, usually 0.5 or 1 second.  The
      default is a half second -- that is, the dwell times leading up to the
      k-weighted region will be a half second.

    coef (float) [0.25]
      The coefficient of k to use for the k-weighted dwell times.  The
      default is a k coefficient of 1/4.


    non-calculation arguments
    =========================
    end (string of int or float) ['14k']
      The end value of the bounds list

    edge (float) [0.3]
      The step size through the end in eV.  The default is 0.3 eV.

    '''
    time = 1/coef
    transition = KTOE*(time*base)**2
    answer  = f'# base dwell time = {base:.2f} seconds, {coef:.2f}k weighting\n'
    answer += f'# transition energy = {transition:.1f} eV above the edge\n\n'
    if transition < 25:
        answer += f'bounds = -200   -30   -2    {transition:.1f}    25    {end}\n'
        answer += f'steps  =     10    2     {edge:.2f}  {edge:.2f}   0.05k\n'
    else:
        answer += f'bounds = -200   -30   -2    25    {transition:.1f}    {end}\n'
        answer += f'steps  =     10    2     {edge:.2f}  0.05k  0.05k\n'

    answer += f'times  =     {base:.2f}  {base:.2f}  {base:.2f}  {1/time:.2f}k  {1/time:.2f}k'

    print(answer)
