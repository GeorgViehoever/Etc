#!/usr/bin/env python3
# -*- coding: utf8 -*-
""" Implements INDI scheduler for Canon Camera. See configuration section.
"""

#
# formalia
#
__author__      = "Georg Viehoever"
__copyright__   = "(c) 2017 Georg Viehoever"
__license__   ="""
/*
* ----------------------------------------------------------------------------
* "THE CHOCOLATE LICENSE":
* Georg Viehoever wrote this file in 2017. As long as you retain this notice you
* can do whatever you want with this stuff. If we meet some day, and you think
* this stuff is worth it, you can buy me a chocolate in return.
* ----------------------------------------------------------------------------
*/
"""
__version__ = "0.1.1"
__status__ = "Prototype"

#
# imports
#
import sys
import time
import datetime as dt
import logging
import math

import PyIndi
import pandas as pd

#
# configuration
#

#
# Eclipe times. Based on these time, the exposure schedule is created. All times in UTC
#
UtcZone = dt.timezone.utc #(dt.timedelta(hours=0), "UTC")
""" timezone used in program"""
# schedule for actual eclipse at HiddenSpring
C1Time=    dt.datetime(2017, 8,21,16, 7,37,600000,UtcZone)
""" first contact"""
C2Time=    dt.datetime(2017, 8,21,17,20,58,900000,UtcZone)
""" second contact"""
MaxTime=   dt.datetime(2017, 8,21,17,22, 1,400000,UtcZone)
""" maximum eclipse"""
C3Time=    dt.datetime(2017, 8,21,17,23, 4,     0,UtcZone)
""" 3rd contact"""
C4Time=    dt.datetime(2017, 8,21,18,42,54,300000,UtcZone)

if True:
    # schedule for test run, modified for short partial phase, to start in 30 seconds
    Now=dt.datetime.now(UtcZone)
    Delay=dt.timedelta(seconds=5)
    PartialDuration=dt.timedelta(seconds=60)#185)
    C2ToMaxTimeDuration=MaxTime-C2Time
    MaxTimeToC3Duration=C3Time-MaxTime
    # adjust times given above
    C1Time= Now + Delay
    C2Time= C1Time + PartialDuration
    MaxTime=C2Time+C2ToMaxTimeDuration
    C3Time=MaxTime+MaxTimeToC3Duration
    C4Time= C3Time + PartialDuration

MINTIME = 3.0
""" minimal time in seconds between exposures, used when creating schedule"""

#INDI_HOST="raspberrypiAstro"
INDI_HOST="192.168.0.5"
""" hostname of INDI server"""
INDI_PORT=7624
""" port of INDI server"""
INDI_CAMERA="Canon DSLR EOS 80D"
"""" the device we are interested in"""

LOGGING_FORMAT='%(asctime)s %(message)s'
"""logging format """
LOGGING_LEVEL=logging.INFO
#LOGGING_LEVEL=logging.DEBUG
"""logging level """

SLEEPTIME=0.1
""" seconds for maximum sleep when polling for event"""
#
# functionality
#
logging.basicConfig(format=LOGGING_FORMAT, level=LOGGING_LEVEL)

def pollingSleep(secs):
    """ sleep for given number of secs with polling.

    This has the effect to return to Python every now and then,
    giving it a chance to do output etc.
    """
    maxSleep=SLEEPTIME #maximum time to sleep
    then=dt.datetime.now(UtcZone)+dt.timedelta(seconds=secs)
    now=dt.datetime.now(UtcZone)
    timeToSleep=min(maxSleep,(then-now).total_seconds())
    while timeToSleep>0.0:
        time.sleep(timeToSleep)
        now=dt.datetime.now(UtcZone)
        timeToSleep=min(maxSleep,(then-now).total_seconds())
    return

class IndiClient(PyIndi.BaseClient):
    """ basic client with debugging methods

    Based on https://sourceforge.net/p/pyindi-client/code/HEAD/tree/trunk/pip/pyindi-client/
    """
    def __init__(self):
        super(IndiClient, self).__init__()
        self.logger = logging.getLogger('IndiClient')
        self.logger.debug('creating an instance of IndiClient')

    def strNumber(self,v):
        """ output for number
        """
        f="label={}, format={}, min={}, step={}, aux0=NULL={}, value={}"
        return f.format(v.label,v.format,v.min,v.step,v.aux0 is None,v.value)

    def strNumberVector(self,v,prefix=" "):
        """ output for vector of numbers
        """
        return (prefix+"\n").join([self.strNumber(value) for value in v])

    def strVectorProperty(self,v):
        """ common output for all value vectors
        """
        f="device={}, name={}, label={}, group={}, IPERM={}, timeout={}, IPSTATE={},nnp={}, timestamp={}, aux==NULL={}"
        return f.format(v.device,v.name,v.label,v.group,self.strIPPerm(v.p),v.timeout,self.strIPState(v.s),v.nnp,v.timestamp,v.aux is None)

    def newDevice(self, d):
        self.logger.debug("new device " + d.getDeviceName())

    def newProperty(self, p):
        self.logger.debug("new property " + p.getName() + " for device " + p.getDeviceName())

    def removeProperty(self, p):
        self.logger.debug("remove property " + p.getName() + " for device " + p.getDeviceName())

    def newBLOB(self, bp):
        self.logger.debug("new BLOB " + bp.name.decode())

    def newSwitch(self, svp):
        self.logger.debug("new Switch " + svp.name + " for device " + svp.device)

    def newNumber(self, nvp):
        self.logger.debug("new Number {}\n{}".format(self.strVectorProperty(nvp),self.strNumberVector(nvp)))

    def newText(self, tvp):
        self.logger.debug("new Text " + tvp.name + " for device " + tvp.device)

    def newLight(self, lvp):
        self.logger.debug("new Light " + lvp.name + " for device " + lvp.device)

    def newMessage(self, d, m):
        self.logger.info("new Message " + d.messageQueue(m))

    def serverConnected(self):
        self.logger.debug("Server connected (" + self.getHost() + ":" + str(self.getPort()) + ")")

    def serverDisconnected(self, code):
        self.logger.debug("Server disconnected (exit code = " + str(code) + "," + str(self.getHost()) + ":" + str(
            self.getPort()) + ")")

    #
    # some helpers
    #
    # Note that all INDI constants are accessible from the module as PyIndi.CONSTANTNAME
    @staticmethod
    def strISState(s):
        if (s == PyIndi.ISS_OFF):
            return "Off"
        elif s==PyIndi.ISS_ON:
            return "On"
        else:
            raise ValueError("Unknown switch state")

    @staticmethod
    def strIPState(s):
        if (s == PyIndi.IPS_IDLE):
            return "Idle"
        elif (s == PyIndi.IPS_OK):
            return "Ok"
        elif (s == PyIndi.IPS_BUSY):
            return "Busy"
        elif (s == PyIndi.IPS_ALERT):
            return "Alert"
        else:
            raise ValueError("Unknown Switch State")

    @staticmethod
    def strIPPerm(s):
        if s==PyIndi.IP_RO:
            return "RO"
        elif s==PyIndi.IP_RW:
            return "RW"
        elif s==PyIndi.IP_WO:
            return "WO"
        else:
            #print("Perm=",s)
            raise ValueError("Unknown Permssion")

    def printProperty(self,property):
        """ print INDI property
        """
        print("   > " + property.getName())
        if property.getType() == PyIndi.INDI_TEXT:
            tpy = property.getText()
            for t in tpy:
                print("       TEXT " + t.name + "(" + t.label + ")= " + t.text)
        elif property.getType() == PyIndi.INDI_NUMBER:
            tpy = property.getNumber()
            for t in tpy:
                print("       NUMBER " + t.name + "(" + t.label + ")= " + str(t.value))
        elif property.getType() == PyIndi.INDI_SWITCH:
            tpy = property.getSwitch()
            for t in tpy:
                try:
                    print("       SWITCH " + t.name + "(" + t.label + ")= " + self.strISState(t.s))
                except UnicodeDecodeError:
                    # workaround for error I get with V4L2 driver on raspberryPi (Raspbian Jessie, May 2017)
                    print("UnicodeDecodeError")
        elif property.getType() == PyIndi.INDI_LIGHT:
            tpy = property.getLight()
            for t in tpy:
                print("       LIGHT " + t.name + "(" + t.label + ")= " + self.strIPState(t.s))
        elif property.getType() == PyIndi.INDI_BLOB:
            tpy = property.getBLOB()
            for t in tpy:
                print("       BLOB " + t.name + "(" + t.label + ")= <blob " + str(t.size) + " bytes>")

    def printCurrent(self):
        """ print all devices and properties
        """
        # Print list of devices. The list is obtained from the wrapper function getDevices as indiclient is an instance
        # of PyIndi.BaseClient and the original C++ array is mapped to a Python List. Each device in this list is an
        # instance of PyIndi.BaseDevice, so we use getDeviceName to print its actual name.
        print("List of devices")
        dl = self.getDevices()
        for dev in dl:
            print(dev.getDeviceName())

        # Print all properties and their associated values.
        print("List of Device Properties")
        for d in dl:
            print("-- " + d.getDeviceName())
            lp = d.getProperties()
            for p in lp:
                self.printProperty(p)

class CanonCamera:
    """ convenience class for handling a canon camera
    """


    def __init__(self,indiClient,indiDeviceName,bDebug=False):
        """indiClient is the IndiClient, indiDeviceName is the camera device name

        indiClient is supposed to be already connected
        :param bDebug: If True, switch camera to debug mode
        """
        self.logger= logging.getLogger("CanonCamera")
        if bDebug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

        self.logger.info("Creating CanonCamera for device {}".format(indiDeviceName))
        self.indiClient=indiClient
        self.indiDeviceName=indiDeviceName
        # find device
        self.indiDevice = self.indiClient.getDevice(self.indiDeviceName)
        while self.indiDevice is None:
            self.logger.warning("Cannot find device, trying again in 1 sec.")
            pollingSleep(1)
            self.indiDevice = self.indiClient.getDevice(self.indiDeviceName)
        # connect device
        while not self.indiDevice.isConnected():
            self.logger.warning("Device not yet connected, trying again in 1 sec.")
            self.indiClient.connectDevice(indiDeviceName)
            pollingSleep(1)
        pollingSleep(5)
        self.exposureTime=10
        """ current exposure time"""
        self.iso=800
        """ current ISO"""
        # store on SD CARD
        captureTargetAttribute=self.getSwitch("CCD_CAPTURE_TARGET")
        captureTargetAttribute[0].s = PyIndi.ISS_OFF
        # FIXME didnt do that, need 2.3 seconds anyway betweem exposures
        # FIXME patched indi_gphoto such that we dont load data from camera in this case
        captureTargetAttribute[1].s=PyIndi.ISS_ON
        self.indiClient.sendNewSwitch(captureTargetAttribute)

        # store as RAW
        nativeFormatAttribute=self.getSwitch("CCD_TRANSFER_FORMAT")
        nativeFormatAttribute[0].s=PyIndi.ISS_OFF
        nativeFormatAttribute[1].s=PyIndi.ISS_ON
        self.indiClient.sendNewSwitch(nativeFormatAttribute)

        # store as RAW
        uploadModeAttribute = self.getSwitch("UPLOAD_MODE")
        uploadModeAttribute[0].s = PyIndi.ISS_ON # dont want to write file, upload anything to net
        uploadModeAttribute[1].s = PyIndi.ISS_OFF
        uploadModeAttribute[2].s = PyIndi.ISS_OFF
        self.indiClient.sendNewSwitch(uploadModeAttribute)
        pollingSleep(3)

        if bDebug:
            # debug mode
            debugModeAttribute = self.getSwitch("DEBUG")
            debugModeAttribute[0].s = PyIndi.ISS_OFF
            debugModeAttribute[1].s = PyIndi.ISS_ON
            self.indiClient.sendNewSwitch(debugModeAttribute)
            self.indiClient.printCurrent()

    def getNumber(self,name):
        """ get number attribute and wait until it is ready
        """
        attribute=self.indiDevice.getNumber(name)
        while not attribute:
            print("Sleeping to get number attribute")
            time.sleep(SLEEPTIME)
            attribute = self.indiDevice.getNumber(name)
        return attribute

    def getSwitch(self,name):
        """ get switch attribute and wait until it is ready
        """
        attribute=self.indiDevice.getSwitch(name)
        while not attribute:
            print("Sleeping to get switch attribute")
            time.sleep(SLEEPTIME)
            attribute = self.indiDevice.getSwitch(name)
        return attribute

    def setIso(self,value):
        """set ISO value
        """
        #print("Setting Iso")
        isoAttribute=self.getSwitch("CCD_ISO")
        bestSwitch=None
        bestIsoDiff=float("inf")
        # find best matching ISO setting
        for switch in isoAttribute:
            isoStr=switch.label
            #print(isoStr)
            try:
                # extract number from name
                isoVal=float(isoStr)
                #print("isoVal=",isoVal)
            except ValueError:
                continue
            if abs(value-isoVal)<bestIsoDiff:
                bestIsoDiff=abs(value-isoVal)
                bestSwitch=switch
            switch.s=PyIndi.ISS_OFF
        if bestSwitch:
            bestSwitch.s=PyIndi.ISS_ON
            #print("setISO(), setting to ",bestSwitch.label)
            #print("Sending ISO")
            self.indiClient.sendNewSwitch(isoAttribute)
            #print("Send ISO done")
        else:
            raise ValueError("No suitable ISO found")
        #print("Set Iso done")

    def setExposureTime(self,value):
        """ set exposure time in seconds
        """
        if value>1.0:
            print("Current impl has problems with exposure times >1.0, in particular")
            print("in range 1-2. Expect lost or misconfigured shots")
        self.exposureTime=value

    def getBulb(self):
        """ True if bulb mode is set, false if M. Otherwise raise error
        """
        switchName = "autoexposuremode"
        labelBulb="Bulb"
        labelManual="Manual"
        attribute = self.getSwitch(switchName)
        for switch in attribute:
            if switch.s == PyIndi.ISS_ON:
                label = switch.label
                if label==labelBulb:
                    print("in Bulb mode")
                    return True
                elif label==labelManual:
                    print("in Manual mode")
                    return False
        raise ValueError("Neither Bulb nor Manual Mode")

    def setBulb(self,val):
        """ if True, set mode to Bulb, else to manual
        """
        #print("_setBulb(),val=",val)
        switchName = "autoexposuremode"
        if val:
            val="Bulb"
        else:
            val="Manual"
        attribute = self.getSwitch(switchName)
        # find switch with right label
        for switch in attribute:
            label = switch.label
            if label==val:
                bestSwitch=switch
            switch.s = PyIndi.ISS_OFF
        if bestSwitch:
            bestSwitch.s = PyIndi.ISS_ON
        else:
            raise ValueError("No suitable value found")
        self.indiClient.sendNewSwitch(attribute)
        pollingSleep(1)

    def _setExposureSwitchAndCapture(self):
        """ sets camera to best approximation of capture time and triggers exposure
        """
        print("_setExposureSwitchAndCapture")
        switchName="CCD_EXPOSURE_PRESETS"
        ccdExposureName="CCD_EXPOSURE"
        print("getting switch ",switchName)
        attribute=self.getSwitch(switchName)
        print("got switch")
        reqVal=self.exposureTime
        bestSwitch=None
        bestDiff=float("inf")
        # find best matching exposure setting
        for switch in attribute:
            label=switch.label
            if "/" in label:
                # written as 1/x
                try:
                    nomStr,divStr=label.split("/")
                    nomVal=float(nomStr)
                    divVal=float(divStr)
                    val=nomVal/divVal
                except ValueError:
                    continue
            else:
                # full seconds
                try:
                    val=float(label)
                except ValueError:
                    continue
            if abs(val-reqVal)<bestDiff:
                bestDiff=abs(val-reqVal)
                bestSwitch=switch
            switch.s=PyIndi.ISS_OFF
        if bestSwitch:
            bestSwitch.s=PyIndi.ISS_ON
            #print("setISO(), setting to ",bestSwitch.label)
            #triggers exposure
            print("Issuing exposure")
            self.indiClient.sendNewSwitch(attribute)
            print("Issue done")
            #time.sleep(reqVal)
            #print("sleep done")
        else:
            raise ValueError("No suitable exposure found")
        #print("Waiting CCD_EXPOSURE")
        # attempt to wait until Getting Raw has been done.
        # May need some re-engineering
        while self.getNumber("CCD_EXPOSURE")[0].value!=0:
            # works with exposures>2 sec.
            print("Waiting for exposure ok", self.getNumber(switchName)[0].value)
            time.sleep(SLEEPTIME)
        while self.getSwitch(switchName).s != PyIndi.IPS_OK:
            print("Waiting for switch ok",self.getSwitch(switchName).s)
            time.sleep(SLEEPTIME)
        while self.getNumber("CCD_INFO").s != PyIndi.IPS_IDLE:
            print("Waiting for info",self.getNumber("CCD_INFO").s)
            time.sleep(SLEEPTIME)

    def captureImage(self):
        """ capture image with current settings

        needs approx. 3.4 seconds+exposure time
        """
        #There are issues with exposures >1.0, in particular 1.0<=x<=2.0
        if True: #self.exposureTime>1.0:
            # using CCD_EXPOSURE
            #print("self.exposureTime=",self.exposureTime)
            # non-Bulb goes to 1 second
            # self._setBulb(self.exposureTime>1.0)
            exposureAttribute=self.getNumber("CCD_EXPOSURE")
            exposureAttribute[0].value=self.exposureTime
            self.indiClient.sendNewNumber(exposureAttribute)
            pollingSleep(self.exposureTime)
            # wait until exposure is done
            while self.getNumber("CCD_EXPOSURE").s != PyIndi.IPS_OK:
            #    #print("Waiting for ok",self.getNumber("CCD_EXPOSURE").s)
                time.sleep(SLEEPTIME)
        else:
            # can do 1/8000-1
            self._setBulb(False)
            self._setExposureSwitchAndCapture()


class Scheduler:
    """ generates photo schedule according to times set in header
    """

    ITERSCHEDULE=True
    """ If True, use iterative scheduler instead of precomputing table """

    COLNAMES=["seqNo","startTime","stopTime","exposureTime","ISO", "phase"]
    """ columnnames for the generated dataframe"""

    def __init__(self,minDelta,c1Time,c2Time,maxTime,c3Time,c4Time):
        """ create scheduler
        :param minDelta: minimum time between captures
        """
        self.minDelta=minDelta
        self.c1Time=c1Time
        self.c2Time=c2Time
        self.maxTime=maxTime
        self.c3Time=c3Time
        self.c4Time=c4Time
        # derive other times
        beadsTimeDelta=dt.timedelta(seconds=30) #time for beads
        diamondTimeDelta=dt.timedelta(seconds=8) #time for diamond ring
        self.beadsTime1=c2Time-beadsTimeDelta
        """ start time where I take filters off and hope for Baily's Bead"""
        self.diamondsTime1=c2Time-diamondTimeDelta
        """ start time for diamond ring"""
        self.diamondsTime2=c3Time+diamondTimeDelta
        """ end time for 2nd diamond ring"""
        self.beadsTime2=c3Time+beadsTimeDelta
        """ end time for beads"""

        self.partialIso=100
        """ iso during partial phase"""
        self.partialExposureSequence=[1.0/1250.0,1.0/3500, 1.0/500]#[1.0/1000.0,1.0/100, 1.0/250]#[1.0/1250.0,1.0/3500, 1.0/500]
        """ exposure time sequence during partial phase"""
        self.partialExposureDelta=60
        """ seconds between exposure sequences in partial phase"""

        self.beadsIso=100
        """ iso for beads"""
        self.beadsExposure=[1.0/4000]#[1.0/1000]#[1.0/4000]
        """ exposure for beads"""

        self.diamondIso=100
        """ iso for diamonds"""
        self.diamondExposure=[1.0/100]
        """ exposure time for diamonds"""

        self.totalityMinIso=100
        """ minimum ISO during totality"""
        self.totalityMaxTime=1.0#2.0 #camera has problems with anything >1.0
        """ maximum exposure time during totality"""
        self.totalityMinProduct=1.0/4000*100#1.0/1000*100#1.0/4000*100
        """ exposure value during initial phase"""
        self.totalityMaxProduct=6.0*200
        """ exposure value during maximum phase"""
        if not self.ITERSCHEDULE:
            # precompute table
            self.schedule=self._genSchedule()
            """ the table with the scheduled shots"""

    def nextShot(self):
        """ generator that yields the next shot, based on current time and already yielded shots
        """
        if self.ITERSCHEDULE:
            yield from self._nextShotIter()
        else:
            yield from self._nextShotPrecomputed()

    #
    # shots computed on the fly
    #
    def _nextShotIter(self):
        """ generate next shot based on current state. Compute on the fly
        """
        seqNo=0
        #print("_nextShotIter()")
        for shot in self._iterSequence("partial1", seqNo+1,self.c1Time,self.beadsTime1,self.partialIso,
                                    self.partialExposureSequence,self.partialExposureDelta,self.minDelta):
            #print("yielding partial 1, shot=",shot)
            yield shot
            seqNo+=1
        for shot in self._iterSequence("beads1",seqNo+1,
                                     self.beadsTime1,self.diamondsTime1,self.beadsIso,
                                     self.beadsExposure,0.0,self.minDelta):
            yield shot
            seqNo+=1
        for shot in self._iterSequence("diamonds1",seqNo+1,
                                     self.diamondsTime1, self.c2Time, self.diamondIso,
                                     self.diamondExposure, 0.0,self.minDelta):
            yield shot
            seqNo+=1
        for shot in self._iterTotality("totality",seqNo+1,
                                     self.c2Time,self.maxTime,self.c3Time,
                                     self.totalityMinIso,self.totalityMaxTime,
                                     self.totalityMinProduct,self.totalityMaxProduct,self.minDelta):
            yield shot
            seqNo+=1
        for shot in self._iterSequence("diamonds2",seqNo+1,
                                     self.c3Time, self.diamondsTime2, self.diamondIso,
                                     self.diamondExposure, 0.0,self.minDelta):
            yield shot
            seqNo+=1
        for shot in self._iterSequence("beads2",seqNo+1,
                                     self.diamondsTime2,self.beadsTime2,self.beadsIso,
                                     self.beadsExposure,0.0,self.minDelta):
            yield shot
            seqNo+=1
        for shot in self._iterSequence("partial2",seqNo+1,
                                     self.beadsTime2, self.c4Time, self.partialIso,
                                     self.partialExposureSequence, self.partialExposureDelta,self.minDelta):
            yield shot
            seqNo+=1

    @classmethod
    def _iterSequence(cls,sPhase,seqNo,startTime,stopTime,iso,exposureSequence,deltaTime,minDelta):
        """ generate sequence of shots
        :param sPhase: string describing phase
        :param seqNo: starting sequence number
        :param startTime: of sequence: First shot will wait for this time
        :param stopTime: endtime of sequence. Will return immediately if now is beyond this time
        :param iso: iso setting for this sequence
        :param exposureSequence: list of exposure values
        :param deltaTime time between sequences
        :param minDelta: estimate of required time for shot

        """
        subNo=0 #number in exposureSequence
        nextSubSequence=dt.timedelta(seconds=deltaTime)
        now = dt.datetime.now(UtcZone)
        nextShotTime = max(now,startTime)  # do first immediately
        subStartTime=nextShotTime # start time of subsequence

        while nextShotTime<stopTime:
            exposure=exposureSequence[subNo]
            requiredTime=dt.timedelta(seconds=minDelta+exposure)
            nextShotEnd=nextShotTime+requiredTime
            if nextShotEnd>=stopTime:
                # dont run into next sequence
                break
            shot=pd.Series({cls.COLNAMES[0]: seqNo,
                            cls.COLNAMES[1]: nextShotTime,
                            cls.COLNAMES[2]: nextShotEnd,
                            cls.COLNAMES[3]: exposure,
                            cls.COLNAMES[4]: iso,
                            cls.COLNAMES[5]: sPhase})
            yield shot

            #prepare next shot
            subNo=(subNo+1)%(len(exposureSequence))
            seqNo+=1
            now = dt.datetime.now(UtcZone)
            if subNo==0:
                # start of new subsequence:
                nextShotTime=max(now,subStartTime+nextSubSequence)
                subStartTime=nextShotTime
            else:
                nextShotTime=now
        return #seqNo-1 # last one was not used

    @classmethod
    def _iterExponential(cls, sPhase, seqNo, startTime, endTime, minIso, maxTime, startProduct, endProduct, minDelta):
        """ generate sequence of shots with as frequent as possible shots, not exceeding endTime

        with exponential curve going from startProduct to maxProduct (product=exposureTime*ISO) around maxTime,
        staying at minIso as long as possible.
        :param sPhase: string for phase name
        :param seqNo: starting sequence number
        :param startTime: datetime of beginning time
        :param endTime: datetime of end time
        :param minIso: minimal ISO value to use
        :param maxTime: maximum time to use
        :param startProduct: ISO*exposure time for shot at startTime
        :param endProduct: ISO*exposure time for shot at endTime
        :param minDelta: overhead time required by camera for managing a shot in seconds

        """
        #print("minIso=",minIso,", maxTime=",maxTime,", endProduct=",endProduct)
        lastExposureTime,_=cls._computeTimeIso(minIso, maxTime, endProduct)
        minProduct=min(startProduct,endProduct)
        maxProduct=max(startProduct,endProduct)
        lastExposureTime+=minDelta #time required for last exposure
        #print("lastExposureTime=",lastExposureTime)
        availableTime=(endTime-startTime).total_seconds()-lastExposureTime
        #print("availableTime=",availableTime)
        factor=endProduct/startProduct
        factorSecond=math.pow(factor,1.0/availableTime)

        now=dt.datetime.now(UtcZone)
        currentStartTime=max(now,startTime)
        currentTimeSeconds=(currentStartTime-startTime).total_seconds()

        while currentTimeSeconds<availableTime:
            #print("currentTimeSeconds=",currentTimeSeconds)
            currentProduct=startProduct*math.pow(factorSecond,currentTimeSeconds)
            #print("currentProduct=",currentProduct)
            currentProduct=max(minProduct,currentProduct)
            currentProduct=min(maxProduct,currentProduct)
            #print("currentProduct Clamped=", currentProduct)

            currentExposureTime,currentIso=cls._computeTimeIso(minIso, maxTime, currentProduct)
            currentStopTime=currentStartTime+dt.timedelta(seconds=currentExposureTime+minDelta)
            #print("currentIso=",currentIso,", currentExposureTime=",currentExposureTime)
            if currentStopTime>endTime:
                # dont go into next interval
                break
            shot = pd.Series({cls.COLNAMES[0]: seqNo,
                              cls.COLNAMES[1]: currentStartTime,
                              cls.COLNAMES[2]: currentStopTime,
                              cls.COLNAMES[3]: currentExposureTime,
                              cls.COLNAMES[4]: currentIso,
                              cls.COLNAMES[5]: sPhase})
            yield shot

            seqNo+=1
            now = dt.datetime.now(UtcZone)
            currentStartTime=max(now,startTime)
            currentTimeSeconds=(currentStartTime-startTime).total_seconds()


        return #seqNo-1

    @classmethod
    def _iterTotality(cls ,sPhase, startNo, startTime, maxEclipseTime, endTime,
                    minIso, maxExposureTime, startProduct, endProduct, minDelta ):
        """generate  exposure schedule, starting immediately

        with exponential curve going from startProduct to maxProduct (product=exposureTime*ISO) around maxTime,
        staying at minIso as long as possible.
        :param sPhase: string for phase name
        :param startNo: starting sequence number
        :param startTime: datetime of beginning time, C2
        :param maxExclipseTime : maximum eclipse
        :param endTime: datetime of end time, C3
        :param minIso: minimal ISO value to use
        :param maxExposureTime: maximum time to use
        :param startProduct: ISO*exposure time for shot at startTime
        :param endProduct: ISO*exposure time for shot at endTime
        :param minDelta: overhead time required by camera for managing a shot in seconds
        """
        for shot in cls._iterExponential(sPhase+"1",startNo,startTime,maxEclipseTime,
                                 minIso,maxExposureTime,startProduct,endProduct,minDelta):
            yield shot
            startNo+=1
        for shot in cls._iterExponential(sPhase+"2",startNo+1,maxEclipseTime,endTime,
                                 minIso,maxExposureTime,endProduct,startProduct,minDelta):
            yield shot
            #startNo+=1
        return #seqNo-1

    #
    # Precomputed shots
    #
    def _nextShotPrecomputed(self):
        """ generator that yields the next shot, based on current time and already yielded shots.

        Based on precomputed table in self.schedule
        """
        tolerance=dt.timedelta(seconds=0.1) #tolerance accepted between now and startTime
        for i,shot in self.schedule.iterrows():
            #print("shot=",shot,", type=",type(shot))
            now=dt.datetime.now(UtcZone)
            #print(now)
            #print(shot.startTime)
            if now-tolerance<=shot.startTime:
                #print("yielding shot=",shot)
                yield shot
            else:
                print("skipping shot, now=",now,", starttime=",shot.startTime,", diff=",now-shot.startTime)


    @classmethod
    def _genSequence(cls, sPhase, startNo, startTime, stopTime, iso, sequence, deltaTime, minDelta):
        """ generate table for exposure sequences between start and stopTime, not exceeding stop time
        :param sequence: List of exposure times in seconds
        """
        phase=[]
        seqNos=[]
        start=[]
        stop=[]
        isos=[]
        exposures=[]

        currentStartTime=startTime
        currentNo=startNo
        sequenceNo=0 # number in sequence list
        while currentStartTime<=stopTime:
            if sequenceNo==0:
                sequenceStartTime=currentStartTime

            currentExposureTime=sequence[sequenceNo]
            currentStopTime=currentStartTime+dt.timedelta(seconds=minDelta+currentExposureTime)
            if currentStopTime>=stopTime:
                # end time exceeds stopTime. No further shots in this sequence
                break
            seqNos.append(currentNo)
            phase.append(sPhase)
            start.append(currentStartTime)
            stop.append(currentStopTime)
            isos.append(iso)
            exposures.append(currentExposureTime)
            sequenceNo=(sequenceNo+1)%len(sequence)
            if sequenceNo != 0:
                # as quickly as possible
                currentStartTime=currentStopTime
            else:
                # keep minimum of deltatime
                currentStartTime=max(sequenceStartTime+dt.timedelta(seconds=deltaTime),currentStopTime)
            currentNo+=1


            #print("sequenceNo=",sequenceNo)


        res=pd.DataFrame({cls.COLNAMES[0]:seqNos,
                          cls.COLNAMES[1]:start,
                          cls.COLNAMES[2]:stop,
                          cls.COLNAMES[3]:exposures,
                          cls.COLNAMES[4]:isos,
                          cls.COLNAMES[5]:phase})
        #print("res=",res)
        return res

    @staticmethod
    def _computeTimeIso(minIso,maxTime,targetProduct):
        """ given desired product of time and iso, return iso,exposureTime within given limits

        stays at minIso as long as possibe
        :returns iso,exposureTime
        """
        #print("_computeTimeIso, minIso=",minIso,", maxTime=",maxTime,", targetProduct=",targetProduct)
        minIsoProduct=minIso*maxTime
        #print("minIsoProduct=",minIsoProduct)
        if targetProduct<=minIsoProduct:
            # we can achieve goal with minIso
            iso=minIso
        else:
            # we need to increase iso
            iso=targetProduct/maxTime
        time=targetProduct/iso
        return time,iso

    @classmethod
    def _genExponential(cls, sPhase, startNo, startTime, endTime, minIso, maxTime, startProduct, endProduct, minDelta):
        """ generate sequence of shots with as frequent as possible shots, not exceeding endTime

        with exponential curve going from startProduct to maxProduct (product=exposureTime*ISO) around maxTime,
        staying at minIso as long as possible.
        :param sPhase: string for phase name
        :param startNo: starting sequence number
        :param startTime: datetime of beginning time
        :param endTime: datetime of end time
        :param minIso: minimal ISO value to use
        :param maxTime: maximum time to use
        :param startProduct: ISO*exposure time for shot at startTime
        :param endProduct: ISO*exposure time for shot at endTime
        :param minDelta: overhead time required by camera for managing a shot in seconds
        """
        lastExposureTime,_=cls._computeTimeIso(minIso, maxTime, endProduct)
        lastExposureTime+=minDelta
        availableTime=(endTime-startTime).total_seconds()-lastExposureTime
        factor=endProduct/startProduct
        factorSecond=math.pow(factor,1.0/availableTime)
        currentTime=0.0
        currentNo=startNo

        phase=[]
        seqNos=[]
        start=[]
        stop=[]
        isos=[]
        exposures=[]
        while currentTime<availableTime:
            currentProduct=startProduct*math.pow(factorSecond,currentTime)
            currentExposureTime,currentIso=cls._computeTimeIso(minIso, maxTime, currentProduct)
            currentStartTime=startTime+dt.timedelta(seconds=currentTime)
            currentStopTime=currentStartTime+dt.timedelta(seconds=currentExposureTime+minDelta)

            seqNos.append(currentNo)
            phase.append(sPhase)
            start.append(currentStartTime)
            stop.append(currentStopTime)
            isos.append(currentIso)
            exposures.append(currentExposureTime)

            currentNo+=1
            currentTime+=currentExposureTime+minDelta

            res = pd.DataFrame({cls.COLNAMES[0]: seqNos,
                                cls.COLNAMES[1]: start,
                                cls.COLNAMES[2]: stop,
                                cls.COLNAMES[3]: exposures,
                                cls.COLNAMES[4]: isos,
                                cls.COLNAMES[5]: phase})
        #print("res=",res)
        return res

    @classmethod
    def _genTotality(cls ,sPhase, startNo, startTime, maxEclipseTime, endTime,
                    minIso, maxExposureTime, startProduct, endProduct, minDelta ):
        """ create exposure schedule

        with exponential curve going from startProduct to maxProduct (product=exposureTime*ISO) around maxTime,
        staying at minIso as long as possible.
        :param sPhase: string for phase name
        :param startNo: starting sequence number
        :param startTime: datetime of beginning time, C2
        :param maxExclipseTime : maximum eclipse
        :param endTime: datetime of end time, C3
        :param minIso: minimal ISO value to use
        :param maxExposureTime: maximum time to use
        :param startProduct: ISO*exposure time for shot at startTime
        :param endProduct: ISO*exposure time for shot at endTime
        :param minDelta: overhead time required by camera for managing a shot in seconds
        :return DataFrame
        """
        phase1=cls._genExponential(sPhase+"1",startNo,startTime,maxEclipseTime,
                                 minIso,maxExposureTime,startProduct,endProduct,minDelta)
        phase2=cls._genExponential(sPhase+"2",phase1.seqNo.iloc[-1]+1,phase1.stopTime.iloc[-1],endTime,
                                 minIso,maxExposureTime,endProduct,startProduct,minDelta)
        return phase1.append(phase2,ignore_index=True)

    def _genSchedule(self):
        """generates schedule in form of a pandas data frame

        Using times and values as proposed in http://www.astropix.com/html/i_astrop/2017_eclipse/Eclipse_2017.html#Sequence
        Format of Pandas table:
        seqNo(int), startTime (datetime), est.StopTime, exposureTime (seconds), ISO, done (bool), actualStart (datetime), actualStop
        """
        res=pd.DataFrame()
        # partial phase 1
        res=res.append(self._genSequence("partial1", 1,self.c1Time,self.beadsTime1,self.partialIso,
                                        self.partialExposureSequence,self.partialExposureDelta,self.minDelta),
                       ignore_index=True)
        # beads phase 1
        res=res.append(self._genSequence("beads1",res.seqNo.iloc[-1]+1,
                                         res.stopTime.iloc[-1],self.diamondsTime1,self.beadsIso,
                                         self.beadsExposure,0.0,self.minDelta),
                       ignore_index=True)

        # diamonds1
        res=res.append(self._genSequence("diamonds1",res.seqNo.iloc[-1]+1,
                                         res.stopTime.iloc[-1], self.c2Time, self.diamondIso,
                                         self.diamondExposure, 0.0, self.minDelta),
                       ignore_index=True)
        # totality C2 to max to C3
        res=res.append(self._genTotality("totality",res.seqNo.iloc[-1]+1,
                                         res.stopTime.iloc[-1],self.maxTime,self.c3Time,
                                         self.totalityMinIso,self.totalityMaxTime,
                                         self.totalityMinProduct,self.totalityMaxProduct,
                                         self.minDelta),
                       ignore_index=True)
        # diamonds2
        res=res.append(self._genSequence("diamonds2",res.seqNo.iloc[-1]+1,
                                         res.stopTime.iloc[-1], self.diamondsTime2, self.diamondIso,
                                         self.diamondExposure, 0.0, self.minDelta),
                       ignore_index=True)

        # beads phase 2
        res=res.append(self._genSequence("beads2",res.seqNo.iloc[-1]+1,
                                         res.stopTime.iloc[-1],self.beadsTime2,self.beadsIso,
                                         self.beadsExposure,0.0,self.minDelta),
                       ignore_index=True)


        #partial phase2
        res=res.append(self._genSequence("partial2",max(res.seqNo)+1,
                                         res.stopTime.iloc[-1], self.c4Time, self.partialIso,
                                         self.partialExposureSequence, self.partialExposureDelta, self.minDelta),
                       ignore_index=True)
        return res


class ScheduledCamera:
    """ camera that works on a schedule provided by a Scheduler Instance

    Also writes table of the currently taken photographs to csv in current working directory
    """

    def __init__(self,scheduler, camera):
        """ init
        :param scheduler: instance of Scheduler
        :param camera: instance of CanonCamera. If None, just simulate run
        """
        self.logFileName="schedCamLog_"+str(dt.datetime.now(UtcZone))+".csv"
        """ name of log file. Written whenever there is more than 5 seconds break"""
        self.scheduler=scheduler
        """ scheduler used"""
        self.camera=camera
        """ camera used. If none, simulate things"""

    def _takeShot(self,iso,exposureTime):
        """ take shot
        """

        if self.camera:
            self.camera.setIso(iso)
            self.camera.setExposureTime(exposureTime)
            self.camera.captureImage()
        else:
            # simulate shot
            print("simulating exposure of ISO=", iso,
                  ", exposureTime=", exposureTime, "(=1/", 1 / exposureTime, ")")
            pollingSleep(MINTIME-0.1+exposureTime)

    def _writeLog(self,log):
        """ write log
        """
        log.to_csv(self.logFileName)

    def run(self):
        """ take photos
        """
        log=pd.DataFrame()
        tolerance=0.2 #tolerance accepted for shots. The will be taken even if they are late by <=0.2 secs
        writeLogSeconds=5.0 # if wait time exceeds this value, write log
        for shot in self.scheduler.nextShot():
            print("Next Shot:",shot)
            start=shot.startTime

            seconds=(start-dt.datetime.now(UtcZone)).total_seconds() #time to wait until shot
            while seconds>0.0:
                # sleep until time is reached
                if seconds>writeLogSeconds:
                    #write log
                    self._writeLog(log)
                seconds = (start - dt.datetime.now(UtcZone)).total_seconds()  # time to wait until shot
                if seconds>0:
                    pollingSleep(seconds)
                seconds=(start-dt.datetime.now(UtcZone)).total_seconds() #time to wait until shot
            # take shot, otherwise skip shot
            iso=shot.ISO
            exposureTime=shot.exposureTime
            startTime=dt.datetime.now(UtcZone)
            self._takeShot(iso,exposureTime)
            stopTime=dt.datetime.now(UtcZone)
            shot["actualStartTime"]=startTime
            shot["actualStopTime"]=stopTime
            shot["done"]=True

            log=log.append(shot,ignore_index=True)
        self._writeLog(log)
        diffSequence = [(log.actualStartTime.iloc[i] -
                         log.startTime.iloc[i]).total_seconds()
                        for i in range(0, len(log))]
        log["diffFromScheduled"] = diffSequence
        pd.set_option('display.width', 200)
        pd.set_option('display.max_rows', 500)
        print("Schedule=")
        print(log[
                  ["seqNo", "phase","ISO","exposureTime","diffFromScheduled"]])

def main():
    """ main program
    """

    if False:
        # Tests with simulated camera
        scheduler = Scheduler(MINTIME, C1Time, C2Time, MaxTime, C3Time, C4Time)
        scheduledCamera=ScheduledCamera(scheduler,None)
        scheduledCamera.run()
        return
        #sequence = scheduler.genSchedule()
        #sequence=[el for el in scheduler.nextShot()]
        #print("SequenceList=",sequence)
        for shot in scheduler.nextShot():
            print("shot=",shot)
        sequence=pd.DataFrame(scheduler.nextShot())
        print(sequence)
        sequence["invExposureTime"] = 1.0 / sequence.exposureTime
        sequence["secondsFromC2"]=[(startTime-C2Time).total_seconds() for startTime in sequence["startTime"]]
        sequence["secondsFromC3"] = [(startTime - C3Time).total_seconds() for startTime in sequence["startTime"]]
        diffSequence=[(sequence.startTime.iloc[i]-
                                         sequence.startTime.iloc[i-1]).total_seconds()
                                         for i in range(1,len(sequence))]
        diffSequence.insert(0,-1.0)
        sequence["secondsFromPrevious"]=diffSequence
        pd.set_option('display.width', 200)
        pd.set_option('display.max_rows', 500)
        print("Schedule=")
        print(sequence[["seqNo","phase","secondsFromC2","secondsFromC3","secondsFromPrevious","ISO","exposureTime","invExposureTime"]])
        #print("Description=", sequence.describe())
        print("columns=", sequence.columns)
        return

    indiClient=None
    try:
        # Create an instance of the IndiClient class and initialize its host/port members
        indiclient = IndiClient()
        indiclient.setServer(INDI_HOST, INDI_PORT)
        indiclient.watchDevice(INDI_CAMERA)

        # Connect to server
        print("Connecting to server")
        if not (indiclient.connectServer()):
            print("Cannot connect to indiserver running on " + indiclient.getHost() + ":" + str(indiclient.getPort()) +
                  " - Try to run something like")
            print("  indiserver indi_simulator_telescope indi_simulator_ccd")
            sys.exit(1)
        pollingSleep(5)

        camera=CanonCamera(indiclient,INDI_CAMERA)

        if camera.getBulb():
            print("Please switch to to Manual an reconnect")
            return

        if False:
            #test with some shots
            #camera.setISO(300)
            exposureTimes=[1,0.5,0.2,0.1,0.02,0.01,1/200,1/1000,1/8000,1.0,1/8000,0.2,1,0.02,1]#[0.1,1,2,3,4]
            for eTime in exposureTimes:
                before = dt.datetime.now()
                camera.setExposureTime(eTime)
                camera.setIso(300)
                print("capture time,exposure=",eTime)
                camera.captureImage()
                after = dt.datetime.now()
                print("Exposure, start=", before, ", end=", before, ", duration=", after - before)

            return
        # real shots
        scheduler = Scheduler(MINTIME, C1Time, C2Time, MaxTime, C3Time, C4Time)
        scheduledCamera=ScheduledCamera(scheduler,camera)
        scheduledCamera.run()
    finally:
        if indiClient:
            # Disconnect from the indiserver
            print("Disconnecting")
            indiclient.disconnectServer()

if __name__ == "__main__":
    main()