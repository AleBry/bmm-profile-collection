import os
from matplotlib import get_backend
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
#from mpl_multitab import MplTabs
import numpy, pandas
import xraylib
import datetime
from bluesky import __version__ as bluesky_version

from slack import img_to_slack
from tools import experiment_folder, echo_slack, file_resource, profile_configuration

from BMM.periodictable import Z_number, edge_number

#from nslsii.kafka_utils import _read_bluesky_kafka_config_file
#from bluesky_kafka.produce import BasicProducer
import pprint

import redis
bmm_redis = profile_configuration.get('services', 'bmm_redis')
rkvs = redis.Redis(host=bmm_redis, port=6379, db=0)



class LineScan():
    '''Manage the live plot for a motor scan or a time scan.

    Before yielding from the basic scan type, issue a kafka document
    indicating the start of the scan.  This document will look
    something like this:

      {'linescan' : 'start', ... }

    where the ... elides the various arguments used to construct the
    desired plot.

    Every time an event document from BlueSky is observed, call the
    add method, which will parse the event document, extract the
    latest data point, add it correctly to the data arrays, and redraw
    the plot.

    After the basic scan finishes, issue a kafka document indicating
    the end of the scan.  This document will look
    something like this:

      {'linescan' : 'end',}

    This is a single scan plot.  Over plotting of successive scans is
    not currently supported.

    This works for time scans as well as motor scans.  Those two scan
    types plot the same sorts of signals on the y-axis.  If the
    "motor" attribute is None, then a time scan (with time in seconds
    on the x-axis) will be displayed.

    attributes
    ==========
    ongoing (bool)
      a flag indicating whether a line or time scan is in progress

    xdata (list)
      a list containing all x-axis values measured thus far

    ydata (list)
      a list containing all y-axis values measured thus far

    motor (str)
      the name of the motor in motion or None for a time scan

    numerator (str)
      the name of the detector being plotted, something like io, it,
      ir, if, xs, xs1, xs4, xs7 ...

    denominator (str or int)
      the name of the signal used to normalize the numerator
      signal. for most plots, this would be "i0", for a plot of the
      reference detector, this would be 'it'. For an plot of a signal
      without a normalization signal (I0) for example, this should be
      1.

    figure (mpl figure object)
      this will hold the reference to the active figure object

    axes (mpl axis object)
      this will hold the reference to the active axis object

    line (mpl line object)
      this will hold the reference to the active line object

    description (str)
      a generated string used in the figure title

    xs1, xs2, xs3, xs4, xs5, xs6, xs7, xs8 (strs)
      strings identifying the names of the fluorescence ROIs for the
      current state of the photon delivery system.  these will be
      fetched from redis.

    plots (list)
      a list of the matplotlib figure objects still on screen

    initial (float)
      the time in epoch seconds of the first point of a time scan

    '''
    ongoing     = False
    xdata       = []
    ydata       = []
    motor       = None
    numerator   = None
    denominator = 1
    figure      = None
    axes        = None
    line        = None
    line2       = None
    line3       = None
    linetr      = None
    description = None
    xs1, xs2, xs3, xs4, xs5, xs6, xs7, xs8 = None, None, None, None, None, None, None, None
    plots       = []
    initial     = 0
    detector    = 7

    transmission_like = ('It', 'Transmission', 'Trans')
    fluorescence_like = ('If', 'Xs', 'Xs1', 'Fluorescence', 'Flourescence', 'Fluo', 'Flou', 'Dante')
    yield_like        = ('Iy', 'Yield')
    
    def start(self, **kwargs):
        #if self.figure is not None:
        #    plt.close(self.figure.number)
        self.ongoing = True
        self.xdata = []
        self.ydata = []
        self.y2data = []
        self.y3data = []
        self.trdata = []
        if 'motor' in kwargs: self.motor = kwargs['motor']
        self.numerator = kwargs['detector'].capitalize()
        self.denominator = None
        self.figure = plt.figure()
        if self.motor is not None:
            cid = self.figure.canvas.mpl_connect('button_press_event', self.interpret_click)
            #cid = BMMuser.fig.canvas.mpl_disconnect(cid)
        try:
            self.stack = kwargs['stack']
        except:
            self.stack = False
        self.plots.append(self.figure.number)
        if self.numerator not in self.fluorescence_like or self.stack is False:
            self.axes = self.figure.add_subplot(111)
            self.axes.set_facecolor((0.95, 0.95, 0.95))
            self.line, = self.axes.plot([],[])
        self.initial = 0
        self.fluo_detector = ''
        if 'fluo_detector' in kwargs:
            self.fluo_detector = kwargs['fluo_detector']

        self.detector = rkvs.get('BMM:xspress3').decode('utf-8')
        if self.detector == '1' and self.numerator in self.fluorescence_like:
            self.numerator = 'Xs1'
        
        self.xs1 = rkvs.get('BMM:user:xs1').decode('utf-8')
        self.xs2 = rkvs.get('BMM:user:xs2').decode('utf-8')
        self.xs3 = rkvs.get('BMM:user:xs3').decode('utf-8')
        self.xs4 = rkvs.get('BMM:user:xs4').decode('utf-8')
        self.xs5 = rkvs.get('BMM:user:xs5').decode('utf-8')
        self.xs6 = rkvs.get('BMM:user:xs6').decode('utf-8')
        self.xs7 = rkvs.get('BMM:user:xs7').decode('utf-8')
        self.xs8 = rkvs.get('BMM:user:xs8').decode('utf-8')


        ## todo:  bicron, new ion chambers, both
        
        ## transmission: plot It/I0
        if self.numerator in self.transmission_like:
            self.numerator = 'It'
            self.description = 'transmission'
            self.denominator = 'I0'
            self.axes.set_ylabel(f'{self.numerator}/{self.denominator}')

        ## I0: plot just I0
        elif self.numerator == 'I0':
            self.description = 'I0'
            self.denominator = None
            self.axes.set_ylabel(self.numerator)

        ## reference: plot just Ir
        elif self.numerator == 'Ir':
            self.description = 'reference'
            self.denominator = None
            self.axes.set_ylabel(self.numerator)

        ## yield: plot Iy/I0
        elif self.numerator == 'Iy':
            self.description = 'yield'
            self.denominator = 'I0'
            self.axes.set_ylabel(f'{self.numerator}/{self.denominator}')

        elif self.numerator == 'Eiger':
            self.line.set_label('specular (ROI3)')
            self.line2, = self.axes.plot([],[], label='diffuse (ROI2)')
            self.description = 'specular (ROI3)'
            self.denominator = None
            self.axes.set_ylabel(self.numerator)
            self.axes.legend(loc='best', shadow=True)
            
        ## split ion chamber
        elif self.numerator == 'Ic1':
            self.line.set_label('Ita')
            self.line2, = self.axes.plot([],[], label='Itb')
            self.description = 'split ion chamber (channel A)'
            self.denominator = 'I0'
            self.axes.set_ylabel(f'Ita/{self.denominator}')
            self.axes.legend(loc='best', shadow=True)

        elif self.stack is False and self.numerator in self.fluorescence_like:
            self.description = 'fluorescence (SDD)'
            self.denominator = 'I0'
            self.axes.set_ylabel('fluorescence / I0')
            

        ## fluorescence (4 channel): plot sum(If)/I0
        ##xs1, xs2, xs3, xs4 = rkvs.get('BMM:user:xs1'), rkvs.get('BMM:user:xs2'), rkvs.get('BMM:user:xs3'), rkvs.get('BMM:user:xs4')
        elif self.stack is True and self.numerator in self.fluorescence_like:

            if get_backend().lower() == 'agg':
                self.figure.set_figheight(9.5)
                self.figure.set_figwidth(5.5)
            else:
                self.figure.canvas.manager.window.setGeometry(2240, 1887, 600, 963)
            self.gs = gridspec.GridSpec(2,1)
            self.fl = self.figure.add_subplot(self.gs[0, 0])
            self.fl.grid(which='major', axis='both')
            self.fl.set_facecolor((0.95, 0.95, 0.95))
            self.fl.set_ylabel('fluorescence (SDD)')

            self.tr = self.figure.add_subplot(self.gs[1, 0])
            self.tr.grid(which='major', axis='both')
            self.tr.set_facecolor((0.95, 0.95, 0.95))
            self.tr.set_ylabel('transmission')

            if self.fluo_detector == '1-element SDD':
                self.line, = self.fl.plot([],[])
                self.line.set_label(rkvs.get('BMM:user:xs8').decode('utf-8'))
                self.line2  = self.fl.plot([],[], label='K8')
                self.line3  = self.fl.plot([],[], label='OCR')
                self.linetr, = self.tr.plot([],[], label='trans')
                self.numerator = 'If'
                self.description = 'fluorescence (1 channel)'
                self.denominator = 'I0'
                self.fl.set_ylabel('fluorescence (1 channel)')
            else:
                self.line, = self.fl.plot([],[], label='fluorescence')
                self.linetr, = self.tr.plot([],[], label='transmission', color='tab:orange')
                self.numerator = 'If'
                self.description = 'fluorescence (SDD)'
                self.denominator = 'I0'
            if self.fluo_detector == 'Dante':  # delete me once testing is finished!
                self.denominator = None
            self.fl.legend(loc='best', shadow=True)
            self.tr.legend(loc='best', shadow=True)
                

        ## fluorescence (1 channel): plot If/I0
        ##xs8 = rkvs.get('BMM:user:xs8').decode('utf-8')
        #elif self.numerator == 'Xs1':
            
        if self.numerator in self.fluorescence_like:
            if 'motor' in kwargs:
                if self.stack is True:
                    self.fl.set_xlabel(self.motor)
                    self.tr.set_xlabel(self.motor)
                else:
                    self.axes.set_xlabel(self.motor)
                self.figure.suptitle(f'{self.motor} alignment scan')
            else:
                if self.stack is True:
                    self.fl.set_xlabel('time (seconds)')
                    self.tr.set_xlabel('time (seconds)')
                else:
                    self.axes.set_xlabel(self.motor)
                self.figure.suptitle('time scan')
        else:
            if 'motor' in kwargs:
                self.axes.set_xlabel(self.motor)
                self.axes.set_title(f'{self.motor} alignment scan')
            else:                   # this is a time scan
                self.axes.set_xlabel('time (seconds)')
                self.axes.set_title('time scan')

    def interpret_click(self, ev):
        '''Grab location of mouse click.  Identify motor by grabbing the
        x-axis label from the canvas clicked upon.

        Stash those in Redis.
        '''
        x,y = ev.xdata, ev.ydata
        print('plucked', x, ev.canvas.figure.axes[0].get_xlabel(), ev.canvas.figure.number)
        if x is not None:
            rkvs.set('BMM:mouse_event:value', x)
            rkvs.set('BMM:mouse_event:motor', ev.canvas.figure.axes[0].get_xlabel())
        

        
        # kafka_config = _read_bluesky_kafka_config_file(config_file_path="/etc/bluesky/kafka.yml")
        # producer = BasicProducer(bootstrap_servers=kafka_config['bootstrap_servers'],
        #                          topic='bmm.test',
        #                          producer_config=kafka_config["runengine_producer_config"],
        #                          key='abcdef')
        # document = {'mpl_event' : 'mouse_click',
        #             'motor' : self.motor,
        #             'position' : ev.xdata, }
        # pprint.pprint(documemnt)
        # producer.produce(['bmm', document])

        
    def stop(self, catalog, **kwargs):
        if get_backend().lower() == 'agg':
            if 'fname' in kwargs and 'uid' in kwargs:
                fname = os.path.join(experiment_folder(catalog, kwargs["uid"]), 'snapshots', kwargs["fname"])
                self.figure.savefig(fname)
                self.logger.info(f'saved linescan figure {fname}')
                img_to_slack(fname, title=f'{self.description} vs. {self.motor}', measurement='line')

        #self.figure.show(block=False)
        self.ongoing     = False
        self.xdata       = []
        self.ydata       = []
        self.y2data      = []
        self.trdata      = []
        self.motor       = None
        self.numerator   = None
        self.denominator = 1
        self.figure      = None
        self.axes        = None
        self.line        = None
        self.line2       = None
        self.line3       = None
        self.description = None
        self.xs1, self.xs2, self.xs3, self.xs4, self.xs8 = None, None, None, None, None
        self.initial     = 0

    # this helped: https://techoverflow.net/2021/08/20/how-to-autoscale-matplotlib-xy-axis-after-set_data-call/
    def add(self, **kwargs):

        if 'dcm_roll' in kwargs['data']:
            return              # this is a baseline event document, dcm_roll is almost never scanned

        
        if self.numerator in self.fluorescence_like:
            if self.fluo_detector == '1-element SDD':
                signal = kwargs['data'][self.xs8]
            elif self.fluo_detector == '4-element SDD':
                signal = (kwargs['data'][self.xs1] +
                          kwargs['data'][self.xs2] +
                          kwargs['data'][self.xs3] +
                          kwargs['data'][self.xs4])
            elif self.fluo_detector == 'Dante':
                signal = (kwargs['data'][self.xs1] +
                          kwargs['data'][self.xs2] +
                          kwargs['data'][self.xs3] +
                          kwargs['data'][self.xs4] + 
                          kwargs['data'][self.xs5] +
                          kwargs['data'][self.xs6] +
                          kwargs['data'][self.xs7])
            else:
                signal = (kwargs['data'][self.xs1] +
                          kwargs['data'][self.xs2] +
                          kwargs['data'][self.xs3] +
                          kwargs['data'][self.xs4] + 
                          kwargs['data'][self.xs5] +
                          kwargs['data'][self.xs6] +
                          kwargs['data'][self.xs7])
            
            # if self.xs1 in kwargs['data']:  # this is a primary documemnt
            #     signal = kwargs['data'][self.xs1] + kwargs['data'][self.xs2] + kwargs['data'][self.xs3] + kwargs['data'][self.xs4]
            #     if numpy.isnan(signal):
            #         signal = 0
            #     #signal2 = kwargs['data']['La1'] + kwargs['data']['La2'] + kwargs['data']['La3'] + kwargs['data']['La4']
            # else:                           # this is a baseline document
            #     return
            # elif self.numerator == 'Ic0':
            #     signal  = kwargs['data']['I0a']
            #     signal2 = kwargs['data']['I0b']
            # elif self.numerator == 'Ic1':
            #     signal  = kwargs['data']['Ita']
            #     signal2 = kwargs['data']['Itb']
            # elif self.numerator == 'Xs1':
            #     signal  = kwargs['data'][self.xs8]
            #     signal2 = kwargs['data']['K8']
            #     signal3 = kwargs['data']['OCR']
        elif self.numerator == 'Eiger':
            signal  = kwargs['data']['specular']
            signal2 = kwargs['data']['diffuse']
    
        elif self.numerator in kwargs['data']:  # numerator will not be in baseline document
            signal = kwargs['data'][self.numerator]
        else:
            print(f'could not determine signal, self.numerator is {self.numerator}')
            return
            
        if self.motor is None:   # this is a time scan
            if kwargs['seq_num'] == 1:
                self.initial = kwargs['time']
            self.xdata.append(kwargs['time'] - self.initial)
        else:
            self.xdata.append(kwargs['data'][self.motor])

        if self.denominator is None:
            self.ydata.append(signal)
            #if self.numerator == 'Ic0' or self.numerator == 'Xs1':
            if self.fluo_detector is not None:
                self.trdata.append(kwargs['data']['It'])
            if self.fluo_detector == '1-element SDD':
                self.y2data.append(signal2)
                self.y3data.append(signal3)
            if self.numerator == 'Eiger':
                self.y2data.append(signal2)
                
            # self.ydata.append(signal)
            # #if self.numerator == 'Ic0' or self.numerator == 'Xs1':
            # if self.numerator in ('Xs1', 'Xs', 'If'):  # 'Ic0q', 'Ic1'
            #     self.y2data.append(signal2)
            # if self.numerator == 'Xs1':
            #     self.y3data.append(signal3)
        else:
            self.ydata.append(signal/kwargs['data'][self.denominator])
            #if self.numerator == 'Ic0' or self.numerator == 'Xs1':
            if self.fluo_detector is not None and self.stack is True:
                self.trdata.append(kwargs['data']['It']/kwargs['data']['I0'])
            if self.fluo_detector == '1-element SDD':
                self.y2data.append(signal2/kwargs['data'][self.denominator])
                self.y3data.append(signal3/kwargs['data'][self.denominator])
        self.line.set_data(self.xdata, self.ydata)
        if self.numerator == 'Eiger':
            self.line2.set_data(self.xdata, self.y2data)
        if self.fluo_detector == '1-element SDD':
            self.line2.set_data(self.xdata, self.y2data)
            self.line3.set_data(self.xdata, self.y3data)
        if self.fluo_detector is not None and self.stack is True:
            self.linetr.set_data(self.xdata, self.trdata)
            self.fl.relim()
            self.fl.autoscale_view(True,True,True)
            self.tr.relim()
            self.tr.autoscale_view(True,True,True)
        else:
            self.axes.relim()
            self.axes.autoscale_view(True,True,True)


        #self.figure.show()      # in case the user has closed the window
        self.figure.canvas.draw()
        self.figure.canvas.flush_events()

    def close_all_lineplots(self):
        for i in self.plots:
            plt.close(i)
            


class XAFSScan():
    '''Plot a grid of views of the data streaming from an XAFS scan.

    Care is taken to maintain references to the matplotlib objects in
    each grid panel of the plot.

    In the event of an ion-chamber-only scan (transmission, reference, test) show a 3x1 grid:

    +----------+----------+----------+
    |          |          |          |
    |   mu(E)  |   I0     |  ref(E)  |
    |          |          |          |
    +----------+----------+----------+

    In the event of a scan with fluorescence, show a 2x2 grid:

    +----------+----------+
    |          |          |
    | trans(E) | fluo(E)  |
    |          |          |
    +----------+----------+
    |          |          |
    |    I0    | ref(E)   |
    |          |          |
    +----------+----------+

    In the event of a scan with electron yield and fluorescence, show a 3x2 grid:

    +----------+----------+----------+
    |          |          |          |
    | trans(E) | fluo(E)  |   I0     |
    |          |          |          |
    +----------+----------+----------+
    |          |          |          |
    |  ref(e)  | yield(E) |          |
    |          |          |          |
    +----------+----------+----------+

    In the event of a reflectivity scan with Pilatus/Eiger and fluorescence, show a 2x2 grid:

    +----------+----------+
    |          |          |
    | fluo(E)  |   I0     |
    |          |          |
    +----------+----------+
    |          |          |
    | diffuse  | specular |
    |          |          |
    +----------+----------+

    '''

    ongoing     = False
    energy      = []
    i0sig       = []
    iysig       = []
    trans       = []
    fluor       = []
    refer       = []
    xs1, xs2, xs3, xs4, xs5, xs6, xs7, xs8 = None, None, None, None, None, None, None, None
    mode        = None
    filename    = None
    repn        = 0
    reference_material = None
    sample      = None
    fluo_detector = None

    fig, gs = None, None
    mut, line_mut = None, None
    muf, line_muf = None, None
    i0 , line_i0  = None, None
    ref, line_ref = None, None
    iy , line_iy  = None, None
    axis_list = []

    transmission_like = ('It', 'Transmission', 'Trans')
    fluorescence_like = ('Both', 'If', 'Xs', 'Xs1', 'Fluorescence', 'Flourescence', 'Fluo', 'Flou', 'Dante')
    yield_like        = ('Iy', 'Yield')

    
    def start(self, **kwargs):
        '''Begin a sequence of XAFS live plots.
        '''
        self.ongoing     = True
        self.energy      = []
        self.i0sig       = []
        self.trans       = []
        self.fluor       = []
        self.refer       = []
        self.iysig       = []
        self.mode        = kwargs['mode']
        self.filename    = kwargs['filename']
        self.repetitions = kwargs['repetitions']
        self.count       = 1
        self.sample      = kwargs['sample']
        self.fluo_detector = kwargs['fluo_detector']
        self.reference_material = kwargs['reference_material']
        
        ## close the plot from the last sequence
        if self.fig is not None:
            plt.close(self.fig.number)
        plt.rcParams["figure.raise_window"] = True
        self.fig = plt.figure(num='XAFS live view', tight_layout=True)
        plt.rcParams["figure.raise_window"] = False

        ## a nod at backwards compatibility, regularize mode, as of Jan 30 2025 mode should be regularized
        if self.mode in ('both', 'fluorescence', 'fluo', 'flourescence', 'flour', 'xs', 'xs1', 'xs4', 'xs7'):
            self.mode = 'fluorescence'
        if self.mode in ('yield', 'eyield', 'fluo+yield'):
            self.mode = 'yield'
        if self.mode in ('fluo+pilatus',):
            self.mode = 'pilatus'

        self.xs1 = rkvs.get('BMM:user:xs1').decode('utf-8')
        self.xs2 = rkvs.get('BMM:user:xs2').decode('utf-8')
        self.xs3 = rkvs.get('BMM:user:xs3').decode('utf-8')
        self.xs4 = rkvs.get('BMM:user:xs4').decode('utf-8')
        self.xs5 = rkvs.get('BMM:user:xs5').decode('utf-8')
        self.xs6 = rkvs.get('BMM:user:xs6').decode('utf-8')
        self.xs7 = rkvs.get('BMM:user:xs7').decode('utf-8')
        self.xs8 = rkvs.get('BMM:user:xs8').decode('utf-8')

            
        ## 2x2 grid if fluorescence
        if self.mode in ('fluorescence', 'dante'):
            if get_backend().lower() == 'agg':
                self.fig.set_figheight(9.5)
                self.fig.set_figwidth(11)
            else:
                self.fig.canvas.manager.window.setGeometry(2240, 1757, 1200, 1093)
            self.gs = gridspec.GridSpec(2,2)
            self.mut = self.fig.add_subplot(self.gs[0, 0])
            self.muf = self.fig.add_subplot(self.gs[0, 1])
            self.i0  = self.fig.add_subplot(self.gs[1, 0])
            self.ref = self.fig.add_subplot(self.gs[1, 1])
            self.axis_list   = [self.mut, self.muf, self.i0, self.ref]

        ## 3x2 grid for yield
        elif self.mode == 'yield':
            if get_backend().lower() == 'agg':
                self.fig.set_figheight(9.5)
                self.fig.set_figwidth(15)
            else:
                self.fig.canvas.manager.window.setGeometry(1800, 1726, 1600, 1093)
            self.gs = gridspec.GridSpec(2,3)
            self.mut = self.fig.add_subplot(self.gs[0, 0])
            self.muf = self.fig.add_subplot(self.gs[0, 1])
            self.i0  = self.fig.add_subplot(self.gs[0, 2])
            self.ref = self.fig.add_subplot(self.gs[1, 0])
            self.iy  = self.fig.add_subplot(self.gs[1, 1])
            self.axis_list   = [self.mut, self.muf, self.i0, self.ref, self.iy]
            
        ## 2x2 grid if pilatus or eiger
        elif self.mode in ('pilatus', 'eiger'):
            if get_backend().lower() == 'agg':
                self.fig.set_figheight(9.5)
                self.fig.set_figwidth(6.5)
            else:
                self.fig.canvas.manager.window.setGeometry(2240, 1757, 1200, 1093)
            self.gs = gridspec.GridSpec(2,2)
            self.muf = self.fig.add_subplot(self.gs[0, 0])
            self.i0  = self.fig.add_subplot(self.gs[0, 1])
            self.ref = self.fig.add_subplot(self.gs[1, 0])
            self.iy  = self.fig.add_subplot(self.gs[1, 1])
            self.axis_list   = [self.muf, self.i0, self.ref, self.iy]

        ## 3x1 grid if no fluorescence (transmission, reference, test)
        else:
            if get_backend().lower() == 'agg':
                self.fig.set_figwidth(16.5)
            else:
                self.fig.canvas.manager.window.setGeometry(1640, 2259, 1800, 624)
            self.gs = gridspec.GridSpec(1,3)
            self.mut = self.fig.add_subplot(self.gs[0, 0])
            self.i0  = self.fig.add_subplot(self.gs[0, 1])
            self.ref = self.fig.add_subplot(self.gs[0, 2])
            self.axis_list   = [self.mut, self.i0, self.ref]
        self.fig.suptitle(f'{self.filename}: scan {self.count} of {self.repetitions}')


        ## start lines and set axis labels

        ## every plot type uses mu_t and i0
        if self.mode not in ('pilatus', 'eiger'):
            self.mut.set_ylabel('transmission $\mu(E)$')
            self.mut.set_xlabel('energy (eV)')
            self.mut.set_title(f'data: {self.sample}')

        self.i0.set_ylabel('I0 (nanoamps)')
        self.i0.set_xlabel('energy (eV)')
        self.i0.set_title('I0')

        ## all plot types except transmission and reference need mu_f
        if self.mode in ('fluorescence', 'yield', 'pilatus', 'eiger', 'dante'):
            self.muf.set_ylabel(f'fluorescence $\mu(E)$  ({self.fluo_detector})')
            self.muf.set_xlabel('energy (eV)')
            self.muf.set_title(f'data: {self.sample}')

        ## all plot types except pilatus/eiger need reference
        if self.mode in ('transmission', 'fluorescence', 'yield', 'dante', 'reference'):
            self.ref.set_ylabel('reference $\mu(E)$')
            self.ref.set_xlabel('energy (eV)')
            self.ref.set_title(f'reference: {self.reference_material}')
        elif self.mode in ('pilatus', 'eiger'):  # pilatus/eiger plot re-purposes ref for diffuse
            self.ref.set_ylabel('diffuse intensity')
            self.ref.set_xlabel('energy (eV)')
            self.ref.set_title('diffuse scattering')
            

        ## yield needs the iy signal
        if self.mode == 'yield':
            self.iy.set_ylabel('electron yield $\mu(E)$')
            self.iy.set_xlabel('energy (eV)')
            self.iy.set_title('electron yield')
        elif self.mode in ('pilatus', 'eiger'):  # pilatus plot re-purposes iy for specular
            self.iy.set_ylabel('specular intensity')
            self.iy.set_xlabel('energy (eV)')
            self.iy.set_title('specular scattering')
            
        ## common appearance
        for ax in self.axis_list:
            ax.grid(which='major', axis='both')
            ax.set_facecolor((0.95, 0.95, 0.95))

        

            
    def Next(self, **kwargs):
        '''Initialize data arrays and plotting lines for next scan.
        '''
        self.count = kwargs['count']
        self.fig.suptitle(f'{self.filename}: scan {self.count} of {self.repetitions}')
        self.energy      = []
        self.i0sig       = []
        self.trans       = []
        self.fluor       = []
        self.refer       = []
        self.iysig       = []
        if self.mode not in ('pilatus', 'eiger'):
            self.line_mut,   = self.mut.plot([],[], label=f'scan {self.count}')
        self.line_i0,    = self.i0.plot([],[],  label=f'scan {self.count}')
        self.line_ref,   = self.ref.plot([],[], label=f'scan {self.count}')
        if self.mode in ('fluorescence', 'yield', 'pilatus', 'dante'):
            self.line_muf, = self.muf.plot([],[], label=f'scan {self.count}')
        if self.mode in ('yield', 'pilatus', 'eiger'):
            self.line_iy,  = self.iy.plot([],[], label=f'scan {self.count}')
        for ax in self.axis_list:
            if self.count < 10:
                ax.legend(loc='best', shadow=True)
            else:
                ax.legend.remove()
            
    def stop(self, catalog, **kwargs):
        '''Done with a sequence of XAFS live plots.
        '''
        filename = kwargs['filename']
        #self.figure.show(block=False)
        self.ongoing     = False
        # self.xdata       = []
        # self.ydata       = []
        # self.motor       = None
        # self.numerator   = None
        # self.denominator = 1
        # self.figure      = None
        # self.axes        = None
        # self.line        = None
        # self.description = None
        # self.xs1, self.xs2, self.xs3, self.xs4, xs8 = None, None, None, None, None
        # self.initial     = 0
        if get_backend().lower() == 'agg':
            if filename is not None:
                uid = kwargs['uid']
                ## dossier should have already been written, thus the
                ## sequence number (i.e. the number of times a
                ## sequence of repetitions using the same file) should
                ## already be known.  This will align the sequence
                ## numbering of the live plot and triplot images with
                ## the sequence numbering of the dossier itself
                seqnumber = rkvs.get('BMM:dossier:seqnumber').decode('utf-8')
                if seqnumber is not None:
                    try:
                        filename = filename.replace('.png', f'_{int(seqnumber):02d}.png')
                    except:
                        filename = filename.replace('.png', '_01.png')
                    fname = os.path.join(experiment_folder(catalog, uid), filename)
                self.fig.savefig(fname)
                self.logger.info(f'saved XAFS sequence figure {fname}')
                img_to_slack(fname, title=self.sample, measurement='xafs')
            


    def add(self, **kwargs):
        '''Add the most recent event to the current XAFS live plot.
        '''
        if 'dcm_energy' not in kwargs['data']:
            return              # this is a baseline event document

        ## primary event document, append to data arrays
        self.energy.append(kwargs['data']['dcm_energy'])
        self.i0sig.append(kwargs['data']['I0']/kwargs['data']['dwti_dwell_time'])  # this should be the same number as cadashboard....
        self.trans.append(numpy.log(abs(kwargs['data']['I0']/kwargs['data']['It'])))
        ## push the updated data arrays to the various lines
        self.line_i0.set_data(self.energy, self.i0sig)
        if self.mode not in ('pilatus', 'eiger'):
            self.line_mut.set_data(self.energy, self.trans)


        if self.mode in ('transmission', 'fluorescence', 'yield', 'dante', 'reference'):
            self.refer.append(numpy.log(abs(kwargs['data']['It']/kwargs['data']['Ir'])))
            
        if self.mode in ('pilatus', 'eiger'):  # re-purpose refer and iysig
            self.refer.append(kwargs['data']['diffuse']/kwargs['data']['I0'])
            self.iysig.append(kwargs['data']['specular']/kwargs['data']['I0'])
            self.line_iy.set_data(self.energy, self.iysig)

        if self.mode == 'yield':
            self.iysig.append(kwargs['data']['Iy']/kwargs['data']['I0'])
            self.line_iy.set_data(self.energy, self.iysig)

        
        self.line_ref.set_data(self.energy, self.refer)
        

        ## and do all that for the fluorescence spectrum if it is being plotted.
        if self.mode in ('fluorescence', 'yield', 'pilatus', 'eiger', 'dante'):
            if self.fluo_detector == '1-element SDD':
                self.fluor.append( kwargs['data'][self.xs8] / kwargs['data']['I0'] )
            elif self.fluo_detector == '4-element SDD':
                self.fluor.append( (kwargs['data'][self.xs1] +
                                    kwargs['data'][self.xs2] +
                                    kwargs['data'][self.xs3] +
                                    kwargs['data'][self.xs4]   ) / kwargs['data']['I0'])
            elif self.fluo_detector == 'dante':
                self.fluor.append( (kwargs['data'][self.xs1] +
                                    kwargs['data'][self.xs2] +
                                    kwargs['data'][self.xs3] +
                                    kwargs['data'][self.xs4] +
                                    kwargs['data'][self.xs5] +
                                    kwargs['data'][self.xs6] +
                                    kwargs['data'][self.xs7]   ) / kwargs['data']['I0'])
            else:               # 7-element SDD
                self.fluor.append( (kwargs['data'][self.xs1] +
                                    kwargs['data'][self.xs2] +
                                    kwargs['data'][self.xs3] +
                                    kwargs['data'][self.xs4] +
                                    kwargs['data'][self.xs5] +
                                    kwargs['data'][self.xs6] +
                                    kwargs['data'][self.xs7]   ) / kwargs['data']['I0'])
            self.line_muf.set_data(self.energy, self.fluor)
        #if self.mode in ('eyield'):
        #    self.fluor.append( kwargs['data']['Iy'] / kwargs['data']['I0'] )
        #    self.line_muf.set_data(self.energy, self.fluor)

        ## rescale everything
        for ax in self.axis_list:
            ax.relim()
            ax.autoscale_view(True,True,True)
        #self.fig.show()         # in case the user has closed the window
        ## redraw and flush the canvas 
        ## Tom's explanation for how to do multiple plots: https://stackoverflow.com/a/31686953
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()
        
            

class XRF():
    '''Manage the plotting of an XRF spectrum

    This:

         uid = RE(count([xs], 1))
         kafka_message({'xrf': True, 'uid': uid})

    will plot an XRF spectrum to screen.

    parameters
    ==========
    xrf : 'plot'
      flag to Kafka consumer that an XRF spectrum is to be plotted
    uid : str
      UID string from the XRF measurement
    add : bool
      True to add the sum of channels, false to overplot all channels
    only : int
      Channel number to plot
    filename : str
      fully resolved path and filename for output PNG image
    post : bool
      True means to post the saved image file to Slack

    '''

    def plot(self, catalog, **kwargs):
        uid=None
        add=True
        only=None
        filename = None
        post = False

        uid  = kwargs['uid']
        if 'add'      in kwargs: add      = kwargs['add']
        if 'only'     in kwargs: only     = kwargs['only']
        if 'filename' in kwargs: filename = kwargs['filename']
        if 'post'     in kwargs: post     = kwargs['post']

        self.title = ''
        self.figure = plt.figure()
        self.axes = self.figure.add_subplot(111)
        self.axes.set_facecolor((0.95, 0.95, 0.95))
        self.axes.set_xlabel('Energy (eV)')
        title = 'counts'
        if 'XDI' in catalog[uid].metadata['start']:
            if 'Sample' in catalog[uid].metadata['start']['XDI'] and 'name' in catalog[uid].metadata['start']['XDI']['Sample']:
                self.title = catalog[uid].metadata['start']['XDI']['Sample']['name']
        self.axes.set_title(self.title)
        self.axes.grid(which='major', axis='both')
        
        s = []
        nelem = 4
        channels = tuple(range(1, 5))
        if '1-element SDD' in catalog[uid].metadata['start']['detectors']:
            nelem = 1
            channels = (1, )
            only = 1
        elif '7-element SDD' in catalog[uid].metadata['start']['detectors']:
            nelem = 7
            channels = tuple(range(0, 7))
        elif 'dante-1' in catalog[uid].metadata['start']['detectors']:
            nelem = 7
            channels = tuple(range(1, 8))

            
        if nelem == 1:
            s.append(catalog[uid].primary.data['1-element SDD_channel08_xrf'][0])  #  note channel number!
            only = 1
            add = False
        elif 'dante-1' in catalog[uid].metadata['start']['detectors']:
            for i in channels:
                s.append(catalog[uid].primary.data[f'dante-1_image'][0][0][i-1])
        else:
            for i in channels:
                s.append(catalog[uid].primary.data[f'{nelem}-element SDD_channel0{i+1}_xrf'][0])


        e = numpy.arange(0, len(s[0])) * 10

        if only is not None and only in channels:
            plt.plot(e, s[only-1], label=f'channel {only}')
        elif add is True and nelem > 1:
            ss = numpy.zeros((len(s[0])))
            for i in channels:
                ss = ss + s[i-1]
            plt.plot(e, ss, label=f'sum of {nelem} channels')
        else:
            for i in channels:
                plt.plot(e, s[i-1], label=f'channel {i}')

        if 'XDI' in catalog[uid].metadata['start']:
            if 'Element' in catalog[uid].metadata['start']['XDI']:
                if 'symbol' in catalog[uid].metadata['start']['XDI']['Element'] and 'edge' in catalog[uid].metadata['start']['XDI']['Element']:
                    el = catalog[uid].metadata['start']['XDI']['Element']['symbol']
                    ed = catalog[uid].metadata['start']['XDI']['Element']['edge']
                    z = Z_number(el)
                    if ed.lower() == 'k':
                        label = f'{el} Kα1'
                        eline = (2*xraylib.LineEnergy(z, xraylib.KL3_LINE) + xraylib.LineEnergy(z, xraylib.KL2_LINE))*1000/3
                    elif ed.lower() == 'l3':
                        label = f'{el} Lα1'
                        eline = xraylib.LineEnergy(z, xraylib.L3M5_LINE)*1000
                    elif ed.lower() == 'l2':
                        label = f'{el} Kβ1'
                        eline = xraylib.LineEnergy(z, xraylib.L2M4_LINE)*1000
                    elif ed.lower() == 'l1':
                        label = f'{el} Kβ3'
                        eline = xraylib.LineEnergy(z, xraylib.L1M3_LINE)*1000

                    self.axes.axvline(x = eline, color = 'brown', linewidth=1, label=label)
                self.axes.set_xlim(2500, eline+2000)
        else:
            self.axes.set_xlim(2500, 20000)
        self.axes.legend(loc='best', shadow=True)

        if get_backend().lower() == 'agg':
            if filename is not None:
                fname = os.path.join(experiment_folder(catalog, uid), 'XRF', filename)
                self.figure.savefig(fname)
                self.logger.info(f'saved XRF figure {fname}')
                if post is True:
                    img_to_slack(fname, title=self.title, measurement='xrf')
            



    def to_xdi(self, catalog=None, uid=None, filename=None):
        '''Write an XDI-style file with bin energy in the first column and the
        waveform of each of the channels in the other columns.

        '''
        if get_backend().lower() != 'agg':
            return()
        xdi = None
        if 'XDI' in catalog[uid].metadata["start"]:
            xdi = catalog[uid].metadata["start"]["XDI"]
        fname = os.path.join(experiment_folder(catalog, uid), 'XRF', filename)
        handle = open(fname, 'w')
        handle.write(f'# XDI/1.0 BlueSky/{bluesky_version}\n')
        handle.write(f'# Beamline.name: BMM (06BM) -- Beamline for Materials Measurement\n')
        handle.write(f'# Beamline.xray_source: NSLS-II three-pole wiggler\n')
        handle.write(f'# Beamline.collimation: paraboloid mirror, 5 nm Rh on 30 nm Pt\n')
        if xdi is not None:
            if 'Beamline' in catalog[uid].metadata['start']['XDI']:
                handle.write(f'# Beamline.focusing: {xdi["Beamline"]["focusing"]}\n')
                handle.write(f'# Beamline.harmonic_rejection: {xdi["Beamline"]["harmonic_rejection"]}\n')
                handle.write(f'# Beamline.energy: {xdi["_pccenergy"]}\n')
        handle.write(f'# Detector.fluorescence: SII Vortex ME4 (4-element silicon drift)\n')
        if xdi is not None:
            if 'Sample' in catalog[uid].metadata['start']['XDI']:
                handle.write(f'# Sample.name: {xdi["Sample"]["name"]}\n')
                handle.write(f'# Sample.prep: {xdi["Sample"]["prep"]}\n')
        start = datetime.datetime.fromtimestamp(catalog[uid].metadata['start']['time']).strftime('%A, %B %d, %Y %I:%M %p')
        #end   = datetime.datetime.fromtimestamp(catalog[uid].metadata['stop']['time']).strftime('%A, %B %d, %Y %I:%M %p')
        handle.write(f'# Scan.time: {start}\n')
        #handle.write(f'# Scan.stop: {end}\n')
        handle.write(f'# Scan.uid: {uid}\n')
        hdf5files = file_resource(catalog, uid)
        handle.write(f'# Scan.hdf5file: {hdf5files[0]}\n')
        handle.write(f'# Facility.name: NSLS-II\n')
        if xdi is not None:
            if 'Facility' in catalog[uid].metadata['start']['XDI']:
                handle.write(f'# Facility.energy: {xdi["Facility"]["energy"]}\n')
                handle.write(f'# Facility.cycle: {xdi["Facility"]["cycle"]}\n')
                handle.write(f'# Facility.GUP: {xdi["Facility"]["GUP"]}\n')
                handle.write(f'# Facility.SAF: {xdi["Facility"]["SAF"]}\n')
        handle.write('# Column.1: energy eV\n')

        column_list = []
        if '1-element SDD' in catalog[uid].metadata['start']['detectors']:
            nchan = 1
            column_list.append('MCA8')
        elif '4-element SDD' in catalog[uid].metadata['start']['detectors']:
            nchan = 4
        elif '7-element SDD' in catalog[uid].metadata['start']['detectors']:
            nchan = 7
        elif 'dante-1' in catalog[uid].metadata['start']['detectors']:
            nchan = 7
        for c in range(1, nchan+1):
            handle.write(f'# Column.{c+1}: MCA{c} counts\n')
            if nchan > 1:
                column_list.append(f'MCA{c}')
                
        handle.write('# //////////////////////////////////////////////////////////\n')
        if xdi is not None and "_comment" in xdi:
            for l in xdi["_comment"]:
                handle.write(f'# {l}\n')
        else:
            handle.write('# \n')
        handle.write('# ----------------------------------------------------------\n')
        handle.write('# energy ')

        ## data table
        s = []
        if nchan == 1:
            s.append(catalog[uid].primary.data['1-element SDD_channel08_xrf'][0])  #  note channel number!
            datatable = numpy.array([s,])
        elif 'dante-1' in catalog[uid].metadata['start']['detectors']:
            s.append(catalog[uid].primary.data['dante-1_image'][0][0])  #  note channel number!
            datatable = numpy.array([s,])
        else:
            for i in range(1, nchan+1):
                s.append(catalog[uid].primary.data[f'{nchan}-element SDD_channel0{i}_xrf'][0])
            datatable = numpy.vstack(s)
                
        e=numpy.arange(0, len(s[0])) * 10
        ndt=numpy.vstack(datatable)
        b=pandas.DataFrame(ndt.transpose(), index=e, columns=column_list)
        handle.write(b.to_csv(sep=' '))

        handle.flush()
        handle.close()
        print('wrote XRF spectra to %s' % fname)
                
class AreaScan():
    '''Manage the live plot for a motor scan or a time scan.
    '''

    ongoing     = False
    xdata       = []
    ydata       = []
    cdata       = []
    count       = 0 

    detector    = None
    element     = 'H'

    figure      = None
    axes        = None
    area        = None

    description = None
    xs1, xs2, xs3, xs4, xs8 = None, None, None, None, None
    plots       = []

    slow_motor  = None
    slow_start  = -1
    slow_steps  = 3
    slow_stop   = 1
    slow_initial = 0
    
    fast_motor  = None
    fast_start  = -1
    fast_steps  = 3
    fast_stop   = 1
    fast_initial = 0
    
    def start(self, **kwargs):
        #if self.figure is not None:
        #    plt.close(self.figure.number)
        self.ongoing = True
        self.xdata = []
        self.ydata = []

        self.slow_motor   = kwargs['slow_motor']
        self.slow_start   = kwargs['slow_start']
        self.slow_stop    = kwargs['slow_stop']
        self.slow_steps   = kwargs['slow_steps']
        self.slow_initial = kwargs['slow_initial']

        self.fast_motor   = kwargs['fast_motor']
        self.fast_start   = kwargs['fast_start']
        self.fast_stop    = kwargs['fast_stop']
        self.fast_steps   = kwargs['fast_steps']
        self.fast_initial = kwargs['fast_initial']

        self.energy       = kwargs['energy']
        self.element      = kwargs['element']

        self.slow = self.slow_initial + numpy.linspace(self.slow_start, self.slow_stop, self.slow_steps)
        self.fast = self.fast_initial + numpy.linspace(self.fast_start, self.fast_stop, self.fast_steps)

        
        self.detector     = kwargs['detector']
        self.cdata        = numpy.zeros(self.fast_steps * self.slow_steps)
        self.count        = 0
        
        self.figure = plt.figure()
        if self.fast_motor is not None:
            cid = self.figure.canvas.mpl_connect('button_press_event', self.interpret_click)
        
        
        self.plots.append(self.figure.number)
        self.axes = self.figure.add_subplot(111)
        self.axes.set_facecolor((0.95, 0.95, 0.95))
        self.im = self.axes.pcolormesh(self.fast, self.slow, self.cdata.reshape(self.slow_steps, self.fast_steps), cmap=plt.cm.viridis)
        self.figure.gca().invert_yaxis()  # plot an xafs_x/xafs_y plot upright
        self.cb = self.figure.colorbar(self.im)

        self.axes.set_xlabel(f'fast axis ({self.fast_motor}) position (mm)')
        self.axes.set_ylabel(f'slow axis ({self.slow_motor}) position (mm)')
        self.axes.set_title(f'{self.detector}   Energy = {self.energy:.1f}')

        
        self.xs1 = rkvs.get('BMM:user:xs1').decode('utf-8')
        self.xs2 = rkvs.get('BMM:user:xs2').decode('utf-8')
        self.xs3 = rkvs.get('BMM:user:xs3').decode('utf-8')
        self.xs4 = rkvs.get('BMM:user:xs4').decode('utf-8')
        self.xs8 = rkvs.get('BMM:user:xs8').decode('utf-8')

    def interpret_click(self, ev):
        '''Grab location of mouse click.  Identify motor by grabbing the
        x-axis label from the canvas clicked upon.

        Stash those in Redis.
        '''
        x,y = ev.xdata, ev.ydata
        print(x, ev.canvas.figure.axes[0].get_xlabel(), ev.canvas.figure.number)
        print(y, ev.canvas.figure.axes[0].get_ylabel(), ev.canvas.figure.number)
        rkvs.set('BMM:mouse_event:value', x)
        rkvs.set('BMM:mouse_event:motor', ev.canvas.figure.axes[0].get_xlabel())
        rkvs.set('BMM:mouse_event:value2', y)
        rkvs.set('BMM:mouse_event:motor2', ev.canvas.figure.axes[0].get_ylabel())
        
    def stop(self, catalog, **kwargs):
        if get_backend().lower() == 'agg':
            if 'filename' in kwargs and kwargs['filename'] is not None and kwargs['filename'] != '':
                fname = os.path.join(experiment_folder(catalog, kwargs["uid"]), 'maps', kwargs["filename"])
                self.figure.savefig(fname)
                self.logger.info(f'saved areascan figure {fname}')
                img_to_slack(fname, title=f'{self.detector}   Energy = {self.energy:.1f}', measurement='raster')

        self.ongoing     = False
        self.xdata       = []
        self.ydata       = []
        self.y2data      = []
        self.motor       = None
        self.element     = 'H'
        self.figure      = None
        self.axes        = None
        self.line        = None
        self.line2       = None
        self.line3       = None
        self.description = None
        self.xs1, self.xs2, self.xs3, self.xs4, self.xs8 = None, None, None, None, None
        self.initial     = 0


    def add(self, **kwargs):
        
        if 'dcm_roll' in kwargs['data']:
            return              # this is a baseline event document, dcm_roll is almost never scanned

        if self.detector == 'noisy_det':
            signal  = kwargs['data']['noisy_det']
        elif self.detector == 'I0':
            signal  = kwargs['data']['I0']
        elif self.detector == 'It':
            signal  = kwargs['data']['It'] / kwargs['data']['I0']
        elif self.detector == 'Iy':
            signal  = kwargs['data']['Iy'] / kwargs['data']['I0']
        elif self.detector == 'Ir':
            signal  = kwargs['data']['Ir'] / kwargs['data']['It']
        elif self.detector == 'Xs1':
            signal  = kwargs['data'][f'{self.element}8'] / kwargs['data']['I0']
        elif self.detector == 'Xs':
            signal  = (kwargs['data'][f'{self.element}1']+kwargs['data'][f'{self.element}2']+kwargs['data'][f'{self.element}3']+kwargs['data'][f'{self.element}4']) / kwargs['data']['I0']
            
        self.cdata[self.count] = signal
        self.axes.pcolormesh(self.fast, self.slow, self.cdata.reshape(self.slow_steps, self.fast_steps), cmap=plt.cm.viridis)
        self.im.set_clim(self.cdata.min(), self.cdata.max())
        self.count += 1
