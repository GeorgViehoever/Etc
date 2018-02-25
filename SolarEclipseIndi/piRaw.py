#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""" tool capturing RAW images on a RaspberryPi
Profike with options -mcProfile -s"tottime"

In addition to the modules available with Raspian anyway, you will need tto install
the following packages via apt-get or Settings/Add/Remove Software
- python3-numpy
- python3-matplotlib
- python3-pyfits

If RPi does not set time correctly on boot:
NTP workaround per https://github.com/raspberrypi/linux/issues/1519

Known problems:
  - Capturing 10 second shots takes 1:15 minutes. Most of this is spent in a lock in picamera, outside of
    this tool
  - Sometimes Tk-related traceback on Quit

Version:
0.1.0: Initial version
0.2.0: - control for analog gain and awb_gains that previously were floating
       - formatting picture number in file name to for digits, i.e. 0001, 0002, ...

"""

__author__    = 'Georg Viehoever'
__copyright__ = 'Copyright 2016, Georg Viehoever,  PiBayerFlatArray Copyright (c) 2013-2015 Dave Jones <dave@waveform.org.uk>'
__license__   = """
License/Copyright except for class PiBayerFlatArray, see there for license.

The MIT License (MIT)
Copyright (c) 2016 Georg Viehoever

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
__version__   = '0.2.0'
__email__     = 'georg.viehoever@web.de'
__maintainer__= 'Georg Viehoever'
__status__    = 'Prototype'
__date__      = '20160828'

import argparse
import trace
import datetime
import time
import functools
import math
import threading
import fractions
import os
import pathlib
import gc

#GUI
import tkinter as Tk
import tkinter.ttk as Ttk
import tkinter.messagebox as TkMb
import tkinter.filedialog as TkFd

import matplotlib as mpl
mpl.use("TkAgg") #FIXME Try other backend?
import matplotlib.pyplot as plt
import numpy as np

#Camera
import picamera
import picamera.array

# FITS file
import pyfits

#
# GUI
#
def busyCursor(f):
    """ decorator that causes execution of f with a busy cursor
    """
    @functools.wraps(f)
    def wrapper(self,*args,**kwargs):
        cursor=self.cget("cursor")
        try:
            #print("wait cursor")
            self.configure(cursor="watch")
            self.update() #necessary so cursor actually changes
            return f(self,*args,**kwargs)
        finally:
            #print("restore cursor")
            self.configure(cursor=cursor)
            self.update()

    return wrapper

class CaptureThread(threading.Thread):
    """" runs the capture thread
    """
    def __init__(self,shutterSpeed, numPictures,delay, directory, prefix, autoShutter, updateImageGui,app=None):
        """ initialize thread class.
        :param shutterSpeed: Initial shutterspeed to use in microseconds
        :param numPictures: Number of pictures to take
        :param delay: delay between pictures in seconds, except for first picture. If capturing picture
               takes longer than this, the next picture is taken immediately
        :param directory: directory where pictures are stored
        :param prefix: prefix of file name, appended by "_num_datetime.fits"
        :param autoShutter: if true, adjust shutterSpeed such that self.targetMean is reach. self.targetFactor
               is the accepted tolerance
        :param updateImageGui: if True provide debayered image to GUI. Needs additional time
        :param app: owning app, optional. If given, GUI updates are made
        """
        self.shutterSpeed=shutterSpeed
        """ shutter speed to use. May be changed with autoShutter"""
        self.numPictures=numPictures
        """ number of pictures still to be taken"""
        self.delay=delay
        """ delay between shots in secs. First shot is done immediately. If shot takes longer than delay,
            the next shot is done immediately
        """
        self.autoShutter = autoShutter
        """ if true adapt shutterSpeed by 10% until mean value of 256 is reached"""

        self.updateImageGui =updateImageGui and (app is not None)
        """ if True, send captured image also to GUI. Need additional time for debayer and display"""
        self.directory=directory
        """ path where images are stored"""
        self.prefix=prefix
        """ prefix for filename. Files are stored as "prefix_Num_DateTime.ms.fits"""

        self.app=app
        """ calling app. If not None, issue callbacks for updating the GUI"""

        self.targetMean=500
        """ target mean for exposure"""
        self.targetFactor=1.05
        """ tolerance factor for autoShutter"""

        self.bStopRequest=False
        """ set by stopReques(). Stops run()"""

        super().__init__()


    @staticmethod
    def _captureFits(shutterSpeed,filename,debayer):
        """ capture image to fits file
        @param shutterSpeed in microseconds
        @param filename where to store file. Existing file is overwritten
        @param debayer: If truem also return debayered image
        returns (raw,debayered) with debayer==None if debayer is False, else None
        """
        with RawCamera() as camera:
            camera.shutter_speed=shutterSpeed
            raw,debayer=camera.capture(debayer)
            #print("camera: ISO=",camera.iso, ", analogGain=",camera.analog_gain, "awb_gains=",camera.awb_gains)
        hdu=pyfits.PrimaryHDU(raw)
        # FIXME add some fits keywords, such as date
        hduList=pyfits.HDUList([hdu])
        hdu.writeto(filename,clobber=True)
        return (raw,debayer)

    def _updateApp(self,running,debayer=None):
        """ update app with current values
        @param running: True if still running, otherwise terminating
        @param image: debayered image, may be None
        """
        if self.app is None:
            return
        if running:
            thread=self
        else:
            thread=None
        self.app.threadUpdateItems(thread, self.shutterSpeed, self.numPictures, debayer)


    def stopRequest(self):
        """ call to stop running thread. Returns immediazely without waiting for stop
        """
        self.bStopRequest=True

    def adjustShutter(self,image):
        if image is None:
            return
        mean=max(1.0,np.mean(image))
        #if mean<self.targetMean/self.targetFactor:
        #    self.shutterSpeed=min(1000000*10,int(self.targetFactor*self.shutterSpeed))
        #elif mean>self.targetMean*self.targetFactor:
        #    self.shutterSpeed=max(1000000//1000,int(self.shutterSpeed/self.targetFactor))
        if mean < self.targetMean / self.targetFactor or mean > self.targetMean * self.targetFactor:
            self.shutterSpeed = min(1000000 * 10, max(1000000 // 100000, int(self.shutterSpeed*self.targetMean/mean)))

    def run(self):
        """ actual work. Also ,manages state with app.

        thread stops when work is done or if someone called stopRequest()
        """

        self.bStopRequest=False
        bFirst=True
        lastCaptureTime = datetime.datetime.now()
        i = 0
        fileTemplate=str(pathlib.Path(self.directory)/pathlib.Path(self.prefix+"_{:04d}_{!s}.fits"))
        try:
            while not self.bStopRequest and self.numPictures > 0:
                debayer=None
                timeSinceCapture = (datetime.datetime.now() - lastCaptureTime).total_seconds()
                if bFirst or timeSinceCapture >= self.delay:
                    # take picture
                    lastCaptureTime = datetime.datetime.now()
                    filename=fileTemplate.format(i,lastCaptureTime.strftime("%Y%m%d%H%M%S.%f"))
                    print("Capture", i,filename,self.numPictures)
                    (raw,debayer)=self._captureFits(self.shutterSpeed,filename,self.updateImageGui)
                    #raw=None
                    if self.autoShutter:
                        self.adjustShutter(raw)
                    bFirst = False
                    i += 1
                    self.numPictures -= 1
                    # attempt to fight the memory leak
                    gc.collect()
                else:
                    # make sure we poll at least every seconds
                    timeToGo=self.app.captureDelay-timeSinceCapture
                    timeToSleep = min(1, timeToGo )
                    print("sleeping",timeToGo)
                    time.sleep(timeToSleep)
                self._updateApp(True,debayer)
        finally:
            self._updateApp(False)
            #print("thread terminated")

class HelpWindow:
    def __init__(self, master, helpText):
        self.master = master
        self.master.wm_title("Help") #window title
        self.master.protocol("WM_DELETE_WINDOW",self._quitCallback) #close action
        self.frame = Tk.Frame(self.master)
        self.text=Tk.Text(self.frame,width=110)
        self.text.pack(side=Tk.TOP)
        self.text.insert(Tk.END, str(helpText))
        self.quitButton = Tk.Button(self.frame, text = 'Quit', width = 25, command = self._quitCallback)
        self.quitButton.pack(side=Tk.TOP)
        self.frame.pack()
    def _quitCallback(self):
        self.master.destroy()

class RawCameraApp(Tk.Frame):
    """GUI for RawCamera
    """

    def __init__(self,master):

        # slots
        self.shutter_speed=int(1000000 / 10)
        """ shutter speed used in microseconds"""

        # GUI
        self.subsample=100
        """x size of sample used for display. Avoids memory problems"""
        self.rotation=0
        """rotation of image in view, 0,90,180,270"""

        # managing the capture thread
        self.captureThread=None
        """thread object doing the capture, not None only while running"""

        # capture thread settings
        self.captureNum = 100
        """ number of images on run """
        self.captureDelay = 120
        """ delay between images during run"""
        self.captureDirectory=os.getcwd()
        """ directory for storing images"""
        self.capturePrefix="light"
        """ prefix for generated file names"""
        self.captureAutoShutter=True
        """" if True, drift current exposure time until mean value 256 is reached"""
        self.captureDisplayImage=True
        """ if True, display captured images in GUI. Needs additional time"""

        #some image with non-trivial histogram
        image1=np.random.randint(0,512,(self.subsample,self.subsample,3))
        image2=np.random.randint(0,513,(self.subsample,self.subsample,3))
        self.image=(image1+image2).astype(np.uint16)
        """image being displayed in GUI, expected to be (low quality) debayered"""
        #GUI
        super().__init__(master)
        self._createWidgets()

    @property
    def logShutter_speed(self):
        """ log10 value of shutter_speed in [s]
        """
        res=math.log10(self.shutter_speed / 1000000)
        return res

    @logShutter_speed.setter
    def logShutter_speed(self,value):
        """ set log1 value of shutter speed in [s]
        """
        self.shutter_speed=int((10.0 ** value) * 1000000)

    def _createWidgets(self):
        """Create the GUI elements
        """
        self.master.wm_title("PiRaw Camera") #window title
        self.master.protocol("WM_DELETE_WINDOW",self._quitCallback) #close action

        # matplotlib related elements
        self.figure=self._genFigure()
        self.canvas=mpl.backends.backend_tkagg.FigureCanvasTkAgg(self.figure,master=self)
        self.canvas.get_tk_widget().pack(side=Tk.TOP,fill=Tk.BOTH,expand=1)

        self.toolbar=mpl.backends.backend_tkagg.NavigationToolbar2TkAgg(self.canvas,self)
        self.toolbar.pack(side=Tk.TOP,fill=Tk.BOTH)

        # GUI elements for test capture shown in GUI
        self.uiFrameCapture=Tk.Frame(self)
        self.uiCaptureTestButton=Tk.Button(self.uiFrameCapture,text="Capture Test",command=self._captureTestCallback)
        self.uiCaptureTestButton.pack(side=Tk.LEFT)

        self.uiLogShutterSlider=Tk.Scale(self.uiFrameCapture,label="log10(shutter)[s]",
                                         from_=-5,to=1,
                                         orient=Tk.HORIZONTAL,length=200,resolution=0.02,
                                         command=self._logShutterCallback)
        self.uiLogShutterSlider.pack(side=Tk.LEFT)
        self.uiShutterLabel = Tk.Label(self.uiFrameCapture, text="x.xx s")
        self.uiShutterLabel.pack(side=Tk.LEFT)

        self.uiRotationLabel = Tk.Label(self.uiFrameCapture, text="Rotate View [deg]:")
        self.uiRotationLabel.pack(side=Tk.LEFT)
        self._rotationVar=Tk.IntVar(self.uiFrameCapture,self.rotation)
        self.uiRot0RadioButton=Tk.Radiobutton(self.uiFrameCapture, text="0",
                                              variable=self._rotationVar,value=0,
                                              command=self._rotationCallback)
        self.uiRot0RadioButton.pack(side=Tk.LEFT)
        self.uiRot90RadioButton=Tk.Radiobutton(self.uiFrameCapture, text="90",
                                              variable=self._rotationVar,value=90,
                                              command=self._rotationCallback)
        self.uiRot90RadioButton.pack(side=Tk.LEFT)
        self.uiRot180RadioButton=Tk.Radiobutton(self.uiFrameCapture, text="180",
                                              variable=self._rotationVar,value=180,
                                              command=self._rotationCallback)
        self.uiRot180RadioButton.pack(side=Tk.LEFT)
        self.uiRot270RadioButton=Tk.Radiobutton(self.uiFrameCapture, text="270",
                                              variable=self._rotationVar,value=270,
                                              command=self._rotationCallback)
        self.uiRot270RadioButton.pack(side=Tk.LEFT)

        self.uiFrameCapture.pack(side=Tk.TOP,fill=Tk.BOTH)

        # GUI elements for capture to file

        #self.uiCaptureFitsButton=Tk.Button(self.uiFrameFile,text="Single FITS",command=self._captureFitsCallback)
        #self.uiCaptureFitsButton.pack(side=Tk.LEFT)


        self.uiFrameSequence = Tk.Frame(self)

        # GUI elements for sequence
        self.uiCaptureNumLabel=Tk.Label(self.uiFrameSequence,text="No of Images:")
        self.uiCaptureNumLabel.pack(side=Tk.LEFT)
        self._captureNumVar=Tk.IntVar(self.uiFrameSequence,self.captureNum)
        captureNumCallback=self.uiFrameSequence.register(self._captureNumCallback)
        self.uiCaptureNumEntry=Ttk.Entry(self.uiFrameSequence,width=4,textvariable=self._captureNumVar,
                                         validate="all",validatecommand=(captureNumCallback,"%P"))
        self.uiCaptureNumEntry.pack(side=Tk.LEFT)

        self.uiCaptureDelayLabel = Tk.Label(self.uiFrameSequence, text="Delay [s]:")
        self.uiCaptureDelayLabel.pack(side=Tk.LEFT)

        self._captureDelayVar=Tk.IntVar(self.uiFrameSequence,self.captureDelay)
        captureDelayCallback = self.uiFrameSequence.register(self._captureDelayCallback)
        self.uiCaptureDelayEntry = Ttk.Entry(self.uiFrameSequence, width=4, textvariable=self._captureDelayVar,
                                           validate="all", validatecommand=(captureDelayCallback, "%P"))
        self.uiCaptureDelayEntry.pack(side=Tk.LEFT)

        self._captureAutoShutterVar=Tk.BooleanVar(self.uiFrameSequence,self.captureAutoShutter)
        self.uiCaptureAutoShutterCheckbox=Tk.Checkbutton(self.uiFrameSequence,text="AutoShutter",command=self._captureAutoShutterCallback,
                                                  variable=self._captureAutoShutterVar)
        self.uiCaptureAutoShutterCheckbox.pack(side=Tk.LEFT)

        self.uiFrameSequence.pack(side=Tk.TOP, fill=Tk.BOTH)

        # GUI elements for file management
        self.uiFrameFile=Tk.Frame(self)
        self.uiCaptureDirectoryButton = Tk.Button(self.uiFrameFile, text="Directory...", command=self._captureDirectoryCallback)
        self.uiCaptureDirectoryButton.pack(side=Tk.LEFT)
        self.uiCaptureDirectoryLabel=Tk.Label(self.uiFrameFile,text="")
        self.uiCaptureDirectoryLabel.pack(side=Tk.LEFT)

        self.uiCapturePrefixLabel = Tk.Label(self.uiFrameFile, text="Prefix:")
        self.uiCapturePrefixLabel.pack(side=Tk.LEFT)
        self._capturePrefixVar=Tk.IntVar(self.uiFrameFile,self.capturePrefix)
        capturePrefixCallback = self.uiFrameFile.register(self._capturePrefixCallback)
        self.uiCapturePrefixEntry = Ttk.Entry(self.uiFrameFile, width=8, textvariable=self._capturePrefixVar,
                                           validate="all", validatecommand=(capturePrefixCallback, "%P"))
        self.uiCapturePrefixEntry.pack(side=Tk.LEFT)

        self.uiCaptureRunButton = Tk.Button(self.uiFrameFile, text="Run", command=self._captureRunCallback)
        self.uiCaptureRunButton.pack(side=Tk.LEFT)

        self.uiFrameFile.pack(side=Tk.TOP,fill=Tk.BOTH)

        #Quit +Help Button
        self.quitButton=Tk.Button(self,text="Quit",command=self._quitCallback)
        self.quitButton.pack(side=Tk.LEFT)
        self.helpButton=Tk.Button(self,text="Help...",command=self._helpCallback)
        self.helpButton.pack(side=Tk.LEFT)

        self.pack(fill=Tk.BOTH, expand=1)

        self._updateItems()


    def threadUpdateItems(self,thread,shutterSpeed,captureNum,image=None):
        """ called by capture thread to update GUI
        """
        self.captureThread=thread
        self.shutter_speed=shutterSpeed
        #print("threadUpdateItems():shutterSpeed=",shutterSpeed)
        self.captureNum=captureNum
        if image is not None:
            self.image=image
            self._redraw()
        self._updateItems()
        self.update()

    def _updateItems(self):
        """ update GUI elements to current state
        """
        #update displayed values
        #print("_updateItems,log_shutter_speed",self.logShutter_speed)
        self.uiLogShutterSlider.set(self.logShutter_speed)
        self.uiShutterLabel.config(text="{:6.6f} sec".format(self.shutter_speed / 1000000))
        self._rotationVar.set(self.rotation)
        self._captureNumVar.set(self.captureNum)
        self._captureDelayVar.set(self.captureDelay)
        self._capturePrefixVar.set(self.capturePrefix)
        self._captureAutoShutterVar.set(self.captureAutoShutter)
        self.uiCaptureDirectoryLabel.config(text=self.captureDirectory[-20:])

        # disable/enable
        if self.captureThread is not None:
            self.uiCaptureRunButton.config(text="Abort")
            # FIXME wont update if disabled
            #self.uiCaptureFitsButton.config(state=Tk.DISABLED)
            self.uiCaptureNumEntry.config(state=Tk.DISABLED)
            self.uiCaptureDelayEntry.config(state=Tk.DISABLED)
            self.uiCaptureDirectoryButton.config(state=Tk.DISABLED)
            self.uiCapturePrefixEntry.config(state=Tk.DISABLED)
            self.uiCaptureTestButton.config(state=Tk.DISABLED)
            self.uiCaptureAutoShutterCheckbox.config(state=Tk.DISABLED)
            #self.uiLogShutterSlider.config(state=Tk.DISABLED)
            self.helpButton.config(state=Tk.DISABLED)
            self.quitButton.config(state=Tk.DISABLED)
        else:
            self.uiCaptureRunButton.config(text="Run")
            #self.uiCaptureFitsButton.config(state=Tk.NORMAL)
            self.uiCaptureNumEntry.config(state=Tk.NORMAL)
            self.uiCaptureDelayEntry.config(state=Tk.NORMAL)
            self.uiCaptureDirectoryButton.config(state=Tk.NORMAL)
            self.uiCapturePrefixEntry.config(state=Tk.NORMAL)
            self.uiCaptureTestButton.config(state=Tk.NORMAL)
            self.uiCaptureAutoShutterCheckbox.config(state=Tk.NORMAL)
            self.uiLogShutterSlider.config(state=Tk.NORMAL)
            self.helpButton.config(state=Tk.NORMAL)
            self.quitButton.config(state=Tk.NORMAL)


    def _quitCallback(self):
        """ callback for Quit button
        """
        if self.captureThread:
            TkMb.showerror("Error","Abort capture run before quitting!")
        else:
            self.quit()
            self.destroy()

    def _helpCallback(self):
        helpText="""PiRaw - A tool for capturing RAWs with the Raspberry Pi

This tool allows to capture RAWs with the Raspberry Pi Camera Module, controlled with a GUI.
So far tested with Raspberry Pi 3 and PiNoir V2.1, but should work with other
RaspberryPi systems as well.

The pictures are stored as bayered FITS files as understood by many astrophotography tools.
Pixel values are 0..1023 (10 bits). When read with PixInsight, the images can be debayered with
the RGGB pattern.

UI elements:
- Picture preview on the top left: Reduced resolution view of the captured picture. Can be rotated with the
  "Rotation" buttons. Reduced resolution is used to limit memory and CPU consumption
- Histogram on the top right: RGB histogram, generated from the reduced resolution picture.
- Capture Test button: Capture image, but dont store a FITS file. Good for determining shutter speed
  and camera orientation
- Shutter slider: Log scale slider to determine shutter speed. Actual shutter speed in displayed to the right.
  Note that there is no choice of aperture or ISO: The Pi Camera does not really have something like this.
- Rotate View buttons: Rotate the picture preview. Has no influence on the orientation of the FITS file
- No of Images text field: determine the number of images to be taken. One image is approx. 16 MB, so a
  16GB SD card is goold for several hundred images
- Delay: Time between images. If time is shorter than the time needed to take an image (20..80 seconds), the
  next shot is made immediately. Note that the time for capture depends on the shutter time. For 10 second
  captures it is around 80 seconds, for short exposure times around 20 seconds.
- Autoshutter check box: If enabled, adapts shutter time such that the mean value of an image is ~500.
  Adaption happens after each shot. Has no effect on Capture Test.
- Directory button: Choose directory where images are stored.
- Prefix text field: Enter file prefix. Files get names such as prefix_201_20160828163035.727016.fits,
  with _201 being the image number, then datetime.milliseconds, then postfix .fits.
- Run/Abort button: Run the capture sequence. While running, it is possible to abort.
- Help button: Display this text
- Quit button: Quit the tool"""
        newWindow = Tk.Toplevel(self.master)
        self.app = HelpWindow(newWindow,helpText)


    #@busyCursor
    def _captureRunCallback(self):
        """ callback for Run button, capture series
        """
        #print("_captureRunCallback")
        if self.captureThread is not None:
            self.captureThread.stopRequest()
        else:
            self.captureThread=CaptureThread(self.shutter_speed, self.captureNum,
                                             self.captureDelay, self.captureDirectory,
                                             self.capturePrefix, self.captureAutoShutter,
                                             self.captureDisplayImage,
                                             self)
            self.captureThread.start()

        self._updateItems()

    @busyCursor
    def _rotationCallback(self):
        """ Callback for rotation radio butttons
        """
        val=self._rotationVar.get()
        if val!=self.rotation:
            self.rotation=val
            self._redraw()

    def _captureNumCallback(self,val):
        """ callback for capture num entry
        """
        try:
            val=int(val)
        except ValueError:
            return False
        if val<0:
            return False
        self.captureNum=val
        return True

    def _captureDelayCallback(self, val):
        """ callback for capture delay entry
        """
        try:
            val = int(val)
        except ValueError:
            return False
        if val < 0:
            return False
        self.captureDelay = val
        return True

    @busyCursor
    def _captureTestCallback(self):
        """ capture test image
        """
        now=datetime.datetime.now()
        with RawCamera() as camera:
            #print("RawCameraApp._captureTestCallback() init=%s secs" % (datetime.datetime.now() - now))
            camera.shutter_speed=self.shutter_speed
            #print("RawCameraApp._captureTestCallback() shutter=%s secs" % (datetime.datetime.now() - now))
            self.image=camera.capture(True)[1]
        #print("RawCameraApp._captureTestCallback() capture=%s secs" % (datetime.datetime.now() - now))
        self._redraw()
        #print("RawCameraApp._captureTestCallback() redraw=%s secs" % (datetime.datetime.now() - now))

    #@busyCursor
    #def _captureFitsCallback(self):
    #    """ capture image to fits file
    #    """
    #    now=datetime.datetime.now()
    #    with RawCamera() as camera:
    #        camera.shutter_speed=self.shutter_speed
    #        image=camera.capture(False)
    #    print("RawCameraApp._captureFitsCallback() capture=%s secs" % (datetime.datetime.now() - now))
    #    print("FitsImage=",image.shape,image.dtype)
    #    hdu=pyfits.PrimaryHDU(image)
    #    hduList=pyfits.HDUList([hdu])
    #    print("RawCameraApp._captureFitsCallback() prepFits=%s secs" % (datetime.datetime.now() - now))
    #    hdu.writeto("test.fits",clobber=True)
    #    print("RawCameraApp._captureFitsCallback() writeFits=%s secs" % (datetime.datetime.now() - now))

    def _logShutterCallback(self,value):
        """ callback for shutter slider
        """
        self.logShutter_speed=float(value)
        self._updateItems()

    def _captureAutoShutterCallback(self):
        """ callback for autoshutter checkbox
        """
        self.captureAutoShutter=not self.captureAutoShutter
        self._updateItems()

    def _captureDirectoryCallback(self):
        """ callback for directory button
        """
        self.captureDirectory=TkFd.askdirectory(parent=self,initialdir=self.captureDirectory, mustexist=True,
                                                title=("Choose directory for images"))
        self._updateItems()

    def _capturePrefixCallback(self, val):
        """ callback for capture prefix entry
        """
        self.capturePrefix=val
        return True

    def _redraw(self):
        """ redraw with current data
        """
        now = datetime.datetime.now()
        size=self.figure.get_size_inches()

        self.figure=self._genFigure(self.figure)
        #print("RawCameraApp._redraw() genFigure=%s secs" % (datetime.datetime.now() - now))
        self.figure.set_size_inches(size)
        #print("RawCameraApp._redraw() set_size=%s secs" % (datetime.datetime.now() - now))
        self.canvas.figure=self.figure
        #print("RawCameraApp._redraw() set_figure=%s secs" % (datetime.datetime.now() - now))
        self.canvas.draw()
        #print("RawCameraApp._redraw() draw=%s secs" % (datetime.datetime.now() - now))

    def _genFigure(self,fig=None):
        """returns figure to be displayed
        """
        #print("genFigureCalled")
        #now=datetime.datetime.now()
        # subsample. Full image is too much for RPi
        #print("image.shape=",self.image.shape)
        subStep=max(1,self.image.shape[0]/self.subsample)
        smallImage=self.image[::subStep,::subStep,:]
        #print("RawCameraApp._genFigure() smallImage=%s secs" % (datetime.datetime.now() - now))

        #order seems incorrect, fix it
        #r = smallImage[:, :, 1].copy()
        #g = smallImage[:, :, 0].copy()
        #smallImage[:,:,0]=r
        #smallImage[:,:,1]=g

        uint8Image=(smallImage//4).astype(np.uint8)
        if self.rotation==90:
            uint8Image=np.rot90(uint8Image)
        elif self.rotation==180:
            uint8Image = np.rot90(uint8Image,2)
        elif self.rotation==270:
            uint8Image = np.rot90(uint8Image,3)

        #print("RawCameraApp._genFigure() uint8Image=%s secs" % (datetime.datetime.now() - now))
        #smallImage=self.image[0:self.subsample,0:self.subsample,:]
        #print("smallImage=",smallImage.shape, smallImage.dtype)
        #print("uin8Image=",uint8Image.shape, uint8Image.dtype)
        if fig is None:
            fig,axes=plt.subplots(1,2,squeeze=True)
        else:
            axes=fig.axes
            for ax in axes:
                ax.clear()
        #print("RawCameraApp._genFigure() subPlots=%s secs" % (datetime.datetime.now() - now))
        ax=axes[0]
        ax.imshow(uint8Image,interpolation='none')
        #print("RawCameraApp._genFigure() imshow=%s secs" % (datetime.datetime.now() - now))

        ax=axes[1]
        ax.hist([smallImage[:,:,i] for i in range(smallImage.shape[2])],bins=10,range=(0,1023),
                color=('r','g','b'))
        #print("RawCameraApp._genFigure() hist=%s secs" % (datetime.datetime.now() - now))

        ax.set_title("Mean={:4.3f}".format(smallImage.mean()))
        #ax.plot([1,2],[2,1])
        #print("RawCameraApp._genFigure() return=%s secs" % (datetime.datetime.now() - now))

        return fig

# Adapted from https://github.com/waveform80/picamera/pull/309:
# -faster decode
# -2d raw
# -correct debayer

# Copyright for the following class only:
# # Copyright (c) 2013-2015 Dave Jones <dave@waveform.org.uk>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the copyright holder nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
from numpy.lib.stride_tricks import as_strided
# Adapted PiBayerArray
class PiBayerFlatArray(picamera.array.PiArrayOutput):
    """
    Produces a 3-dimensional RGB array from raw Bayer data.
    This custom output class is intended to be used with the
    :meth:`~picamera.PiCamera.capture` method, with the *bayer* parameter set
    to ``True``, to include raw Bayer data in the JPEG output.  The class
    strips out the raw data, constructing a 2-dimensional numpy array organized
    as (rows, columns, colors). The resulting data is accessed via the
    :attr:`~PiArrayOutput.array` attribute::
        import picamera
        import picamera.array
        with picamera.PiCamera() as camera:
            with picamera.array.PiBayerArray(camera) as output:
                camera.capture(output, 'jpeg', bayer=True)
                print(output.array.shape)
    Note that Bayer data is *always* full resolution, so the resulting
    array always has the shape (1944, 2592, 3) with the V1 module, or
    (2464, 3280, 3) with the V2 module; this also implies that the
    optional *size* parameter (for specifying a resizer resolution) is not
    available with this array class. As the sensor records 10-bit values,
    the array uses the unsigned 16-bit integer data type.
    By default, `de-mosaicing`_ is **not** performed; if the resulting array is
    viewed it will therefore appear dark and too green (due to the green bias
    in the `Bayer pattern`_). A trivial weighted-average demosaicing algorithm
    is provided in the :meth:`demosaic` method::
        import picamera
        import picamera.array
        with picamera.PiCamera() as camera:
            with picamera.array.PiBayerArray(camera) as output:
                camera.capture(output, 'jpeg', bayer=True)
                print(output.demosaic().shape)
    Viewing the result of the de-mosaiced data will look more normal but still
    considerably worse quality than the regular camera output (as none of the
    other usual post-processing steps like auto-exposure, white-balance,
    vignette compensation, and smoothing have been performed).
    .. _de-mosaicing: http://en.wikipedia.org/wiki/Demosaicing
    .. _Bayer pattern: http://en.wikipedia.org/wiki/Bayer_filter
    """

    def __init__(self, camera):
        super(PiBayerFlatArray, self).__init__(camera, size=None)
        self._demo = None

    def flush(self):
        super(PiBayerFlatArray, self).flush()
        self._demo = None
        ver = 1
        data = self.getvalue()[-6404096:]
        if data[:4] != b'BRCM':
            ver = 2
            data = self.getvalue()[-10270208:]
            if data[:4] != b'BRCM':
                raise picamera.exc.PiCameraValueError('Unable to locate Bayer data at end of buffer')
        # Strip header
        data = data[32768:]
        # Reshape into 2D pixel values
        reshape, crop = {
            1: ((1952, 3264), (1944, 3240)),
            2: ((2480, 4128), (2464, 4100)),
        }[ver]
        data = np.frombuffer(data, dtype=np.uint8). \
                   reshape(reshape)[:crop[0], :crop[1]]
        # Unpack 10-bit values; every 5 bytes contains the high 8-bits of 4
        # values followed by the low 2-bits of 4 values packed into the fifth
        # byte
        data = data.astype(np.uint16) << 2
        for byte in range(4):
            data[:, byte::5] |= ((data[:, 4::5] >> ((4 - byte) * 2)) & 3)
        # Create a new array from the unpacked data
        self.array = np.zeros((data.shape[0], (data.shape[1]*4)//5), dtype=np.uint16)
        for i in range(4):
            self.array[:, i::4] = data[:, i::5]

    def demosaic(self):
        if self._demo is None:
            # XXX Again, should take into account camera's vflip and hflip here
            # Construct representation of the bayer pattern
            expandedArray = np.zeros(self.array.shape + (3,), dtype=self.array.dtype)
            expandedArray[1::2, 1::2, 0] = self.array[1::2, 1::2]  # Red
            expandedArray[1::2, 0::2, 1] = self.array[1::2, 0::2]  # Green
            expandedArray[0::2, 1::2, 1] = self.array[0::2, 1::2]  # Green
            expandedArray[0::2, 0::2, 2] = self.array[0::2, 0::2]  # Blue
            # Construct representation of the bayer pattern
            bayer = np.zeros(expandedArray.shape, dtype=np.uint8)
            bayer[1::2, 1::2, 0] = 1  # Red
            bayer[0::2, 1::2, 1] = 1  # Green
            bayer[1::2, 0::2, 1] = 1  # Green
            bayer[0::2, 0::2, 2] = 1  # Blue
            # Allocate output array with same shape as data and set up some
            # constants to represent the weighted average window
            window = (3, 3)
            borders = (window[0] - 1, window[1] - 1)
            border = (borders[0] // 2, borders[1] // 2)
            # Pad out the data and the bayer pattern (np.pad is faster but
            # unavailable on the version of numpy shipped with Raspbian at the
            # time of writing)
            rgb = np.zeros((
                expandedArray.shape[0] + borders[0],
                expandedArray.shape[1] + borders[1],
                expandedArray.shape[2]), dtype=self.array.dtype)
            rgb[
            border[0]:rgb.shape[0] - border[0],
            border[1]:rgb.shape[1] - border[1],
            :] = expandedArray
            bayer_pad = np.zeros((
                expandedArray.shape[0] + borders[0],
                expandedArray.shape[1] + borders[1],
                expandedArray.shape[2]), dtype=bayer.dtype)
            bayer_pad[
            border[0]:bayer_pad.shape[0] - border[0],
            border[1]:bayer_pad.shape[1] - border[1],
            :] = bayer
            bayer = bayer_pad
            # For each plane in the RGB data, construct a view over the plane
            # of 3x3 matrices. Then do the same for the bayer array and use
            # Einstein summation to get the weighted average
            self._demo = np.empty(expandedArray.shape, dtype=expandedArray.dtype)
            for plane in range(3):
                p = rgb[..., plane]
                b = bayer[..., plane]
                pview = as_strided(p, shape=(
                                                p.shape[0] - borders[0],
                                                p.shape[1] - borders[1]) + window, strides=p.strides * 2)
                bview = as_strided(b, shape=(
                                                b.shape[0] - borders[0],
                                                b.shape[1] - borders[1]) + window, strides=b.strides * 2)
                psum = np.einsum('ijkl->ij', pview)
                bsum = np.einsum('ijkl->ij', bview)
                self._demo[..., plane] = psum // bsum
        return self._demo


# Patching this because default 30 is too short
picamera.PiCamera.CAPTURE_TIMEOUT=80
class RawCamera:
    """ Raw camera class

    Similar to picamera.PiCamera, but tailored towards RAW images.
    Can also work as context manager
    """

    CAMERA_CAPABIILITES={"RP_imx219":{"max_resolution":(3280,2464),
                                      "min_framerate":fractions.Fraction(1,10),
                                      "max_framerate":fractions.Fraction(120,1), #determined empirically, higher cause error
                                      "max_shutter":10*1000000,
                                      "max_mode":3},
                         "RP_OV5647":{"max_resolution:":(2592,1944),
                                      "min_framerate":fractions.Fraction(1,6),
                                      "max_framerate":fractions.Fraction(120,1), #not yet tested
                                      "max_shutter=":6*1000000,
                                      "max_mode":3}
                         }
    """ capabilities of sensors. Framerate is in 1/s, shutter in microsecond
    """

    def __init__(self):
        """ Initializes camera

        needs minimum of 2 seconds
        """
        self._camera=picamera.PiCamera()
        self.iso=800
        self.awb_mode="off"
        self.awb_gains=(1,1)
        # other init settings dont make sense here and seem to have no effect
    def __repr__(self):
        """ return repr string
        """
        if self.closed():
            return "RawCamera: Camera=None"
        else:
            return "RawCamera: Camera={!s}, exposure_speed={!s}".format(self.camera,self.exposure_speed)

    #
    # Context manager
    #

    def __enter__(self):
        """ context manager entry. Launches connection. Use for with-statement
        """
        return self


    def __exit__(self, type, value, traceback):
        """ context manager exit. Takes down connection. Use for with-statement
        """
        self.close()

    def close(self):
        """ deactivate camera

        Most calls on self are illegal once the camera has been closed
        """
        if self._camera is not None:
            self._camera.close()
            self._camera=None

    @property
    def closed(self):
        """ returns true if close has been called

        Most calls on self are illegal once the camera has been closed
        """
        return self._camera is None or self._camera.closed()

    @property
    def exposure_speed(self):
        """ return current exposure speed
        """
        return self._camera.exposure_speed


    @property
    def shutter_speed(self):
        """ return shutter speed in microseconds
        """
        return self._camera.shutter_speed

    @shutter_speed.setter
    def shutter_speed(self,microseconds):
        """ set shutter speed in microseconds
        """
        #print("shutter_speed=",microseconds,type(microseconds))
        # set framerate as neeeded
        # The time needed for capture is strongly influenced by framerate. Therefore
        # set quickest framerate possible.
        shutterSecs=microseconds/1000000
        if shutterSecs>=1.0:
            framerate=fractions.Fraction(1,math.ceil(shutterSecs))
        else:
            maxFramerate=self.CAMERA_CAPABIILITES[self.sensor_type]["max_framerate"]
            framerate=min(maxFramerate,fractions.Fraction(math.floor(1/shutterSecs),1))
        #print("framerate=",framerate)
        self._camera.framerate=framerate
        self._camera.shutter_speed=microseconds

    @property
    def analog_gain(self):
        """ return analog_gain
        """
        return self._camera.analog_gain
    @analog_gain.setter
    def analog_gain(self,val):
        """set analog gain
        """
        self._camera.analog_gain=val

    @property
    def awb_mode(self):
        """return awb_mode
        """
        return self._camera.awb_mode
    @awb_mode.setter
    def awb_mode(self,val):
        """ set awb_mode
        """
        self._camera.awb_mode=val

    @property
    def awb_gains(self):
        """ return awb_gains
        """
        return self._camera.awb_gains
    @awb_gains.setter
    def awb_gains(self,values):
        """ set awb_gains (pair of values
        """
        self._camera.awb_gains=values

    @property
    def iso(self):
        """ return iso
        """
        return self._camera.iso
    @iso.setter
    def iso(self,val):
        """ set iso to value
        """
        self._camera.iso=val

    def capture(self,bDemosaic=True):
        """ capture an image, returns numpy arrays with (raw,debayer), with debayer only filled if bDemosaic=True
        @param bDemosaic: if True, return demosaiced RGB array. Otherwise: Flat RGGB array
        """
        #print("Capture()")
        now=datetime.datetime.now()
        with PiBayerFlatArray(self._camera) as output:
            if not bDemosaic:
                # returns array with RGGB mosaic when saved to FITS
                self._camera.hflip = True
                self._camera.vflip = True
            #print("RawCamera:__capture__() init bayer=%s secs" % (datetime.datetime.now() - now))
            # print("In With")
            self._camera.capture(output, 'jpeg', bayer=True)
            #print("RawCamera:__capture__() capture bayer=%s secs" % (datetime.datetime.now() - now))
            # print("Capture done")
            raw=output.array
            if bDemosaic:
                debayer = output.demosaic()
                raw=raw[::-1,::-1] #because of h/Hflip
            else:
                debayer=None
        #print("RawCamera:__capture__() exit=%s secs"%(datetime.datetime.now()-now))
        return (raw,debayer)

    @property
    def sensor_type(self):
        """ return sensor type of camera
        """
        return self._camera.exif_tags['IFD0.Model']

class EvalArgs:
    """evaluates the command line. Provides --help.  See property methods for the results.
    """

    def __init__(self):
        self.parser = self.createParser()
        self.args = self.parser.parse_args()

    @staticmethod
    def createParser():
        # help -h option is automatically added
        parser = argparse.ArgumentParser(
            description="%(prog)s permits to take RAW photos using a RaspberryPi"
        )

        # debug
        parser.add_argument("-t", "--trace", action="store_true", help="activate trace mode for debugging.")
        parser.add_argument("-v", "--version", action="version", version=__version__,
                            help="display version of this tool and exit.")
        return parser

    @property
    def isTrace(self):
        return self.args.trace


def run(*args):
    #print("Hello World, args=",args)
    #with RawCamera() as camera:
    #    print(camera.capture().shape)
    app=RawCameraApp(Tk.Tk())
    app.mainloop()

def main():
    evalArgs=EvalArgs()
    print("{!s} running with arguments {!s}".format(datetime.datetime.now(),evalArgs.args))
    args = []
    if evalArgs.isTrace:

        aTrace = trace.Trace(count=False, trace=True,
                             # keep subprocess and os, but remove most other libs
                             ignoremods=["shlex", "posixpath", "UserDict", "threading", "platform", "getpass",
                                         "string"])
        aTrace.runctx(
            "run(*args)",
            globals(), locals())
    else:
        run(*args)

if __name__ == "__main__":
    print("{!s} started".format(datetime.datetime.now()))
    try:
        main()
    finally:
        print("{!s} stopped".format(datetime.datetime.now()))
