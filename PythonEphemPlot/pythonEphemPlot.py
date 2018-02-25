#!/usr/bin/env python
""" Plot graphical overview of visibilities of solar system objects

uses matplotlib/numpy/pyephem
Note: pyephem is called pyephem in the Add/Remove software system of Fedora 17.
It is called ephem in pipy.python.org (pyephem there is the version for Pyhon3)
"""

def printTable(name,table):
    """ print rising/setting times as table for debugging
    """
    
    print ""
    print "Table for %s"%name
    for day,setting,rising in table:
        print "%s %s %s"%(day,setting,rising)
    print ""
        
def splitOffsets(table,bRisings):
    """ split days and offsets by None entries in offsets
    
    returns list of sequences (day, hourOffset), where each sequence
    is from a list of days where the chosen event has never been None.
    This sequence can be plotted as a partial curve for the events in table. The full
    plot can be done by plotting all sequences.
    """
    
    res=list()
    subList=list()
    for day,setting,rising in table:
        if bRisings:
            entry=rising
        else:
            entry=setting
        if entry!=None:
            subList.append( (day,entry) )
        elif len(subList)!=0:
            res.append(subList)
            subList=list()
    # add final sequence
    if len(subList)!=0:
        res.append(subList)
    return res;
            
        
def plotObject(ax,table,name,color):
    """ plot object given by table, name with color (e.g "y" for yellow)
    
    Risings are plotted as full line -, settings as broken line --.
    Legend handles are created.
    """
    
    import ephem
    
    table=tableToOffsets(table)
    settings=splitOffsets(table,False)
    risings=splitOffsets(table,True)
    legendLabel=name+" set"
    for entry in settings:
        days=map(lambda x: x[0],entry)
        offsets=map(lambda x: x[1],entry)
        ax.plot(days,offsets,"--",label=legendLabel,linewidth=2,color=color)
        # make sure we get only one entry for this object
        legendLabel=None
    legendLabel=name+" rise"
    for entry in risings:
        days=map(lambda x: x[0],entry)
        offsets=map(lambda x: x[1],entry)
        ax.plot(days,offsets,"-",label=legendLabel,linewidth=2,color=color)
        legendLabel=None

        
def calcSkyBrightness(observer,day,hour):
    """ estimate brightness of the sky for given location, day and hour
    
    This is an ad hoc formula. For serious work, use something like
    http://articles.adsabs.harvard.edu/cgi-bin/nph-iarticle_query?1991PASP..103.1033K&defaultprint=YES&filetype=.pdf
    
    Idea here: Values between 0 and 100. 100 is daylight, 0 dark night without moon. dark night astronomical darkness=
    sun 18 degrees below horizon. If moon is above horizon, add brightness 0..brightnessMul*maxMoonBrightness
    according to phase
    """
    import ephem
    
    #magnitude range of moon to consider
    minMoon=-6
    maxMoon=-12.8
    diffMoon=minMoon-maxMoon
    maxMoonBright=15.0
    brightnessFactor=1.0+1.0/maxMoonBright
    brightnessMul=5.0
    
    currentDate=day+hour*ephem.hour
    observer.date=currentDate
    sun=ephem.Sun()
    sun.compute(observer)
    moon=ephem.Moon()
    moon.compute(observer)
    sunAlt=sun.alt

    # angle for astronomical darkness
    darkAngle=ephem.hours(ephem.degree*18)
    brightness=0.0
    if sunAlt>0:
        # above horizon
        brightness=100
    else:
        if sunAlt>-darkAngle:
            # dusk/dawn
            brightness=(darkAngle+sunAlt)/darkAngle*100
        else:
            brightness=0
        # add moon
        if (moon.alt>0):
            # moon above horizon
            moonMag=min(minMoon,max(moon.mag,maxMoon))
            #value between 0 and 1 (for bright)
            moonBright= -(moonMag-minMoon)/diffMoon
            # empirical formula that also highlights full moon phases
            moonBright=1.0/(brightnessFactor-moonBright)*brightnessMul
            #print "moonMag",moonMag,moonBright
            # assumes range for moonMag between 
            brightness=min(brightness+moonBright,100)
    #print "Brightness",brightness 
    return brightness
            

def plotSkyBrightness(ax,observer,sunTable,hoursMin,hoursMax,hourStep):
    """ plot estimate of the brightness of the sky into ax (dark =deep blue, bright=white)
    
    - ax is the Axes object used for drawing
    - observer defines the location, 
    - sunTable is the table for the sun indicating the dates (x range) for the plot
    - hoursMin/Max is the y range of the plot 
    - hoursStep is the resolution for computations in the y range.
    """
    
    import numpy as np
    import pylab as pl
    
    days=map(lambda x: x[0],sunTable)
    daysMin=min(days)
    daysMax=max(days)
    hours=np.arange(hoursMin,hoursMax,hourStep)
    days,hours=np.meshgrid(days,hours)
    vecFunc=np.vectorize(calcSkyBrightness)
    brightness=vecFunc(observer,days,hours)
    # note flipped orientation in y
    brightness=np.flipud(brightness)
    ax.imshow(brightness,extent=[daysMin,daysMax,hoursMin,hoursMax],aspect="auto",cmap=pl.cm.PuBu_r)

def showFigure(bInteractive):
    """ show current figure. if bInteractive, show pylab plot dialog.
    
    Otherwise, created image is stores as file/store as new image in PixInsight
    """
    import numpy as np
    import matplotlib.pyplot as plt
    import matplotlib
    
    if bInteractive:
        plt.show()
    else:
        if hasPixInsight():
            # export to PixInsight
            #
            # FIXME tried to do it as shown below, but always got AttributeError: 
            # FigureCanvasGTKAgg' object has no attribute 'renderer' without earlier plt.show()
            # fig=plt.gcf()
            #fig.canvas.draw()
            #data = np.fromstring(fig.canvas.tostring_rgb(), dtype=np.uint8, sep='')
            #data = data.reshape(fig.canvas.get_width_height()[::-1] + (3,))
            #print data,data.shape
            import tempfile
            import os
            import pixinsight_api as pi
            handle,fileName=tempfile.mkstemp(suffix=".png")
            os.close(handle)
            plt.savefig(fileName)
            # transfer to PI
            print "PI should read %s"%fileName
            windows=pi.ImageWindow.open(fileName,"Visibilities",True,True)
            #print len(windows), windows
            for window in windows:
                window.show()
            os.remove(fileName)
        else:
            # just save to some file
            plt.savefig("test.png")
      
def plotSettingRising(title,utcOffset,year,observer,sunTable,objectsTable,bInteractive):
    """create plot of sun and moon as background, plus plot the objects in ObjectsTable
    
    objectsTable is list of triples (name,table,color)
    utcOffset is the offset of local time compared to UTC in hours (e.g. 1 for Munich winter time)
    year is the year for which computations should happen
    observer defines the location of the observer, ephem.observer object
    sunTable is the table of setting/rising times of the sun
    objectTable is the list of tables for other objects
    bInteractive: if true, display the pylab plot display dialog. Otherwise: Store result as
    file or (PixInsight mode) as new image
    """
    
    import matplotlib.pyplot as plt
    import ephem
    
    # plot sun
    sunTableOffsets=tableToOffsets(sunTable)
    days=map(lambda x: x[0],sunTableOffsets)
    settings=map(lambda x: x[1],sunTableOffsets)
    risings=map(lambda x: x[2],sunTableOffsets)
    fig=plt.figure(figsize=(11.69,8.27)) #A4
    ax=fig.add_subplot(111)
    ax.plot(days,settings,"--",color="gold",linewidth=3,label="Sunset")
    ax.plot(days,risings,"-",color="gold",linewidth=3,label="Sunrise")
    ylim=ax.get_ylim()
    
    # plot brightness indicator as background
    plotSkyBrightness(ax,observer,sunTable,ylim[0],ylim[1],0.25)
    
    # plot other objects, e.g. moon, planets, ...
    for name,table,color in objectsTable:
        plotObject(ax,table,name,color)

    # adjust y labels to UTC+offset time
    ax.set_ylabel("UTC%+g"%utcOffset)
    nLabels=len(ax.get_yticklabels())
    yLim=ax.get_ylim()
    step=float(yLim[1]-yLim[0])/(nLabels-1.0)
    labels=[(yLim[0]+i*step+utcOffset)%24 for i in range(0,nLabels+1)]
    ax.set_yticklabels(labels)
    
    # adjust x label and ticks to begin of month
    ax.set_xlabel("Begin of Month")
    ticks=[ephem.date( (year,month,1,0,0,0) ) for month in range(1,13)]
    ax.xaxis.set_ticks(ticks)
    ax.set_xticklabels(range(1,13))
        
    ax.set_title(title)
    ax.grid(True)
          
    # legend
    handles, labels = ax.get_legend_handles_labels()
    # Shink current axes to get spaces of labels
    box = ax.get_position()
    ax.set_position([box.x0, box.y0, box.width * 0.9, box.height])
    # Put a legend to the right of the current axis
    ax.legend(handles,labels,loc='center left', bbox_to_anchor=(1, 0.5))
    ax.set_xlim(min(days),max(days))

    # show
    showFigure(bInteractive)
    
def tableToOffsets(table):
    """ translate tables of settings and risings to ephem date 0am UTC and offset from UTC in hours float
    """
    
    import datetime
    
    res=list()
    for currentDay,setting,rising in table:
        cYear,cMonth,cDay,cHour,cMinute,cSecond=currentDay.tuple()
        day=datetime.datetime(cYear,cMonth,cDay,cHour,cMinute,int(cSecond))
        if setting!=None:
            sYear,sMonth,sDay,sHour,sMinute,sSecond=setting.tuple()
            settingTime=datetime.datetime(sYear,sMonth,sDay,sHour,sMinute,int(sSecond))
            # offset to begin of day in hours
            sOffset=(settingTime-day).total_seconds()/3600.0
        else:
            sOffset=None
        if rising!=None:
            rYear,rMonth,rDay,rHour,rMinute,rSecond=rising.tuple()
            risingTime=datetime.datetime(rYear,rMonth,rDay,rHour,rMinute,int(rSecond))
            rOffset=(risingTime-day).total_seconds()/3600.0
        else:
            rOffset=None
        res.append( (currentDay,sOffset,rOffset))
    return res
        
def createTableObject(observer,sunTable,object):
    """ create table of days, setting and rising times for given object
    
    This happens for the days given in the sun table. setting and rising times are
    considered only if during night, otherwise entry is None
    """
    
    res=list()
    for day,sunSet,sunRise in sunTable:
        # we are only interest in events after sunSet
        observer.date=sunSet
        nextSetting=observer.next_setting(object)
        nextRising=observer.next_rising(object)
        if nextSetting>sunRise:
            nextSetting=None
        if nextRising>sunRise:
            nextRising=None
        res.append((day,nextSetting,nextRising))   
    return res
    
          
def createTableSun(observer,year,dayStep=1):
    """ Create table with rising and setting times for the sun
    
    observer is an ephem observer, year is an int giving the desired year, dayStep int specifying the
    distance of days between computations.
    returned table contains pairs of setting/rising times for the night of each day of the year
    returned dates/times are ephem.date, i.e. UTC as float subclass.
    """
    
    import ephem
    import datetime
    object=ephem.Sun()
    # we start on Jan 1st 0am UTC.
    startDate=ephem.date((year,1,1,0,0) )
    # compute days in year
    days=(datetime.date(year+1,1,1)-datetime.date(year,1,1)).days
    res=list()
    #print "days",days
    for day in range(0,days):
        currentDate=ephem.date(startDate+day)
        year,month,day,hour,minute,second=currentDate.tuple()
        observer.date=currentDate
        nextSetting=observer.next_setting(object)
        observer.date=nextSetting
        nextRising=observer.next_rising(object)
        #print nextRising,nextSetting
        res.append( (currentDate,nextSetting,nextRising) )
    return res

def hasPixInsight():
    """ returns true if this environment supports the pixinsight module
    """
    try:
        import pixinsight_api
    except ImportError:
        return False
    return True
    
def main():
    """evaluate args and do what is requestede
    """
    import argparse
    import datetime
    import ephem
    import ephem.cities
    
    cities=str([key for key in ephem.cities._city_data.keys()])
    parser = argparse.ArgumentParser(description='plot the visibilities of the main solar system objects.')
    parser.add_argument("-y","--year",type=int,default=datetime.date.today().year+1,
                        help="select year for ephemeris. Default is current year+1.")
    parser.add_argument("-c","--city",default="Munich",
                        help="select city, is overriden by -l. One of "+cities+". Default: Munich.")
    parser.add_argument("-u","--utc",default=1,type=float,
                        help="offset of local time to UTC time. Default 1.")
    parser.add_argument("-l","--loc",default=[],type=float,nargs=5,metavar="f",
                        help="define observer location. Format is: lat lon elevation temp pressure, "
                        "with f being lat=latitude (+N), lon=longitude (+E), elevation in meters, temperature in deg.C, "
                        "pressure in mBar respectively. Example for Munich: 48.15 11.5833333 508.7112 15 1000. Default: None.")
    parser.add_argument("-t","--title",default=None,
                        help="Title for plot. Default is \"Visibilities for city year\"")
    if hasPixInsight():
        parser.add_argument("-i","--interactive",default=False,action="store_true",
                            help="In PixInsight environment: force interactve operation instead of storing result in new image")
    values=parser.parse_args()
    year=values.year
    
    utcOffset=values.utc
    if hasPixInsight():
        bInteractive=values.interactive;
    else:
        bInteractive=True
    dayStep=1
    if (len(values.loc)==0):
        observer=ephem.city(values.city)
    else:
        loc=values.loc
        lon,lat,elevation,temp,pressure=loc
        observer=ephem.Observer()
        observer.long=lon/180.0*ephem.pi
        observer.lat=lat/180.0*ephem.pi
        observer.elevation=elevation
        observer.temp=temp
        observer.pressure=pressure
    if (values.title==None):
        if(len(values.loc)!=0):
            title="Visibilities for Lon=%f Lat=%f Year=%d"%(observer.long,observer.lat,year)
        else:
            title="Visibilities for %s %d"%(values.city,values.year)
    else:
        title=values.title
    sunTable=createTableSun(observer,year,dayStep)
    # modify here to include the objects that are interesting for you
    objects=[("Mercury",ephem.Mercury(),"c"),
             ("Venus",ephem.Venus(),"y"),
             ("Moon",ephem.Moon(),"gray"),
             ("Mars",ephem.Mars(),"r"),
             ("Jupiter",ephem.Jupiter(),"g"),
             ("Saturn",ephem.Saturn(),"m")]
    objectsTable=list()
    for name,object,color in objects:
        table=createTableObject(observer,sunTable,object)
        objectsTable.append( (name,table,color) )
    plotSettingRising(title,utcOffset,year,observer,sunTable,objectsTable,bInteractive)
    
def execute_global():
    """ main function for PixInsight mode
    """
    try:
        main()
        
    except SystemExit as e:
        # without this catch, whole process (incl. PI) terminates.
        print "Python sys.exit(%s) called"%(e.code)
        return True
    return True

if __name__=="__main__":
    if not hasPixInsight():
        # called when run from the comamnd line
        main()
    else:
        print "loaded as PixInsight Python script."
    